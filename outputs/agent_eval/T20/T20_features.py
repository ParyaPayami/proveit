"""Case 3: pre-fire structure features vs CAL FIRE damage (Eaton and Palisades, 2025).

Runs inside ArcGIS Pro (Spatial Analyst). Features use only pre-fire data:
footprint spacing and density, slope, and distance to open land. The fire
perimeter is never used (it is the outcome). Writes
outputs/wildfire_la/buildings.csv and run_summary.json; scoring is separate.
"""

from __future__ import annotations

import csv
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "pro"))
from common import OUTPUTS, PROJECT, RAW, WORK, check_out, log, provenance, read_json, work_gdb, write_json  # noqa: E402

import arcpy  # noqa: E402

CASE = read_json(PROJECT / "cases" / "wildfire_la.json")
DATA = RAW / "wildfire_la"
OUT = OUTPUTS / "agent_eval" / "T20"
T = WORK / "T20"
T.mkdir(parents=True, exist_ok=True)
UTM = arcpy.SpatialReference(26911)  # NAD83 / UTM 11N, meters
OPEN_LAND_M = 100
EDGE_M = 400
FEATURES = ["nn_distance_m", "neighbors_50m", "slope_deg", "open_land_distance_m"]


def outcome(damage) -> str:
    key = CASE["answer_key"]
    if damage in key["destroyed_values"]:
        return "1"
    if damage in key["inspected_not_destroyed_values"]:
        return "0"
    return ""  # not inspected or inaccessible: excluded, not "no damage"


def main() -> None:
    check_out("Spatial")
    arcpy.env.overwriteOutput = True
    gdb = work_gdb("T20_feat", fresh=True)
    local = T / "buildings_dins.geojson"
    shutil.copyfile(DATA / CASE["sources"]["buildings"]["file"], local)
    raw = arcpy.conversion.JSONToFeatures(str(local), f"{gdb}\\bld_raw", "POLYGON")[0]
    bld = arcpy.management.Project(raw, f"{gdb}\\buildings", UTM)[0]
    arcpy.management.CalculateField(bld, "fire", "'palisades' if !SHAPE.centroid.X! < 380000 else 'eaton'", "PYTHON3",
                                    field_type="TEXT")
    log(f"buildings: {int(arcpy.management.GetCount(bld)[0]):,}")

    # Spacing: distance to the nearest other footprint (Near skips the feature itself).
    arcpy.analysis.Near(bld, bld, method="PLANAR")
    # Density: other footprints within 50 m, edge to edge.
    sj = arcpy.analysis.SpatialJoin(bld, bld, f"{gdb}\\bld_sj", "JOIN_ONE_TO_ONE", "KEEP_ALL",
                                    match_option="WITHIN_A_DISTANCE", search_radius="50 Meters")[0]
    neighbors = {oid: max(n - 1, 0) for oid, n in arcpy.da.SearchCursor(sj, ["TARGET_FID", "Join_Count"])}

    pts = arcpy.management.FeatureToPoint(bld, f"{gdb}\\bld_pts", "INSIDE")[0]
    arcpy.env.cellSize = 5
    values: dict[int, dict] = {}
    for fire in ("eaton", "palisades"):
        tifs = [str(p) for p in sorted((DATA / "elevation").glob(f"{fire}_*.tif"))]
        mosaic = arcpy.management.MosaicToNewRaster(tifs, str(T), f"dem_{fire}.tif", None, "32_BIT_FLOAT",
                                                    None, 1, "MEAN")[0]
        dem = arcpy.management.ProjectRaster(mosaic, str(T / f"dem_{fire}_utm.tif"), UTM, "BILINEAR", 5)[0]
        slope = arcpy.sa.Slope(dem, "DEGREE")

        lyr = arcpy.management.MakeFeatureLayer(bld, f"b_{fire}", f"fire = '{fire}'")[0]
        arcpy.env.extent = arcpy.Describe(dem).extent
        # Open land: ground more than 100 m from any footprint, kept only well inside
        # the layer's coverage (outside it, buildings are simply unknown).
        hull = arcpy.management.MinimumBoundingGeometry(lyr, f"{gdb}\\hull_{fire}", "CONVEX_HULL", "ALL")[0]
        core = arcpy.analysis.Buffer(hull, f"{gdb}\\core_{fire}", f"-{EDGE_M} Meters")[0]
        dist = arcpy.sa.EucDistance(lyr, cell_size=5)
        open_land = arcpy.sa.ExtractByMask(arcpy.sa.SetNull(dist <= OPEN_LAND_M, 1), core)
        to_open = arcpy.sa.EucDistance(open_land, cell_size=5)

        plyr = arcpy.management.MakeFeatureLayer(pts, f"p_{fire}", f"fire = '{fire}'")[0]
        arcpy.sa.ExtractMultiValuesToPoints(plyr, [[slope, f"slope_{fire}"], [to_open, f"open_{fire}"]], "NONE")
        # Read the feature class, not the layer: the layer's field list is cached.
        with arcpy.da.SearchCursor(pts, ["ORIG_FID", f"slope_{fire}", f"open_{fire}"], f"fire = '{fire}'") as cur:
            for oid, s, o in cur:
                values[oid] = {"slope_deg": s, "open_land_distance_m": o}
        arcpy.ClearEnvironment("extent")
        log(f"{fire}: slope and open-land distance sampled")

    OUT.mkdir(parents=True, exist_ok=True)
    counts = {"destroyed": 0, "not_destroyed": 0, "excluded_no_record": 0, "excluded_inaccessible": 0}
    with open(OUT / "features.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["oid", "fire", "damage", "destroyed"] + FEATURES)
        with arcpy.da.SearchCursor(bld, ["OID@", "fire", "DAMAGE", "NEAR_DIST"]) as cur:
            for oid, fire, damage, near in cur:
                y = outcome(damage)
                if y == "1":
                    counts["destroyed"] += 1
                elif y == "0":
                    counts["not_destroyed"] += 1
                elif damage is None:
                    counts["excluded_no_record"] += 1
                else:
                    counts["excluded_inaccessible"] += 1
                v = values.get(oid, {})
                row = [near if near is not None and near >= 0 else "", neighbors.get(oid, ""),
                       v.get("slope_deg", ""), v.get("open_land_distance_m", "")]
                w.writerow([oid, fire, damage or "", y] + ["" if x is None else round(x, 2) for x in row])

    write_json(OUT / "run_summary.json", {
        "features_used": FEATURES,
        "null_damage_excluded": True,
        "counts": counts,
        "assumptions": CASE["assumptions"],
        "params": {"open_land_m": OPEN_LAND_M, "edge_m": EDGE_M, "cell_m": 5},
        "provenance": provenance("wildfire_la", [DATA / CASE["sources"]["buildings"]["file"]]
                                 + sorted((DATA / "elevation").glob("*.tif")),
                                 {"open_land_m": OPEN_LAND_M, "edge_m": EDGE_M}, __file__),
    })
    log(f"wrote features.csv: {counts}")


if __name__ == "__main__":
    main()
