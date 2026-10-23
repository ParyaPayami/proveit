"""T12: fire coverage vs FDNY travel times for Brooklyn only.
Reuses cached citywide network/firehouses/street points from C:\\proveit_work\\fire_ems.gdb;
only the street points (where fires can happen) are restricted to Brooklyn.
Firehouses and network stay citywide so units from adjacent boroughs can respond."""
import csv, sys, statistics
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
import arcpy
import fire_ems as fe
from common import PROJECT, check_out, log, provenance, work_gdb, write_json, read_json

OUT = PROJECT / "outputs" / "agent_eval" / "T12"
SRC = r"C:\proveit_work\fire_ems.gdb"
check_out("Network")
arcpy.env.overwriteOutput = True
gdb = work_gdb("T12_fire", fresh=True)

# Brooklyn MODZCTAs: ZIP prefix 112 (all Brooklyn; check against zips list and firehouse borough field)
zips_all = [r[0] for r in arcpy.da.SearchCursor(SRC + r"\zips", ["modzcta"])]
bk = sorted(z for z in zips_all if z.startswith("112"))
log(f"Brooklyn MODZCTAs: {len(bk)}")
fh = read_json(fe.DATA / fe.CASE["sources"]["firehouses"]["file"])
fh_b = defaultdict(int)
for r in fh: fh_b[r.get("borough")] += 1
log(f"firehouses by borough: {dict(fh_b)}")

where = "modzcta IN (%s)" % ",".join(repr(z) for z in bk)
pts = arcpy.management.MakeFeatureLayer(SRC + r"\mids", "bk_pts", where)[0]
bkpts = arcpy.management.CopyFeatures(pts, gdb + r"\mids_bk")[0]
n_pts = int(arcpy.management.GetCount(bkpts)[0])
log(f"Brooklyn street points: {n_pts}")

nd = SRC + r"\net\streets_nd"
minutes, loaded = fe.nearest_drive_minutes(nd, SRC + r"\firehouses", bkpts)

per_area = defaultdict(list); unreached = defaultdict(int)
with arcpy.da.SearchCursor(bkpts, ["OID@", "modzcta"]) as cur:
    for oid, z in cur:
        (per_area[z].append(minutes[oid]) if oid in minutes else unreached.__setitem__(z, unreached[z] + 1))

# sensitivity: only Brooklyn firehouses
bk_names = {r["facilityname"] for r in fh if r.get("borough") == "Brooklyn"}
fhl = arcpy.management.MakeFeatureLayer(SRC + r"\firehouses", "bkfh", "Name IN (%s)" % ",".join("'" + n.replace("'", "''") + "'" for n in bk_names))[0]
fhb = arcpy.management.CopyFeatures(fhl, gdb + r"\firehouses_bk")[0]
log(f"Brooklyn firehouses matched by name: {arcpy.management.GetCount(fhb)[0]}")
m2, _ = fe.nearest_drive_minutes(nd, fhb, bkpts)
per2 = defaultdict(list)
with arcpy.da.SearchCursor(bkpts, ["OID@", "modzcta"]) as cur:
    for oid, z in cur:
        if oid in m2: per2[z].append(m2[oid])

zips, member = fe.load_zips(gdb)
observed, unmatched = fe.observed_by_area(member)
obs_bk = {z: v for z, v in observed.items() if z in bk}
unm_bk = [u for u in unmatched if (u["zipcode"] or "").startswith("112")]
rows = []
for z in bk:
    m, o = per_area.get(z, []), obs_bk.get(z)
    rows.append({"modzcta": z, "street_points": len(m), "unreached_points": unreached.get(z, 0),
                 "model_median_min": round(statistics.median(m), 3) if m else "",
                 "obs_incidents": o["incidents"] if o else 0,
                 "obs_travel_min": round(o["obs_travel_min"], 3) if o else "",
                 "obs_response_min": round(o["obs_response_min"], 3) if o else "",
                 "model_median_min_bk_houses_only": round(statistics.median(per2[z]), 3) if per2.get(z) else ""})
with open(OUT / "results_by_zip.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
summary = {
    "observed_field_used": fe.CASE["answer_key"]["observed_field"],
    "soql_where": fe.CASE["sources"]["observed"]["soql"]["$where"],
    "min_incidents_applied": fe.CASE["answer_key"]["min_incidents"],
    "unmatched_zips_reported": True,
    "unmatched_zips_brooklyn_prefix": unm_bk,
    "unmatched_zips_citywide": unmatched,
    "scope": "Brooklyn MODZCTAs (prefix 112); network and firehouses citywide",
    "brooklyn_modzctas": bk,
    "firehouses_by_borough": dict(fh_b),
    "counts": {"street_points_loaded": loaded, "street_points_reached": len(minutes), "areas_with_model": len(per_area),
               "areas_with_observed": len(obs_bk)},
    "assumptions": fe.CASE["assumptions"], "cutoff_minutes": fe.CUTOFF_MIN,
    "work_gdb": gdb, "network_reused": nd,
    "provenance": provenance("fire_ems_brooklyn_T12", [fe.DATA / s["file"] for s in fe.CASE["sources"].values()],
                             {"scope": "Brooklyn", "cutoff_min": fe.CUTOFF_MIN}, __file__),
}
write_json(OUT / "run_summary.json", summary)
log("done")
