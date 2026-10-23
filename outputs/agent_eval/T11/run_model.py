import csv, json, shutil, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
import arcpy
from common import check_out, log
import fire_ems as fe

OUT = Path(r"\\Mac\Home\Desktop\Esri\proveit\outputs\agent_eval\T11")
SRC = r"C:\proveit_work\fire_ems.gdb"
DST = r"C:\proveit_work\T11_work.gdb"
arcpy.env.overwriteOutput = True
check_out("Network")
if not arcpy.Exists(DST):
    shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns("*.lock"))
log("copied gdb")
nd = DST + r"\net\streets_nd"
firehouses = DST + r"\firehouses"
points = DST + r"\mids"
streets = DST + r"\net\streets"
log("counts firehouses %s points %s" % (arcpy.management.GetCount(firehouses)[0], arcpy.management.GetCount(points)[0]))
print([f.name for f in arcpy.ListFields(points)])
minutes, loaded = fe.nearest_drive_minutes(nd, firehouses, points)
rows = []
with arcpy.da.SearchCursor(points, ["OID@", "modzcta"]) as cur:
    for oid, m in cur:
        rows.append((oid, m, minutes.get(oid, "")))
with open(OUT / "point_minutes.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["oid", "modzcta", "minutes"]); w.writerows(rows)
# speed stats on ordinary streets
sp = defaultdict(float); n = defaultdict(int)
with arcpy.da.SearchCursor(streets, ["rw_type", "mph", "SHAPE@LENGTH", "posted_speed"]) as cur:
    for rw, mph, L, ps in cur:
        sp[(rw, mph)] += L / 5280; n[(rw, mph, ps in (None, ""))] += 1
json.dump({"miles_by_rw_mph": {f"{k[0]}|{k[1]}": v for k, v in sp.items()},
           "count_by_rw_mph_missing": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in n.items()},
           "loaded": loaded, "reached": len(minutes)}, open(OUT / "speed_stats.json", "w"), indent=1)
log("done")
