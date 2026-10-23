import sys, csv, json, statistics
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
from common import work_gdb, check_out, log, write_json, read_json, PROJECT
import fire_ems as F
import arcpy
OUT = Path(r"\\Mac\Home\Desktop\Esri\proveit\outputs\agent_eval\T09")
arcpy.env.overwriteOutput = True
check_out("Network")
src = r"C:\proveit_work\fire_ems.gdb"
gdb = work_gdb("T09_work", fresh=True)
arcpy.management.Copy(src + r"\net", gdb + r"\net")
for fc in ["firehouses", "zips", "mids"]:
    arcpy.management.CopyFeatures(f"{src}\\{fc}", f"{gdb}\\{fc}")
nd = gdb + r"\net\streets_nd"
log("copied; solving")
minutes, loaded = F.nearest_drive_minutes(nd, gdb + r"\firehouses", gdb + r"\mids")
zips_fc, member = F.load_zips(gdb)
per_area = defaultdict(list); unreached = defaultdict(int)
with arcpy.da.SearchCursor(gdb + r"\mids", ["OID@", "modzcta"]) as cur:
    for oid, m in cur:
        if oid in minutes: per_area[m].append(minutes[oid])
        else: unreached[m] += 1
observed, unmatched = F.observed_by_area(member)
rows = []
for m in sorted(set(per_area) | set(observed) | set(unreached)):
    mm, o = per_area.get(m, []), observed.get(m)
    rows.append({"modzcta": m, "street_points": len(mm), "unreached_points": unreached.get(m, 0),
        "model_median_min": round(statistics.median(mm), 3) if mm else "",
        "model_mean_min": round(statistics.fmean(mm), 3) if mm else "",
        "obs_incidents": o["incidents"] if o else 0, "postal_zips": o["postal_zips"] if o else 0,
        "obs_travel_min": round(o["obs_travel_min"], 3) if o else "",
        "obs_response_min": round(o["obs_response_min"], 3) if o else ""})
with open(OUT / "results_by_zip.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
write_json(OUT / "run_summary.json", {"observed_field_used": "med_travel_s",
    "soql_where": F.CASE["sources"]["observed"]["soql"]["$where"], "min_incidents_applied": 20,
    "unmatched_zips_reported": True, "unmatched_zips": unmatched, "points_loaded": loaded,
    "points_reached": len(minutes), "work_gdb": gdb})
log(f"done {len(rows)} rows; unmatched {unmatched}")
