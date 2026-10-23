"""Build ProveIt_Planning.aprx: the ProveIt maps plus PlanArena's forecast scored against new starts.

Reads ProveIt.aprx (left untouched, it may be open in Pro) and saves a copy with a fourth map,
then records all maps as open tabs. Run twice: once to build, once with --views (separate process).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import WORK, log  # noqa: E402
import make_project as mp  # noqa: E402

import arcpy  # noqa: E402

SRC = mp.DEST_DIR / "ProveIt.aprx"
OUT = mp.DEST_DIR / "ProveIt_Planning.aprx"
GDB = mp.GDB


def main() -> None:
    arcpy.env.overwriteOutput = True
    arcpy.mp.ArcGISProject(str(SRC)).saveACopy(str(OUT))
    aprx = arcpy.mp.ArcGISProject(str(OUT))
    mp._APRX = aprx
    starts = arcpy.management.CopyFeatures(str(WORK / "score_planarena_started_planarena_model.gdb" / "truth"),
                                           str(GDB / "nb_starts_2021_2025"))[0]
    lots = str(GDB / "planarena_forecast_scored")
    m = mp.new_map(aprx, "4 PlanArena forecast (2020) vs new building starts (2021-25)")
    mp.graduated(m.addDataFromPath(lots), "p_redev_5yr", classes=7)
    m.addDataFromPath(str(starts))
    mp.zoom_to(m, lots)
    aprx.save()
    uris = sorted(x.getDefinition("V3").uRI for x in aprx.listMaps())
    (mp.DEST_DIR / "views_planning.json").write_text(json.dumps(uris))
    log(f"saved {OUT} with {len(uris)} maps")


if __name__ == "__main__":
    if "--views" in sys.argv:
        mp.open_views(OUT, json.loads((mp.DEST_DIR / "views_planning.json").read_text()))
        log("map views recorded")
    else:
        main()
