"""Known-answer check for pro/network.py: a 4-edge toy network with a one-way street.

A-B (1 min, two-way), B-C (1 min, one-way B->C), A-C detour (5 min, two-way).
Expected: A->C = 2 min (via the one-way), C->A = 5 min (one-way blocks the shortcut).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS, log, work_gdb, write_json  # noqa: E402
from network import build_network  # noqa: E402

import arcpy  # noqa: E402

arcpy.env.overwriteOutput = True
sr = arcpy.SpatialReference(2263)
gdb = work_gdb("check_network", fresh=True)
fd = arcpy.management.CreateFeatureDataset(gdb, "net", sr)[0]
fc = arcpy.management.CreateFeatureclass(fd, "streets", "POLYLINE", spatial_reference=sr)[0]
for f in ("FT_Min", "TF_Min"):
    arcpy.management.AddField(fc, f, "DOUBLE")
edges = [((0, 0), (1000, 0), 1, 1), ((1000, 0), (2000, 0), 1, -1), ((0, 0), (0, 500), 2.5, 2.5), ((0, 500), (2000, 0), 2.5, 2.5)]
with arcpy.da.InsertCursor(fc, ["SHAPE@", "FT_Min", "TF_Min"]) as cur:
    for a, b, ft, tf in edges:
        cur.insertRow([arcpy.Polyline(arcpy.Array([arcpy.Point(*a), arcpy.Point(*b)]), sr), ft, tf])
nd = build_network(fd, "streets", "streets_nd", "FT_Min", "TF_Min", Path(arcpy.env.scratchFolder))

pts = arcpy.management.CreateFeatureclass("memory", "pts", "POINT", spatial_reference=sr)[0]
arcpy.management.AddField(pts, "Name", "TEXT")
with arcpy.da.InsertCursor(pts, ["SHAPE@XY", "Name"]) as cur:
    cur.insertRow([(0, 0), "A"])
    cur.insertRow([(2000, 0), "C"])
od = arcpy.nax.OriginDestinationCostMatrix(nd)
od.travelMode = arcpy.na.GetTravelModes(nd)["Drive"]
od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Origins, pts)
od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Destinations, pts)
res = od.solve()
got = {}
with res.searchCursor(arcpy.nax.OriginDestinationCostMatrixOutputDataType.Lines, ["OriginName", "DestinationName", "Total_Time"]) as cur:
    for o, d, t in cur:
        got[f"{o}->{d}"] = round(t, 3)
expected = {"A->C": 2.0, "C->A": 5.0}
ok = all(got.get(k) == v for k, v in expected.items())
write_json(OUTPUTS / "check_network.json", {"expected": expected, "got": got, "pass": ok})
log(f"{'PASS' if ok else 'FAIL'}: {got}")
sys.exit(0 if ok else 1)
