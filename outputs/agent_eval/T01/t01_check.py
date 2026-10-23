"""T01: toy one-way network drive times A->C and C->A, plus a check of the cached NYC network."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "pro"))
from common import log, work_gdb, write_json  # noqa: E402
from network import build_network  # noqa: E402

import arcpy  # noqa: E402

arcpy.env.overwriteOutput = True
sr = arcpy.SpatialReference(2263)
gdb = work_gdb("T01_toy", fresh=True)
fd = arcpy.management.CreateFeatureDataset(gdb, "net", sr)[0]
fc = arcpy.management.CreateFeatureclass(fd, "streets", "POLYLINE", spatial_reference=sr)[0]
for f in ("FT_Min", "TF_Min"):
    arcpy.management.AddField(fc, f, "DOUBLE")
edges = [((0, 0), (1000, 0), 1, 1), ((1000, 0), (2000, 0), 1, -1), ((0, 0), (0, 500), 2.5, 2.5), ((0, 500), (2000, 0), 2.5, 2.5)]
with arcpy.da.InsertCursor(fc, ["SHAPE@", "FT_Min", "TF_Min"]) as cur:
    for a, b, ft, tf in edges:
        cur.insertRow([arcpy.Polyline(arcpy.Array([arcpy.Point(*a), arcpy.Point(*b)]), sr), ft, tf])
nd = build_network(fd, "streets", "streets_nd", "FT_Min", "TF_Min", HERE / "tmpl")
pts = arcpy.management.CreateFeatureclass("memory", "pts", "POINT", spatial_reference=sr)[0]
arcpy.management.AddField(pts, "Name", "TEXT")
with arcpy.da.InsertCursor(pts, ["SHAPE@XY", "Name"]) as cur:
    cur.insertRow([(0, 0), "A"]); cur.insertRow([(2000, 0), "C"])
od = arcpy.nax.OriginDestinationCostMatrix(nd)
od.travelMode = arcpy.na.GetTravelModes(nd)["Drive"]
od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Origins, pts)
od.load(arcpy.nax.OriginDestinationCostMatrixInputDataType.Destinations, pts)
res = od.solve()
got = {}
with res.searchCursor(arcpy.nax.OriginDestinationCostMatrixOutputDataType.Lines, ["OriginName", "DestinationName", "Total_Time"]) as cur:
    for o, d, t in cur:
        got[f"{o}->{d}"] = round(t, 3)

nyc = {}
try:
    g = r"C:\proveit_work\fire_ems.gdb"
    nd2 = g + r"\net\streets_nd"
    nyc["exists"] = arcpy.Exists(nd2)
    if nyc["exists"]:
        nyc["streets"] = int(arcpy.management.GetCount(g + r"\net\streets")[0])
        d = arcpy.Describe(nd2)
        nyc["cost_attrs"] = [a.name for a in d.attributes]
except Exception as e:
    nyc["error"] = str(e)
expected = {"A->C": 2.0, "C->A": 5.0}
ok = all(got.get(k) == v for k, v in expected.items())
write_json(HERE / "result.json", {"expected": expected, "got": got, "pass": ok, "nyc_cached": nyc})
log(f"{'PASS' if ok else 'FAIL'}: {got} nyc={nyc}")
