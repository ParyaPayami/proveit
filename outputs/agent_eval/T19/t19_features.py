"""T19: features per structure (same definitions as case wildfire_la), written to T19 folder only."""
import csv, os, shutil, sys
from pathlib import Path
PROJECT = Path(r"\\Mac\Home\Desktop\Esri\proveit")
sys.path.insert(0, str(PROJECT / "pro"))
from common import RAW, check_out, log, read_json
import arcpy

CASE = read_json(PROJECT / "cases" / "wildfire_la.json")
DATA = RAW / "wildfire_la"
OUT = PROJECT / "outputs" / "agent_eval" / "T19"
W = Path(r"C:\proveit_work\T19"); W.mkdir(parents=True, exist_ok=True)
G = Path(r"C:\proveit_work\T19_feat.gdb")
UTM = arcpy.SpatialReference(26911)
OPEN, EDGE = 100, 400
check_out("Spatial"); arcpy.env.overwriteOutput = True
if arcpy.Exists(str(G)): arcpy.management.Delete(str(G))
arcpy.management.CreateFileGDB(str(G.parent), G.name); gdb = str(G)
local = W / "b.geojson"; shutil.copyfile(DATA / CASE["sources"]["buildings"]["file"], local)
raw = arcpy.conversion.JSONToFeatures(str(local), f"{gdb}\\bld_raw", "POLYGON")[0]
bld = arcpy.management.Project(raw, f"{gdb}\\buildings", UTM)[0]
arcpy.management.CalculateField(bld, "fire", "'palisades' if !SHAPE.centroid.X! < 380000 else 'eaton'", "PYTHON3", field_type="TEXT")
log(f"n={arcpy.management.GetCount(bld)[0]}")
arcpy.analysis.Near(bld, bld, method="PLANAR")
sj = arcpy.analysis.SpatialJoin(bld, bld, f"{gdb}\\bld_sj", "JOIN_ONE_TO_ONE", "KEEP_ALL", match_option="WITHIN_A_DISTANCE", search_radius="50 Meters")[0]
neighbors = {o: max(n-1,0) for o,n in arcpy.da.SearchCursor(sj, ["TARGET_FID","Join_Count"])}
pts = arcpy.management.FeatureToPoint(bld, f"{gdb}\\bld_pts", "INSIDE")[0]
arcpy.env.cellSize = 5
values = {}
for fire in ("eaton","palisades"):
    tifs = [str(p) for p in sorted((DATA/"elevation").glob(f"{fire}_*.tif"))]
    mosaic = arcpy.management.MosaicToNewRaster(tifs, str(W), f"dem_{fire}.tif", None, "32_BIT_FLOAT", None, 1, "MEAN")[0]
    dem = arcpy.management.ProjectRaster(mosaic, str(W/f"dem_{fire}_utm.tif"), UTM, "BILINEAR", 5)[0]
    slope = arcpy.sa.Slope(dem, "DEGREE")
    lyr = arcpy.management.MakeFeatureLayer(bld, f"b_{fire}", f"fire = '{fire}'")[0]
    arcpy.env.extent = arcpy.Describe(dem).extent
    hull = arcpy.management.MinimumBoundingGeometry(lyr, f"{gdb}\\hull_{fire}", "CONVEX_HULL", "ALL")[0]
    core = arcpy.analysis.Buffer(hull, f"{gdb}\\core_{fire}", f"-{EDGE} Meters")[0]
    dist = arcpy.sa.EucDistance(lyr, cell_size=5)
    open_land = arcpy.sa.ExtractByMask(arcpy.sa.SetNull(dist <= OPEN, 1), core)
    to_open = arcpy.sa.EucDistance(open_land, cell_size=5)
    plyr = arcpy.management.MakeFeatureLayer(pts, f"p_{fire}", f"fire = '{fire}'")[0]
    arcpy.sa.ExtractMultiValuesToPoints(plyr, [[slope, f"slope_{fire}"], [to_open, f"open_{fire}"]], "NONE")
    with arcpy.da.SearchCursor(pts, ["ORIG_FID", f"slope_{fire}", f"open_{fire}", "SHAPE@XY"], f"fire = '{fire}'") as cur:
        for oid, s, o, xy in cur: values[oid] = (s, o, xy[0], xy[1])
    arcpy.ClearEnvironment("extent"); log(f"{fire} done")
with open(OUT/"features.csv","w",newline="",encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["oid","fire","damage","nn_distance_m","neighbors_50m","slope_deg","open_land_distance_m","x","y"])
    with arcpy.da.SearchCursor(bld, ["OID@","fire","DAMAGE","NEAR_DIST"]) as cur:
        for oid,fire,dmg,near in cur:
            v = values.get(oid,(None,None,None,None))
            w.writerow([oid,fire,dmg or "", "" if near is None or near<0 else round(near,2), neighbors.get(oid,""),
                        "" if v[0] is None else round(v[0],2), "" if v[1] is None else round(v[1],2),
                        "" if v[2] is None else round(v[2],1), "" if v[3] is None else round(v[3],1)])
log("written")
