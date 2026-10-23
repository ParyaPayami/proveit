"""T04: DEM ground elevation (3DEP, m NAVD88) vs surveyed ground = (elev_ft - height_above_gnd) ft -> m."""
import sys, math, json, shutil
from pathlib import Path
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
import numpy as np
import arcpy
from flood_ida import read_marks, merc, DATA, WORK   # importing only; main() not run

OUT = Path(__file__).resolve().parent
marks = read_marks()
tiles = []
for p in sorted((DATA / "elevation").glob("*.tif")):
    local = WORK / "flood_ida" / p.name
    local.parent.mkdir(parents=True, exist_ok=True)
    if not local.exists():
        shutil.copyfile(p, local)
    r = arcpy.Raster(str(local)); d = arcpy.Describe(r)
    z = arcpy.RasterToNumPyArray(r, nodata_to_value=np.nan).astype("float64")
    nod = r.noDataValue
    if nod is not None: z[z == nod] = np.nan
    e = d.extent
    tiles.append(dict(name=p.stem, x0=e.XMin, y1=e.YMax, x1=e.XMax, y0=e.YMin, cw=d.meanCellWidth, ch=d.meanCellHeight, z=z,
                      sr=d.spatialReference.factoryCode))
print("tiles", len(tiles), "sr", {t["sr"] for t in tiles}, "cell", tiles[0]["cw"], flush=True)

rows = []
for m in marks:
    x, y = merc(m["lon"], m["lat"])
    best = None
    for t in tiles:
        # require 3x3 window inside tile; prefer most-central
        mx, my = 3 * t["cw"], 3 * t["ch"]
        if t["x0"] + mx <= x <= t["x1"] - mx and t["y0"] + my <= y <= t["y1"] - my:
            dd = math.hypot(x - (t["x0"] + t["x1"]) / 2, y - (t["y0"] + t["y1"]) / 2)
            if best is None or dd < best[0]: best = (dd, t)
    rec = dict(id=m["id"], lat=m["lat"], lon=m["lon"], interior=m["interior"], quality=m["quality"],
               obs_ground_m=m["obs_ground_m"], height_m=m["obs_depth_m"], dem_m=None, dem_min3=None, dem_max3=None, dem_mean3=None, tile=None)
    if best:
        t = best[1]
        c = int((x - t["x0"]) / t["cw"]); rr = int((t["y1"] - y) / t["ch"])
        w = t["z"][rr-1:rr+2, c-1:c+2]
        v = t["z"][rr, c]
        if not np.isnan(v):
            rec.update(dem_m=float(v), dem_min3=float(np.nanmin(w)), dem_max3=float(np.nanmax(w)), dem_mean3=float(np.nanmean(w)), tile=t["name"])
    rows.append(rec)
(OUT / "t04_rows.json").write_text(json.dumps(rows, indent=1))
print("done", len(rows), sum(r["dem_m"] is not None for r in rows))
