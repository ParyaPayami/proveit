import sys, csv, json, statistics
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
from common import work_gdb, check_out, log, read_json, write_json, PROJECT
import arcpy
import fire_ems as fe   # import only; main() guarded
check_out("Network")
arcpy.env.overwriteOutput = True
SRC = r"C:\proveit_work\fire_ems.gdb"
gdb = work_gdb("T10_work", fresh=True)
arcpy.management.Copy(SRC + r"\net", gdb + r"\net")
for n in ["mids", "firehouses", "zips"]:
    arcpy.management.Copy(f"{SRC}\\{n}", f"{gdb}\\{n}")
nd = gdb + r"\net\streets_nd"
log("copied")
minutes, loaded = fe.nearest_drive_minutes(nd, gdb + r"\firehouses", gdb + r"\mids")
member = {}
with arcpy.da.SearchCursor(gdb + r"\zips", ["modzcta", "zcta"]) as cur:
    for modz, zcta in cur:
        for z in [modz] + [s.strip() for s in (zcta or "").split(",")]:
            if z: member.setdefault(z, modz)
observed, unmatched = fe.observed_by_area(member)
per = defaultdict(list); unreached = defaultdict(int); mph = defaultdict(list)
with arcpy.da.SearchCursor(gdb + r"\mids", ["OID@", "modzcta", "mph"]) as cur:
    for oid, z, s in cur:
        mph[z].append(s or 0)
        if oid in minutes: per[z].append(minutes[oid])
        else: unreached[z] += 1
# firehouses per area
fh = arcpy.analysis.SpatialJoin(gdb + r"\zips", gdb + r"\firehouses", gdb + r"\zips_fh", "JOIN_ONE_TO_ONE", "KEEP_ALL")[0]
info = {}
with arcpy.da.SearchCursor(fh, ["modzcta", "Join_Count", "SHAPE@AREA", "pop_est", "label"]) as cur:
    for z, jc, a, pop, lab in cur: info[z] = (jc, a / 27878400.0, pop, lab)
rows = []
for z in sorted(set(per) | set(observed)):
    m = per.get(z, []); o = observed.get(z)
    rows.append({"modzcta": z, "label": info.get(z, (0,0,0,""))[3], "firehouses_inside": info.get(z, (0,))[0],
        "area_sqmi": round(info.get(z,(0,0))[1], 2), "pop": info.get(z,(0,0,None))[2],
        "street_points": len(m), "unreached": unreached.get(z, 0),
        "model_median_min": round(statistics.median(m), 3) if m else "",
        "model_mean_min": round(statistics.mean(m), 3) if m else "",
        "model_p90_min": round(sorted(m)[int(.9*(len(m)-1))], 3) if m else "",
        "mean_mph": round(statistics.mean(mph[z]), 1) if mph.get(z) else "",
        "obs_incidents": o["incidents"] if o else 0,
        "obs_travel_min": round(o["obs_travel_min"], 3) if o else "",
        "postal_zips": o["postal_zips"] if o else 0})
out = PROJECT / "outputs" / "agent_eval" / "T10"
with open(out / "t10_by_zip.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
write_json(out / "t10_unmatched.json", {"unmatched": unmatched, "loaded": loaded, "reached": len(minutes)})
log("done")
