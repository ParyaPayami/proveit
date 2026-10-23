"""Truth catalog: find public outcome records and download them in one standard shape.

Every source in catalog/*.json says where its records live (adapter), what they
measure (outcome) and what can go wrong with them (traps). `get()` returns a
GeoJSON file of points (or polygons for ArcGIS layers) whose properties always
include `date`, `value`, `label` and `category`, or, for sources published as
area totals, a JSON list of {key, n, value}. Standard library only, so it runs
on the Mac and inside ArcGIS Pro's Python.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CATALOG = PROJECT / "catalog"
CACHE = PROJECT / "data" / "truth"
PAGE = 50000
UA = "proveit/0.2 (research; public open data)"


# ----------------------------------------------------------------- catalog

def sources() -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CATALOG.glob("*.json"))]


def source(source_id: str) -> dict:
    path = CATALOG / f"{source_id}.json"
    if not path.exists():
        raise KeyError(f"no truth source '{source_id}'; see catalog/")
    return json.loads(path.read_text(encoding="utf-8"))


def _overlaps(a: list[float], b: list[float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def find(bbox: list[float] | None = None, topic: str = "", text: str = "") -> list[dict]:
    """Sources whose coverage overlaps `bbox` (lon/lat) and match a topic or free text."""
    out = []
    for s in sources():
        cov = s.get("coverage", {}).get("bbox")
        if bbox and cov and not _overlaps(bbox, cov):
            continue
        hay = " ".join([s["name"], " ".join(s.get("topics", [])), s.get("outcome", {}).get("describes", "")]).lower()
        if topic and topic.lower() not in " ".join(s.get("topics", [])).lower():
            continue
        if text and not all(w in hay for w in text.lower().split()):
            continue
        out.append(s)
    return out


def combine_areal(records: list[dict], member_of: dict[str, str]) -> tuple[dict[str, dict], list[dict]]:
    """Roll area totals published by one code (e.g. postal ZIP) up to the prediction's areas.

    `member_of` maps a source code to a prediction-area code. Values are combined as an
    n-weighted mean, which approximates (but is not) the median of the merged records.
    Returns ({area: {"n", "value", "parts"}}, unmatched records).
    """
    acc: dict[str, list] = {}
    unmatched = []
    for r in records:
        area = member_of.get(r["key"])
        if area is None or r.get("value") is None:
            unmatched.append(r)
            continue
        acc.setdefault(area, []).append(r)
    out = {}
    for area, parts in acc.items():
        n = sum(p["n"] for p in parts)
        out[area] = {"n": n, "value": sum(p["n"] * p["value"] for p in parts) / n, "parts": len(parts)}
    return out, unmatched


# ----------------------------------------------------------------- download

def _curl(url: str, timeout: int = 600) -> bytes:
    # curl uses the system certificate store on macOS and Windows alike.
    return subprocess.run(["curl", "-fsSL", "--retry", "3", "-m", str(timeout), "-A", UA, url],
                          check=True, capture_output=True).stdout


def _json(url: str):
    return json.loads(_curl(url).decode("utf-8-sig"))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(v, fmt: str | None) -> str | None:
    if not v:
        return None
    try:
        if fmt:
            return dt.datetime.strptime(str(v)[:10], fmt).date().isoformat()
        return str(v)[:10]
    except ValueError:
        return None


def _in_window(day: str | None, start: str | None, end: str | None) -> bool:
    if day is None:
        return not (start or end)
    return (not start or day >= start) and (not end or day <= end)


def _point(lon, lat) -> dict | None:
    x, y = _num(lon), _num(lat)
    if x is None or y is None or (x == 0 and y == 0):
        return None
    return {"type": "Point", "coordinates": [x, y]}


def _socrata_where(a: dict, bbox, start, end, where) -> list[str]:
    parts = [f"({a['base_where']})"] if a.get("base_where") else []
    if where:
        parts.append(f"({where})")
    df = a.get("date_field")
    if df and not a.get("date_format"):  # text dates can't be range-filtered on the portal
        if start:
            parts.append(f"{df} >= '{start}T00:00:00'")
        if end:
            parts.append(f"{df} <= '{end}T23:59:59'")
    if bbox:
        w, s, e, n = bbox
        if a.get("point"):
            parts.append(f"within_box({a['point']}, {n}, {w}, {s}, {e})")
        elif a.get("lat"):
            cast = "::number" if a.get("coords_are_text") else ""
            parts.append(f"{a['lat']}{cast} between {s} and {n} AND {a['lon']}{cast} between {w} and {e}")
    return parts


def _socrata_rows(domain: str, dataset: str, params: dict, max_rows: int) -> tuple[list[dict], bool]:
    rows, offset = [], 0
    while True:
        q = dict(params, **{"$limit": PAGE, "$offset": offset, "$order": ":id"})
        batch = _json(f"https://{domain}/resource/{dataset}.json?" + urllib.parse.urlencode(q))
        rows += batch
        if len(batch) < PAGE:
            return rows, False
        offset += PAGE
        if offset >= max_rows:
            return rows, True


def _feature(geom, day, value, label_raw, outcome, category, keep: dict) -> dict:
    pos, neg = outcome.get("positive_values"), outcome.get("negative_values")
    label = None
    if pos is not None:
        label = 1 if label_raw in pos else 0 if label_raw in (neg or []) else None
    props = {"date": day, "value": value, "label": label, "label_raw": label_raw, "category": category}
    props.update({k: v for k, v in keep.items() if k not in props})
    return {"type": "Feature", "geometry": geom, "properties": props}


def _socrata(s: dict, bbox, start, end, where, max_rows) -> tuple[list[dict], dict]:
    a, o = s["adapter"], s["outcome"]
    rows, truncated = _socrata_rows(a["domain"], a["dataset"],
                                    {"$where": " AND ".join(_socrata_where(a, bbox, start, end, where)) or "1=1"}, max_rows)
    feats, dropped = [], {"no_location": 0, "outside_dates": 0, "bad_date": 0}
    factor = a.get("value_factor", 1)
    for r in rows:
        geom = _point(r.get(a["point"], {}).get("coordinates", [None, None])[0], r.get(a["point"], {}).get("coordinates", [None, None])[1]) \
            if a.get("point") and isinstance(r.get(a["point"]), dict) else _point(r.get(a.get("lon")), r.get(a.get("lat")))
        if geom is None:
            dropped["no_location"] += 1
            continue
        day = _parse_date(r.get(a.get("date_field")), a.get("date_format")) if a.get("date_field") else None
        if a.get("date_field") and day is None and r.get(a["date_field"]):
            dropped["bad_date"] += 1
            continue
        if a.get("date_format") and not _in_window(day, start, end):
            dropped["outside_dates"] += 1
            continue
        val = _num(r.get(a.get("value_field"))) if a.get("value_field") else None
        feats.append(_feature(geom, day, val * factor if val is not None else None, r.get(a.get("label_field")), o,
                              r.get(a.get("category_field")), {k: r.get(k) for k in a.get("keep", [])}))
    return feats, {"rows": len(rows), "truncated": truncated, "dropped": dropped}


def _socrata_join(s: dict, bbox, start, end, where, max_rows) -> tuple[list[dict], dict]:
    a, o = s["adapter"], s["outcome"]
    site = a["sites"]
    sites, _ = _socrata_rows(a["domain"], site["dataset"], {}, max_rows)
    loc = {r[a["join_key"]]: r for r in sites if r.get(site["lat"])}
    parts = [f"({where})"] if where else []
    if start:
        parts.append(f"{a['date_field']} >= '{start}T00:00:00'")
    if end:
        parts.append(f"{a['date_field']} <= '{end}T23:59:59'")
    rows, truncated = _socrata_rows(a["domain"], a["dataset"], {"$where": " AND ".join(parts) or "1=1"}, max_rows)
    feats, unmatched = [], 0
    for r in rows:
        site_row = loc.get(r.get(a["join_key"]))
        geom = _point(site_row[site["lon"]], site_row[site["lat"]]) if site_row else None
        if geom is None:
            unmatched += 1
            continue
        lon, lat = geom["coordinates"]
        if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
            continue
        val = _num(r.get(a["value_field"]))
        keep = {k: site_row.get(k) for k in site.get("keep", [])} | {a["join_key"]: r.get(a["join_key"])}
        feats.append(_feature(geom, _parse_date(r.get(a["date_field"]), None),
                              val * a.get("value_factor", 1) if val is not None else None, None, o, None, keep))
    return feats, {"rows": len(rows), "truncated": truncated, "dropped": {"no_site_location": unmatched}}


def _socrata_aggregate(s: dict, bbox, start, end, where, max_rows) -> tuple[list[dict], dict]:
    a = s["adapter"]
    parts = [f"({a['base_where']})"] if a.get("base_where") else []
    if where:
        parts.append(f"({where})")
    if start:
        parts.append(f"{a['date_field']} >= '{start}T00:00:00'")
    if end:
        parts.append(f"{a['date_field']} <= '{end}T23:59:59'")
    k, v = a["key_field"], a["value_field"]
    q = {"$select": f"{k} as key, count(*) as n, median({v}) as value", "$where": " AND ".join(parts) or "1=1",
         "$group": k, "$limit": max_rows}
    rows = _json(f"https://{a['domain']}/resource/{a['dataset']}.json?" + urllib.parse.urlencode(q))
    out = [{"key": (r.get("key") or "").split(".")[0], "n": int(r["n"]), "value": _num(r.get("value"))} for r in rows]
    return out, {"rows": len(out), "truncated": False, "dropped": {}}


def _csv_url(s: dict, bbox, start, end, where, max_rows) -> tuple[list[dict], dict]:
    import csv

    a, o = s["adapter"], s["outcome"]
    lines = _curl(a["url"]).decode("utf-8-sig").splitlines()[a.get("header_line", 0):]
    feats, dropped = [], {"no_location": 0}
    for r in csv.DictReader(lines):
        geom = _point(r.get(a["lon"]), r.get(a["lat"]))
        if geom is None:
            dropped["no_location"] += 1
            continue
        lon, lat = geom["coordinates"]
        if bbox and not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
            continue
        val = _num(r.get(a.get("value_field")))
        feats.append(_feature(geom, a.get("fixed_date"), val * a.get("value_factor", 1) if val is not None else None,
                              None, o, None, {k: r.get(k) for k in a.get("keep", [])}))
    return feats, {"rows": len(feats), "truncated": False, "dropped": dropped}


def _arcgis_layer(s: dict, bbox, start, end, where, max_rows) -> tuple[list[dict], dict]:
    a, o = s["adapter"], s["outcome"]
    feats, offset = [], 0
    while True:
        q = {"where": where or "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
             "resultOffset": offset, "resultRecordCount": 2000, "orderByFields": "OBJECTID"}
        if bbox:
            q |= {"geometry": ",".join(map(str, bbox)), "geometryType": "esriGeometryEnvelope", "inSR": 4326,
                  "spatialRel": "esriSpatialRelIntersects"}
        batch = _json(a["url"] + "/query?" + urllib.parse.urlencode(q)).get("features", [])
        for f in batch:
            p = f.get("properties", {})
            feats.append(_feature(f.get("geometry"), a.get("fixed_date"), _num(p.get(a.get("value_field"))),
                                  p.get(a.get("label_field")), o, p.get(a.get("category_field")),
                                  {k: p.get(k) for k in a.get("keep", [])}))
        if len(batch) < 2000 or len(feats) >= max_rows:
            return feats, {"rows": len(feats), "truncated": len(batch) == 2000 and len(feats) >= max_rows, "dropped": {}}
        offset += 2000


ADAPTERS = {"socrata": _socrata, "socrata_join": _socrata_join, "socrata_aggregate": _socrata_aggregate,
            "csv_url": _csv_url, "arcgis_layer": _arcgis_layer}


def get(source_id: str, bbox: list[float] | None = None, start: str | None = None, end: str | None = None,
        where: str | None = None, max_rows: int = 500000, refresh: bool = False) -> tuple[Path, dict]:
    """Download truth records once per request; returns (data file, metadata)."""
    s = source(source_id)
    a = s["adapter"]
    if a["type"] == "manual":
        raise RuntimeError(f"{s['name']} needs a manual download: {a['instructions']} ({a['url']})")
    request = {"source": source_id, "bbox": bbox, "start": start, "end": end, "where": where, "max_rows": max_rows}
    tag = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()[:12]
    folder = CACHE / source_id
    data_path, meta_path = folder / f"{tag}.json", folder / f"{tag}.meta.json"
    if data_path.exists() and meta_path.exists() and not refresh:
        return data_path, json.loads(meta_path.read_text())

    records, info = ADAPTERS[a["type"]](s, bbox, start, end, where, max_rows)
    folder.mkdir(parents=True, exist_ok=True)
    areal = s["outcome"]["kind"] == "areal_measure"
    body = records if areal else {"type": "FeatureCollection", "features": records}
    data_path.write_text(json.dumps(body))
    meta = {
        "request": request,
        "source_name": s["name"],
        "outcome": s["outcome"],
        "format": "areal_json" if areal else "geojson",
        "records": len(records),
        "downloaded": dt.datetime.now().isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        **info,
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    return data_path, meta


def main(argv: list[str]) -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Find and download public truth records.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("find")
    f.add_argument("--bbox", type=float, nargs=4)
    f.add_argument("--topic", default="")
    f.add_argument("--text", default="")
    g = sub.add_parser("get")
    g.add_argument("source")
    g.add_argument("--bbox", type=float, nargs=4)
    g.add_argument("--start")
    g.add_argument("--end")
    g.add_argument("--where")
    g.add_argument("--max-rows", type=int, default=500000)
    ns = ap.parse_args(argv)
    if ns.cmd == "find":
        for s in find(ns.bbox, ns.topic, ns.text):
            print(f"{s['id']:32} {s['outcome']['kind']:14} {s['name']}  [{s.get('status')}]")
    else:
        path, meta = get(ns.source, ns.bbox, ns.start, ns.end, ns.where, ns.max_rows)
        print(json.dumps({k: meta[k] for k in ("source_name", "records", "rows", "truncated", "dropped")}, indent=2))
        print(path)


if __name__ == "__main__":
    main(sys.argv[1:])
