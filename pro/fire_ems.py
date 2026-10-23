"""Case 1: modeled fire-unit drive times vs observed FDNY travel times, by ZIP area.

Runs inside ArcGIS Pro (Network Analyst). Writes outputs/fire_ems/:
  results_by_zip.csv   modeled and observed minutes per MODZCTA area
  run_summary.json     counts, assumptions, trap evidence, provenance
The scoring is done separately (proveit/score.py) so the analysis does not
grade itself.
"""

from __future__ import annotations

import csv
import json
import shutil
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS, PROJECT, RAW, WORK, check_out, log, provenance, read_json, work_gdb, write_json  # noqa: E402
from network import build_network  # noqa: E402

import arcpy  # noqa: E402

CASE = read_json(PROJECT / "cases" / "fire_ems.json")
DATA = RAW / "fire_ems"
OUT = OUTPUTS / "fire_ems"
SR = arcpy.SpatialReference(2263)  # NY Long Island State Plane, feet

# CSCL roadway types a fire engine can drive on, and default speeds (mph)
# where posted_speed is missing.
DRIVABLE = {"1": 25, "2": 45, "3": 30, "4": 30, "9": 30, "10": 15, "13": 15}
CUTOFF_MIN = 15.0


def level(code) -> int:
    """CSCL level codes are digits or letters; any consistent integer works."""
    code = (code or "").strip()
    if code.isdigit():
        return int(code)
    return ord(code[0].upper()) - 64 if code else 0


def load_streets(gdb: str) -> str:
    local = WORK / "streets_cscl.geojson"
    shutil.copyfile(DATA / CASE["sources"]["streets"]["file"], local)  # GP tools are slow over the share
    raw = arcpy.conversion.JSONToFeatures(str(local), f"{gdb}\\streets_raw", "POLYLINE")[0]
    fd = arcpy.management.CreateFeatureDataset(gdb, "net", SR)[0]
    where = f"rw_type IN ({','.join(repr(k) for k in DRIVABLE)}) AND trafdir IN ('TW','FT','TF')"
    lyr = arcpy.management.MakeFeatureLayer(raw, "drivable", where)[0]
    streets = arcpy.management.Project(lyr, f"{fd}\\streets", SR)[0]
    for name, ftype in [("FT_Min", "DOUBLE"), ("TF_Min", "DOUBLE"), ("FromElev", "SHORT"), ("ToElev", "SHORT"), ("mph", "SHORT")]:
        arcpy.management.AddField(streets, name, ftype)
    fields = ["SHAPE@LENGTH", "rw_type", "trafdir", "posted_speed", "from_level_code", "to_level_code",
              "FT_Min", "TF_Min", "FromElev", "ToElev", "mph"]
    defaulted = 0
    with arcpy.da.UpdateCursor(streets, fields) as cur:
        for length_ft, rw, trafdir, speed, flev, tlev, *_ in cur:
            try:
                mph = int(float(speed))
            except (TypeError, ValueError):
                mph, defaulted = DRIVABLE[rw], defaulted + 1
            minutes = length_ft / (mph * 5280 / 60)
            ft = -1.0 if trafdir == "TF" else minutes  # negative cost = cannot travel this way
            tf = -1.0 if trafdir == "FT" else minutes
            cur.updateRow([length_ft, rw, trafdir, speed, flev, tlev, ft, tf, level(flev), level(tlev), mph])
    log(f"streets: {int(arcpy.management.GetCount(streets)[0]):,} drivable segments, {defaulted:,} with default speed")
    return fd, streets, defaulted


def load_firehouses(gdb: str) -> tuple[str, int]:
    rows = read_json(DATA / CASE["sources"]["firehouses"]["file"])
    fc = arcpy.management.CreateFeatureclass(gdb, "firehouses_wgs", "POINT", spatial_reference=4326)[0]
    arcpy.management.AddField(fc, "Name", "TEXT", field_length=120)
    skipped = 0
    with arcpy.da.InsertCursor(fc, ["SHAPE@XY", "Name"]) as cur:
        for r in rows:
            try:
                cur.insertRow([(float(r["longitude"]), float(r["latitude"])), r["facilityname"]])
            except (KeyError, ValueError, TypeError):
                skipped += 1
    out = arcpy.management.Project(fc, f"{gdb}\\firehouses", SR)[0]
    log(f"firehouses: {len(rows) - skipped} located, {skipped} without coordinates")
    return out, skipped


