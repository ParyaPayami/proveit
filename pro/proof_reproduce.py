"""Proof: the general Score My Layer tool reproduces the purpose-built case results.

Wildfire: building footprints (polygons) scored against CAL FIRE inspections
(yes/no labels); the case script reported slope AUC 0.581 and open-land 0.379.
Flood: a terrain sink-depth raster scored against Ida high-water marks
(presence only, random controls), exercising the raster path.
"""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS, RAW, WORK, check_out, log, read_json, write_json  # noqa: E402
import score_layer  # noqa: E402

import arcpy  # noqa: E402

PROJECT_GDB = Path.home() / "Documents" / "ArcGIS" / "Projects" / "ProveIt" / "ProveIt.gdb"


def sink_mosaic() -> str:
    """Sink depth (filled minus original elevation) for every Ida elevation tile, mosaicked."""
    folder = WORK / "proof_sinks"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / "sink_depth_m.tif"
    if out.exists():
        return str(out)
    parts = []
    for tif in sorted((RAW / "flood_ida" / "elevation").glob("*.tif")):
        local = folder / tif.name
        shutil.copyfile(tif, local)
        dem = arcpy.Raster(str(local))
        sink = arcpy.sa.Fill(dem) - dem
        path = folder / f"sink_{tif.stem}.tif"
        sink.save(str(path))
        parts.append(str(path))
    arcpy.management.MosaicToNewRaster(parts, str(folder), out.name, None, "32_BIT_FLOAT", None, 1, "MAXIMUM")
    return str(out)


def main() -> None:
    check_out("Spatial")
    arcpy.env.overwriteOutput = True
    bld = str(PROJECT_GDB / "wildfire_buildings")
    case = read_json(OUTPUTS / "wildfire_la" / "score.json")["all_fires"]
    res = {}
    for field, direction, key in (("slope_deg", "more", "slope_deg"), ("open_land_distance_m", "less", "open_land_distance_m")):
        r = score_layer.run({"prediction": bld, "field": field, "source": "calfire_dins_la_2025", "higher_means": direction,
                             "prediction_date": "2025-01-07", "start": "2025-01-07", "name": f"repro_wildfire_{field}"})
        res[f"wildfire_{field}"] = {"general_tool_auc": r["scorecard"]["metrics"]["auc"], "case_script_auc": case[key],
                                    "scored": r["scorecard"]["scored"]}
        log(f"{field}: general tool AUC {res[f'wildfire_{field}']['general_tool_auc']} vs case script {case[key]}")

    flood = score_layer.run({"prediction": sink_mosaic(), "source": "usgs_hwm_ida_nyc", "higher_means": "more",
                             "prediction_date": "2021-09-01", "start": "2021-09-01", "name": "repro_flood_sinks"})
    case_flood = read_json(OUTPUTS / "flood_ida" / "score.json")["sink_depth"]
    res["flood_sink_depth"] = {"general_tool_auc": flood["scorecard"]["metrics"]["auc"],
                               "case_script_auc_points": case_flood["auc_points"],
                               "note": "the case script draws controls within 500 m of each mark; the general tool draws them across the whole raster"}
    log(f"flood: general tool AUC {res['flood_sink_depth']['general_tool_auc']} (controls anywhere) vs case {case_flood['auc_points']} (controls near marks)")
    write_json(OUTPUTS / "proof_reproduce.json", res)


if __name__ == "__main__":
    main()
