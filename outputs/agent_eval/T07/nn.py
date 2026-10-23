import sys, json, shutil, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pro"))
from common import PROJECT, RAW, WORK, log, work_gdb, write_json
import arcpy
arcpy.env.overwriteOutput = True
OUT = PROJECT / "outputs" / "agent_eval" / "T07"
UTM = arcpy.SpatialReference(26911)
gdb = work_gdb("T07_nn", fresh=True)
local = WORK / "T07_buildings.geojson"
shutil.copyfile(RAW / "wildfire_la" / "buildings_2023_with_dins.geojson", local)
raw = arcpy.conversion.JSONToFeatures(str(local), f"{gdb}\\raw", "POLYGON")[0]
bld = arcpy.management.Project(raw, f"{gdb}\\bld", UTM)[0]
n = int(arcpy.management.GetCount(bld)[0]); log(f"n={n}")
# Near of a class to itself ignores the feature itself (matched by OID).
arcpy.analysis.Near(bld, bld, method="PLANAR")
rows = [r for r in arcpy.da.SearchCursor(bld, ["OID@", "BLD_ID", "CODE", "NEAR_FID", "NEAR_DIST", "DAMAGE", "AREA", "SHAPE@"])]
self_match = sum(1 for r in rows if r[0] == r[3])
nofound = sum(1 for r in rows if r[3] is None or r[3] < 0)
d = sorted(r[4] for r in rows if r[4] is not None and r[4] >= 0)
def q(p): return d[int(p * (len(d) - 1))]
zero = sum(1 for x in d if x == 0)
# is the nearest neighbor a duplicate geometry (same footprint repeated)?
byoid = {r[0]: r for r in rows}
dup_id = [k for k, v in collections.Counter(r[1] for r in rows).items() if v > 1 and k]
same_bldid_nn = sum(1 for r in rows if r[3] in byoid and r[1] and byoid[r[3]][1] == r[1])
dup_geom = 0
for r in rows:
    if r[4] == 0 and r[3] in byoid:
        a, b = r[7], byoid[r[3]][7]
        if a.equals(b): dup_geom += 1
codes = collections.Counter(r[2] for r in rows)
touch_ok = zero - dup_geom
stats = {"n": n, "valid_nn": len(d), "no_neighbor_found": nofound, "self_matches": self_match,
 "mean": sum(d)/len(d), "median": q(.5), "p05": q(.05), "p25": q(.25), "p75": q(.75), "p95": q(.95), "min": d[0], "max": d[-1],
 "zero_distance": zero, "zero_identical_geometry": dup_geom, "zero_touching_or_overlapping_not_identical": touch_ok,
 "duplicate_BLD_ID_values": len(dup_id), "nn_has_same_BLD_ID": same_bldid_nn, "codes": dict(codes),
 "gt_100m": sum(1 for x in d if x > 100), "gt_50m": sum(1 for x in d if x>50)}
write_json(OUT / "nn_stats.json", stats)
with open(OUT / "nn.csv", "w") as f:
    f.write("oid,bld_id,nn_oid,nn_dist_m,damage\n")
    for r in rows: f.write(f"{r[0]},{r[1] or ''},{r[3]},{'' if r[4] is None else round(r[4],3)},{r[5] or ''}\n")
log(json.dumps(stats))