def load_zips(gdb: str) -> tuple[str, dict[str, str]]:
    raw = arcpy.conversion.JSONToFeatures(str(DATA / CASE["sources"]["zips"]["file"]), f"{gdb}\\zips_raw", "POLYGON")[0]
    zips = arcpy.management.Project(raw, f"{gdb}\\zips", SR)[0]
    member = {}  # postal ZIP -> MODZCTA
    # Member ZIPs are listed in both `zcta` and `label`; some (e.g. 11249 in 11211) appear only in `label`.
    with arcpy.da.SearchCursor(zips, ["modzcta", "zcta", "label"]) as cur:
        for modz, zcta, label in cur:
            for z in [modz] + [s.strip() for s in f"{zcta or ''},{label or ''}".split(",")]:
                if z:
                    member.setdefault(z, modz)
    return zips, member


def street_points(gdb: str, streets: str, zips: str) -> str:
    """One point per ordinary street segment (rw_type 1): where fires can happen."""
    lyr = arcpy.management.MakeFeatureLayer(streets, "ordinary", "rw_type = '1'")[0]
    mids = arcpy.management.FeatureVerticesToPoints(lyr, f"{gdb}\\mids_raw", "MID")[0]
    joined = arcpy.analysis.SpatialJoin(mids, zips, f"{gdb}\\mids", "JOIN_ONE_TO_ONE", "KEEP_COMMON",
                                        match_option="WITHIN")[0]
    log(f"street points: {int(arcpy.management.GetCount(joined)[0]):,} inside ZIP areas")
    return joined


def nearest_drive_minutes(nd: str, firehouses: str, points: str) -> tuple[dict[int, float], int]:
    """Drive minutes from the nearest firehouse to each street point (within the cutoff)."""
    arcpy.management.CalculateField(points, "pid", "!OBJECTID!", "PYTHON3", field_type="TEXT")
    od = arcpy.nax.OriginDestinationCostMatrix(nd)
    od.travelMode = arcpy.na.GetTravelModes(nd)["Drive"]
    od.defaultImpedanceCutoff = CUTOFF_MIN
    od.lineShapeType = arcpy.nax.LineShapeType.NoLine
    od.searchTolerance, od.searchToleranceUnits = 500, arcpy.nax.DistanceUnits.Feet
    dests = arcpy.nax.OriginDestinationCostMatrixInputDataType.Destinations
    mapping = od.fieldMappings(dests)
    mapping["Name"].mappedFieldName = "pid"
    od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Origins, firehouses)
    od.load(dests, points, mapping)
    res = od.solve()
    if not res.solveSucceeded:
        raise RuntimeError("OD solve failed: " + "; ".join(str(m) for m in res.solverMessages(arcpy.nax.MessageSeverity.All)))
    best: dict[int, float] = {}
    with res.searchCursor(arcpy.nax.OriginDestinationCostMatrixOutputDataType.Lines, ["DestinationName", "Total_Time"]) as cur:
        for name, minutes in cur:
            pid = int(name)
            if minutes < best.get(pid, 1e9):
                best[pid] = minutes
    loaded = res.count(dests)
    log(f"OD: {len(best):,} of {loaded:,} points reached within {CUTOFF_MIN:g} min")
    return best, loaded


def observed_by_area(member: dict[str, str]) -> tuple[dict[str, dict], list[dict]]:
    """Combine postal-ZIP medians into MODZCTA areas (incident-weighted)."""
    key = CASE["answer_key"]
    rows = read_json(DATA / CASE["sources"]["observed"]["file"])
    acc: dict[str, list] = defaultdict(list)
    unmatched = []
    for r in rows:
        z = (r.get("zipcode") or "").split(".")[0]
        if z not in member:
            unmatched.append({"zipcode": z or None, "incidents": int(r["n"])})
            continue
        acc[member[z]].append((int(r["n"]), float(r[key["observed_field"]]), float(r["med_response_s"])))
    areas = {}
    for modz, parts in acc.items():
        n = sum(p[0] for p in parts)
        areas[modz] = {
            "incidents": n,
            "obs_travel_min": sum(p[0] * p[1] for p in parts) / n / 60,
            "obs_response_min": sum(p[0] * p[2] for p in parts) / n / 60,
            "postal_zips": len(parts),
        }
    return areas, unmatched


