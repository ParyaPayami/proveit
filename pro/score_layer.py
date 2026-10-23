"""Score My Layer: pair any prediction layer with public truth records, then score it.

Runs inside ArcGIS Pro. Handles three prediction shapes and five outcome kinds:

  prediction  | event / presence            | measure                 | label (yes/no)         | areal_measure
  ------------+-----------------------------+-------------------------+------------------------+--------------
  polygons    | count per polygon  (count)  | median per polygon      | share yes per polygon  | join by key
  points      | any within distance (binary)| nearest within distance | nearest within distance| join by key
  raster      | value at records vs random  | value at records        | value at records       | -
              | control points (presence)   |                         |                        |

Usage: bin/pro pro/score_layer.py <config.json>   (or the Score My Layer tool)
Config keys: prediction, field, source, start, end, where, higher_means ("more"|"less"),
prediction_date, distance_m, key_field, min_records, same_units, tolerance, controls, name.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import OUTPUTS, WORK, log, sha256, work_gdb, write_json  # noqa: E402
from proveit import score, truth  # noqa: E402

import arcpy  # noqa: E402

DEFAULTS = {
    "higher_means": "more", "distance_m": 30, "min_records": 1, "same_units": False, "tolerance": None,
    "controls": 5, "where": None, "start": None, "end": None, "prediction_date": None, "key_field": None,
    "outcome_as": "count",      # polygons x events: "count" per polygon, or "any" (yes/no, scored by AUC)
    "polygon_match": "inside",  # or "nearest": each record goes to the closest polygon within distance_m
    "match_key": None,          # e.g. ["bbl", "bbl"]: prediction field, truth field; location is the fallback
    "prediction_where": None,   # definition query on the prediction layer, e.g. "year_built_2020 < 2015"
    "key_members": None,        # area sources: prediction fields listing member codes, e.g. ["zcta", "label"]
}


def _shape(pred: str) -> str:
    d = arcpy.Describe(pred)
    if getattr(d, "dataType", "") in ("RasterDataset", "RasterLayer", "MosaicDataset", "RasterBand"):
        return "raster"
    return {"Polygon": "polygons", "Point": "points", "Multipoint": "points"}.get(getattr(d, "shapeType", ""), "other")


def _wgs84_bbox(pred: str) -> list[float]:
    ext = arcpy.Describe(pred).extent.projectAs(arcpy.SpatialReference(4326))
    return [round(ext.XMin, 6), round(ext.YMin, 6), round(ext.XMax, 6), round(ext.YMax, 6)]


def _load_truth(path: Path, gdb: str, sr) -> str:
    local = WORK / "truth.geojson"
    shutil.copyfile(path, local)
    gj = json.loads(local.read_text())
    gtype = next((f["geometry"]["type"] for f in gj["features"] if f.get("geometry")), "Point")
    raw = arcpy.conversion.JSONToFeatures(str(local), f"{gdb}\\truth_raw", "POLYGON" if "Polygon" in gtype else "POINT")[0]
    if "Polygon" in gtype:  # match polygons (e.g. building footprints) by an interior point
        raw = arcpy.management.FeatureToPoint(raw, f"{gdb}\\truth_pts", "INSIDE")[0]
    out = arcpy.management.Project(raw, f"{gdb}\\truth", sr)[0]
    arcpy.management.CalculateField(out, "tid", "!OBJECTID!", "PYTHON3", field_type="LONG")  # survives later copies
    return out


def _truth_rows(fc: str, key: str | None = None) -> dict[int, dict]:
    fields = [f.name for f in arcpy.ListFields(fc)]
    want = [f for f in ("value", "label", "label_raw", "date", key) if f and f in fields]
    return {r[0]: dict(zip(want, r[1:])) for r in arcpy.da.SearchCursor(fc, ["OID@"] + want)}


def _pairs_polygons(pred, field, tfc, kind, gdb, outcome_as="count", polygon_match="inside", distance_m=30, match_key=None):
    rows = _truth_rows(tfc, match_key[1] if match_key else None)
    groups: dict[int, list] = defaultdict(list)
    preds = {oid: pv for oid, pv in arcpy.da.SearchCursor(pred, ["OID@", field])}
    matched, by_key = set(), 0
    if match_key:
        # Shared IDs (e.g. tax lot BBL) beat geometry; records without a matching ID fall back to location.
        norm = lambda v: str(v).split(".")[0].strip() if v not in (None, "") else None  # noqa: E731
        lookup = {norm(k): oid for oid, k in arcpy.da.SearchCursor(pred, ["OID@", match_key[0]]) if norm(k)}
        for tid, r in rows.items():
            pid = lookup.get(norm(r.get(match_key[1])))
            if pid is not None:
                groups[pid].append(r)
                matched.add(tid)
        by_key = len(matched)
    if polygon_match == "nearest":
        # Records geocoded to a street frontage sit just outside their lot: give each to the closest polygon.
        near = arcpy.analysis.GenerateNearTable(tfc, pred, f"{gdb}\\near", f"{distance_m} Meters", closest="CLOSEST")[0]
        for tid, pid in arcpy.da.SearchCursor(near, ["IN_FID", "NEAR_FID"]):
            if tid not in matched:
                groups[pid].append(rows[tid])
                matched.add(tid)
    elif not match_key:
        sj = arcpy.analysis.SpatialJoin(pred, tfc, f"{gdb}\\sj", "JOIN_ONE_TO_MANY", "KEEP_ALL", match_option="INTERSECT")[0]
        for pid, jid in arcpy.da.SearchCursor(sj, ["TARGET_FID", "JOIN_FID"]):
            if jid is not None and jid >= 0:
                groups[pid].append(rows[jid])
                matched.add(jid)
    pairs, excluded = [], 0
    for fid, pv in preds.items():
        recs = groups.get(fid, [])
        if kind in ("event", "presence"):
            pairs.append({"id": fid, "pred": pv, "outcome": len(recs), "n": len(recs)})
        elif kind == "measure":
            vals = [r["value"] for r in recs if r.get("value") is not None]
            pairs.append({"id": fid, "pred": pv, "outcome": statistics.median(vals) if vals else None, "n": len(vals)})
        elif kind == "label":
            labs = [r["label"] for r in recs if r.get("label") is not None]
            excluded += sum(1 for r in recs if r.get("label") is None)
            pairs.append({"id": fid, "pred": pv, "outcome": (sum(labs) / len(labs)) if labs else None, "n": len(labs),
                          "excluded": sum(1 for r in recs if r.get("label") is None)})
    test = {"event": "count", "presence": "count", "measure": "continuous", "label": "continuous"}[kind]
    if kind in ("event", "presence") and outcome_as == "any":
        for p in pairs:
            p["outcome"] = 1 if p["n"] > 0 else 0
        test = "binary"
    if kind == "label" and sum(p["n"] > 1 for p in pairs) <= 0.05 * max(len(pairs), 1):
        # About one inspected record per feature (e.g. building footprints): score it as yes/no,
        # with the rare multi-record feature counted as yes when most of its records are.
        test = "binary"
        for p in pairs:
            if p["outcome"] is not None:
                p["outcome"] = 1 if p["outcome"] >= 0.5 else 0
    extra = {"truth_unmatched": len(rows) - len(matched), "truth_total": len(rows), "labels_excluded": excluded,
             "polygon_match": polygon_match, "matched_by_key": by_key, "matched_by_location": len(matched) - by_key}
    if polygon_match == "inside" and not match_key and rows and len(matched) < 0.5 * len(rows):
        near = arcpy.management.SelectLayerByLocation(arcpy.management.MakeFeatureLayer(tfc, "tnear")[0],
                                                      "WITHIN_A_DISTANCE", pred, f"{distance_m} Meters")[0]
        extra["truth_within_distance"] = int(arcpy.management.GetCount(near)[0])
    return pairs, test, extra


def _pairs_points(pred, field, tfc, kind, gdb, distance_m):
    rows = _truth_rows(tfc)
    if kind in ("event", "presence"):
        sj = arcpy.analysis.SpatialJoin(pred, tfc, f"{gdb}\\sj", "JOIN_ONE_TO_ONE", "KEEP_ALL",
                                        match_option="WITHIN_A_DISTANCE", search_radius=f"{distance_m} Meters")[0]
        pairs = [{"id": fid, "pred": pv, "outcome": 1 if n > 0 else 0, "n": n}
                 for fid, pv, n in arcpy.da.SearchCursor(sj, ["TARGET_FID", field, "Join_Count"])]
        return pairs, "binary", {}
    sj = arcpy.analysis.SpatialJoin(pred, tfc, f"{gdb}\\sj", "JOIN_ONE_TO_ONE", "KEEP_ALL", match_option="CLOSEST",
                                    search_radius=f"{distance_m} Meters")[0]
    fields = [f.name for f in arcpy.ListFields(sj)]
    col = "value" if kind == "measure" else "label"
    pairs, excluded = [], 0
    for fid, pv, n, out in arcpy.da.SearchCursor(sj, ["TARGET_FID", field, "Join_Count", col if col in fields else "Join_Count"]):
        if kind == "label" and n and out is None:
            excluded += 1
        pairs.append({"id": fid, "pred": pv, "outcome": out if n else None, "n": n, "excluded": int(bool(n and out is None))})
    return pairs, ("continuous" if kind == "measure" else "binary"), {"labels_excluded": excluded}


def _pairs_raster(pred, tfc, kind, gdb, controls, seed=42):
    ras = arcpy.Raster(pred)
    vals = arcpy.sa.ExtractValuesToPoints(tfc, ras, f"{gdb}\\truth_vals", "NONE", "VALUE_ONLY")
    rows = _truth_rows(tfc)
    pairs = []
    for oid, v in arcpy.da.SearchCursor(vals, ["tid", "RASTERVALU"]):
        if v is None or v == -9999:
            continue
        r = rows.get(oid, {})
        out = 1 if kind in ("event", "presence") else (r.get("value") if kind == "measure" else r.get("label"))
        pairs.append({"id": f"t{oid}", "pred": v, "outcome": out, "n": 1})
    meta = {}
    if kind in ("event", "presence"):
        n = controls * max(len(pairs), 1)
        ext = arcpy.Describe(ras).extent
        cp = arcpy.management.CreateRandomPoints(gdb, "controls", None, ext, n)[0]
        arcpy.management.DefineProjection(cp, ras.spatialReference)
        cv = arcpy.sa.ExtractValuesToPoints(cp, ras, f"{gdb}\\control_vals", "NONE", "VALUE_ONLY")
        cvals = [v for (v,) in arcpy.da.SearchCursor(cv, ["RASTERVALU"]) if v is not None and v != -9999]
        pairs += [{"id": f"c{i}", "pred": v, "outcome": 0, "n": 0} for i, v in enumerate(cvals)]
        meta = {"control_points": len(cvals), "control_seed": seed}
        return pairs, "presence", meta
    return pairs, ("continuous" if kind == "measure" else "binary"), meta


def _pairs_areal(pred, field, key_field, records, member_fields=None):
    """Join area totals by code. With member_fields (prediction fields listing the source codes an
    area contains, comma-separated), several source codes roll up into one prediction area."""
    member_of = {}
    fields = ["OID@", field, key_field] + list(member_fields or [])
    rows = list(arcpy.da.SearchCursor(pred, fields))
    norm = lambda v: str(v).split(".")[0].strip()  # noqa: E731
    for row in rows:
        key = norm(row[2])
        member_of.setdefault(key, key)
        for listed in row[3:]:
            for code in str(listed or "").split(","):
                if code.strip():
                    member_of.setdefault(norm(code), key)
    combined, unmatched = truth.combine_areal(records, member_of)
    pairs = []
    for fid, pv, key, *_ in rows:
        r = combined.get(norm(key))
        pairs.append({"id": fid, "pred": pv, "outcome": r["value"] if r else None, "n": r["n"] if r else 0})
    return pairs, "continuous", {"truth_keys_unmatched": len(unmatched),
                                 "truth_records_unmatched": sum(r["n"] for r in unmatched),
                                 "areas_combined_from_several_codes": sum(1 for r in combined.values() if r["parts"] > 1)}


def _residual_layer(pred, pairs, gdb, name) -> str | None:
    """Copy of the prediction features with outcome and rank gap, for mapping where the model was wrong."""
    ok = [p for p in pairs if isinstance(p["id"], int) and p["outcome"] is not None and p["pred"] is not None]
    if not ok:
        return None
    rp = score.ranks([float(p["pred"]) for p in ok])
    ro = score.ranks([float(p["outcome"]) for p in ok])
    info = {p["id"]: (p["outcome"], p["n"], (o - r) / len(ok)) for p, r, o in zip(ok, rp, ro)}
    out = arcpy.management.CopyFeatures(pred, f"{gdb}\\{name}_scored")[0]
    for f, t in (("pi_outcome", "DOUBLE"), ("pi_records", "LONG"), ("pi_rank_gap", "DOUBLE")):
        arcpy.management.AddField(out, f, t)
    with arcpy.da.UpdateCursor(out, ["OID@", "pi_outcome", "pi_records", "pi_rank_gap"]) as cur:
        for row in cur:
            if row[0] in info:
                cur.updateRow([row[0], *info[row[0]]])
    return out


def run(cfg: dict) -> dict:
    cfg = DEFAULTS | cfg
    arcpy.env.overwriteOutput = True
    name = cfg.get("name") or "score"
    out_dir = OUTPUTS / "score" / name
    out_dir.mkdir(parents=True, exist_ok=True)
    gdb = work_gdb("score_" + name, fresh=True)
    src = truth.source(cfg["source"])
    kind = src["outcome"]["kind"]
    pred = cfg["prediction"]
    subset = None
    if cfg["prediction_where"]:
        # Score a subset (an ordinary ArcGIS definition query), e.g. leave out lots already built at the cutoff.
        # Records are matched against all features first, so a record whose own feature is left out
        # is dropped instead of being handed to a neighbour.
        lyr = arcpy.management.MakeFeatureLayer(pred, "pred_subset", cfg["prediction_where"])[0]
        subset = {oid for (oid,) in arcpy.da.SearchCursor(lyr, ["OID@"])}
    shape = _shape(pred)
    bbox = cfg.get("bbox") or _wgs84_bbox(pred)
    log(f"{shape} prediction vs {src['name']} ({kind})")

    path, tmeta = truth.get(cfg["source"], None if kind == "areal_measure" else bbox, cfg["start"], cfg["end"], cfg["where"])
    log(f"truth: {tmeta['records']:,} records")
    if kind == "areal_measure":
        if not cfg["key_field"]:
            raise ValueError(f"{src['name']} is published by area; set key_field to the prediction's matching code field")
        pairs, test, extra = _pairs_areal(pred, cfg["field"], cfg["key_field"], json.loads(path.read_text()),
                                          cfg["key_members"])
    else:
        sr = arcpy.Describe(pred).spatialReference
        tfc = _load_truth(path, gdb, sr)
        if shape == "polygons":
            pairs, test, extra = _pairs_polygons(pred, cfg["field"], tfc, kind, gdb, cfg["outcome_as"],
                                                 cfg["polygon_match"], cfg["distance_m"], cfg["match_key"])
        elif shape == "points":
            pairs, test, extra = _pairs_points(pred, cfg["field"], tfc, kind, gdb, cfg["distance_m"])
        elif shape == "raster":
            arcpy.CheckOutExtension("Spatial")
            pairs, test, extra = _pairs_raster(pred, tfc, kind, gdb, cfg["controls"])
        else:
            raise ValueError(f"unsupported prediction layer: {pred}")

    if subset is not None:
        dropped = [p for p in pairs if isinstance(p["id"], int) and p["id"] not in subset]
        extra["subset_where"] = cfg["prediction_where"]
        extra["subset_excluded_features"] = len(dropped)
        extra["subset_excluded_with_outcome"] = sum(1 for p in dropped if p.get("n"))
        pairs = [p for p in pairs if not isinstance(p["id"], int) or p["id"] in subset]
    with open(out_dir / "pairs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id", "pred", "outcome", "n", "excluded"], extrasaction="ignore")
        w.writeheader()
        w.writerows(pairs)
    meta = {
        "name": name, "config": cfg, "shape": shape, "test": test, "source": src, "truth": tmeta,
        "pairing": extra, "features": sum(1 for p in pairs if isinstance(p["id"], int) or shape != "raster"),
        "prediction_layer": str(pred),
    }
    write_json(out_dir / "meta.json", meta)
    card = score.score_pairs(meta, pairs)
    write_json(out_dir / "scorecard.json", card)
    (out_dir / "report.html").write_text(score.report_html(card), encoding="utf-8")
    layer = _residual_layer(pred, pairs, gdb, name) if shape != "raster" else None
    log(f"{card['headline']}")
    log(f"report: {out_dir / 'report.html'}")
    return {"scorecard": card, "out_dir": str(out_dir), "layer": layer}


if __name__ == "__main__":
    cfg = json.loads(Path(sys.argv[1]).read_text())
    run(cfg)
