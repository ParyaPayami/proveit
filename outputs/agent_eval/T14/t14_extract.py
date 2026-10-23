"""T14: sink depth (Fill - DEM) at USGS Ida high-water marks and control points. Runs in Pro."""
import csv, math, random, re, shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
sys.path.insert(0, str(PROJECT / "pro"))
from common import WORK, check_out, log, provenance, read_json, write_json  # noqa
import arcpy, numpy as np  # noqa

DATA = PROJECT / "data" / "raw" / "flood_ida"
FT = 0.3048
R = 6378137.0
STRICT = re.compile(r"basement|cellar|inside|interior|living room|bedroom|kitchen|indoor|hallway|inside of", re.I)
LOOSE = re.compile(r"basement|cellar|inside|interior|garage|apartment|living room|bedroom|kitchen|indoor", re.I)
RADII = [0, 5, 10, 20]  # m

def merc(lon, lat):
    return math.radians(lon) * R, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R

def main():
    check_out("Spatial"); arcpy.env.overwriteOutput = True
    lines = (DATA / "FilteredHWMs_NewYork.csv").read_text(encoding="utf-8-sig").splitlines()
    rows = list(csv.DictReader(lines[1:]))
    marks = []
    for r in rows:
        t = f"{r['hwm_locationdescription']} {r['hwm_notes']} {r['siteDescription']}"
        h = r["height_above_gnd"].strip()
        x, y = merc(float(r["longitude_dd"]), float(r["latitude_dd"]))
        marks.append(dict(id=r["hwm_id"], x=x, y=y, lat=float(r["latitude_dd"]), h_ft=float(h) if h else None,
                          elev_ft=float(r["elev_ft"]) if r["elev_ft"].strip() else None,
                          type=r["hwmTypeName"], quality=r["hwmQualityName"], stillwater=r["stillwater"],
                          loose=bool(LOOSE.search(t)), strict=bool(STRICT.search(t)), county=r["countyName"], desc=t[:90]))
    work = WORK / "T14"; work.mkdir(parents=True, exist_ok=True)
    tiles = []
    for tif in sorted((DATA / "elevation").glob("*.tif")):
        loc = work / tif.name; shutil.copyfile(tif, loc)
        dem = arcpy.Raster(str(loc)); d = arcpy.Describe(dem)
        nod = dem.noDataValue
        z = arcpy.RasterToNumPyArray(dem, nodata_to_value=np.nan).astype("float64")
        if nod is not None: z[z == nod] = np.nan
        f = arcpy.RasterToNumPyArray(arcpy.sa.Fill(dem), nodata_to_value=np.nan).astype("float64")
        e = d.extent
        tiles.append(dict(name=tif.stem, z=z, s=f - z, x0=e.XMin, y1=e.YMax, x1=e.XMax, y0=e.YMin, cw=d.meanCellWidth, ch=d.meanCellHeight))
    log(f"{len(tiles)} tiles")
    def pick(x, y):
        best = None
        for t in tiles:
            if t["x0"] <= x <= t["x1"] and t["y0"] <= y <= t["y1"]:
                edge = min(x - t["x0"], t["x1"] - x, y - t["y0"], t["y1"] - y)
                if best is None or edge > best[1]: best = (t, edge)
        return best
    def sample(t, x, y, k):
        c = int((x - t["x0"]) / t["cw"]); r = int((t["y1"] - y) / t["ch"])
        out = {}
        for rad in RADII:
            n = int(round(rad / (t["cw"] * k)))
            r0, r1, c0, c1 = max(r - n, 0), min(r + n + 1, t["z"].shape[0]), max(c - n, 0), min(c + n + 1, t["z"].shape[1])
            blk = t["s"][r0:r1, c0:c1]
            out[rad] = np.nanmax(blk) if np.isfinite(blk).any() else np.nan
        return t["z"][r, c], out
    rng = random.Random(42)
    out = []
    for m in marks:
        p = pick(m["x"], m["y"])
        if not p: continue
        t, edge = p; k = math.cos(math.radians(m["lat"]))
        z, s = sample(t, m["x"], m["y"], k)
        out.append(dict(kind="mark", id=m["id"], tile=t["name"], edge_m=round(edge * k, 1), dem_m=z, sink0=s[0], sink5=s[5], sink10=s[10], sink20=s[20],
                        h_ft=m["h_ft"], elev_ft=m["elev_ft"], type=m["type"], quality=m["quality"], stillwater=m["stillwater"],
                        loose=m["loose"], strict=m["strict"], county=m["county"], desc=m["desc"]))
        made = tries = 0
        while made < 20 and tries < 500:
            tries += 1
            rr = 500 * math.sqrt(rng.random()) / k; a = rng.random() * 2 * math.pi
            cx, cy = m["x"] + rr * math.cos(a), m["y"] + rr * math.sin(a)
            q = pick(cx, cy)
            if not q: continue
            cz, cs = sample(q[0], cx, cy, k)
            if math.isnan(cz) or cz < 0.5: continue
            out.append(dict(kind="control", id=f"{m['id']}_c{made}", tile=q[0]["name"], edge_m=round(q[1] * k, 1), dem_m=cz, sink0=cs[0], sink5=cs[5], sink10=cs[10], sink20=cs[20]))
            made += 1
    fn = ["kind","id","tile","edge_m","dem_m","sink0","sink5","sink10","sink20","h_ft","elev_ft","type","quality","stillwater","loose","strict","county","desc"]
    with open(HERE / "points.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fn); w.writeheader()
        for r in out: w.writerow({k: ("" if (v is None or (isinstance(v, float) and math.isnan(v))) else v) for k, v in r.items() if k in fn} | {k: "" for k in fn if k not in r})
    write_json(HERE / "run_summary.json", {"case": "flood_ida", "task": "T14", "marks_read": len(marks), "rows": len(out),
        "header_line_used": 1, "units": "obs ft; DEM m; sink m", "provenance": provenance("flood_ida", [DATA / "FilteredHWMs_NewYork.csv"], {"seed": 42, "radii_m": RADII}, __file__)})
    log("done")
main()