def main(area_prefix: str | None = None) -> None:
    """area_prefix limits the scored areas (e.g. "112" for Brooklyn ZIP areas). The network and
    all firehouses stay citywide, so areas near a borough line are still served correctly."""
    global OUT
    check_out("Network")
    arcpy.env.overwriteOutput = True
    gdb = work_gdb("fire_ems" if not area_prefix else f"fire_ems_{area_prefix}", fresh=True)
    if area_prefix:
        OUT = OUTPUTS / f"fire_ems_{area_prefix}"

    fd, streets, defaulted = load_streets(gdb)
    nd = build_network(fd, "streets", "streets_nd", "FT_Min", "TF_Min", OUT, elevation_fields=("FromElev", "ToElev"))
    log("network built")
    firehouses, no_xy = load_firehouses(gdb)
    zips, member = load_zips(gdb)
    points = street_points(gdb, streets, zips)
    if area_prefix:
        lyr = arcpy.management.MakeFeatureLayer(points, "area_pts", f"modzcta LIKE '{area_prefix}%'")[0]
        points = arcpy.management.CopyFeatures(lyr, f"{gdb}\\mids_area")[0]
        log(f"study area {area_prefix}*: {int(arcpy.management.GetCount(points)[0]):,} street points")

    minutes, loaded = nearest_drive_minutes(nd, firehouses, points)
    per_area: dict[str, list[float]] = defaultdict(list)
    unreached: dict[str, int] = defaultdict(int)
    with arcpy.da.SearchCursor(points, ["OID@", "modzcta"]) as cur:
        for oid, modz in cur:
            if oid in minutes:
                per_area[modz].append(minutes[oid])
            else:
                unreached[modz] += 1

    observed, unmatched = observed_by_area(member)
    if area_prefix:
        observed = {k: v for k, v in observed.items() if k.startswith(area_prefix)}
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for modz in sorted(set(per_area) | set(observed)):
        m, o = per_area.get(modz, []), observed.get(modz)
        rows.append({
            "modzcta": modz,
            "street_points": len(m),
            "unreached_points": unreached.get(modz, 0),
            "model_median_min": round(statistics.median(m), 3) if m else "",
            "obs_incidents": o["incidents"] if o else 0,
            "obs_travel_min": round(o["obs_travel_min"], 3) if o else "",
            "obs_response_min": round(o["obs_response_min"], 3) if o else "",
        })
    with open(OUT / "results_by_zip.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # Keep a map-ready copy for the Pro project.
    arcpy.management.CopyFeatures(zips, f"{gdb}\\zip_results")
    summary = {
        "observed_field_used": CASE["answer_key"]["observed_field"],
        "soql_where": CASE["sources"]["observed"]["soql"]["$where"],
        "min_incidents_applied": CASE["answer_key"]["min_incidents"],
        "unmatched_zips_reported": True,
        "unmatched_zips": unmatched,
        "counts": {
            "street_segments_default_speed": defaulted,
            "firehouses_without_coordinates": no_xy,
            "street_points_loaded": loaded,
            "street_points_reached": len(minutes),
            "areas_with_model": len(per_area),
            "areas_with_observed": len(observed),
        },
        "assumptions": CASE["assumptions"],
        "cutoff_minutes": CUTOFF_MIN,
        "provenance": provenance(
            "fire_ems",
            [DATA / s["file"] for s in CASE["sources"].values()],
            {"drivable_rw_types": DRIVABLE, "cutoff_min": CUTOFF_MIN, "elevation_fields": True},
            __file__,
        ),
        "work_gdb": gdb,
        "study_area_prefix": area_prefix,
    }
    write_json(OUT / "run_summary.json", summary)
    log(f"wrote {OUT / 'results_by_zip.csv'} ({len(rows)} areas); {len(unmatched)} ZIPs unmatched")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
