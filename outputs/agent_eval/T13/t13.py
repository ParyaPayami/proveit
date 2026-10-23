import sys, csv, math, random
from pathlib import Path
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
import flood_ida as F
F.WORK = Path(r"C:\proveit_work\T13")
import arcpy
F.check_out("Spatial")
arcpy.env.overwriteOutput = True
OUT = Path(__file__).resolve().parent
marks = F.read_marks()
tiles = [F.Tile(p) for p in sorted((F.DATA / "elevation").glob("*.tif"))]
rng = random.Random(7)
rows = []; nt = 0
for m in marks:
    x, y = F.merc(m["lon"], m["lat"])
    ins = [t for t in tiles if t.contains(x, y, 60)] or [t for t in tiles if t.contains(x, y)]
    if not ins: nt += 1; continue
    t = min(ins, key=lambda t: t.center_dist(x, y))
    z, s, p = t.values(x, y)
    rows.append(dict(kind="mark", id=m["id"], tile=t.name, dem_m=z, sink=s, tpi=p, depth_m=m["obs_depth_m"], interior=m["interior"], quality=m["quality"]))
    made = tries = 0
    while made < 20 and tries < 500:
        tries += 1
        r = 500 * math.sqrt(rng.random()) / t.k; a = rng.random() * 2 * math.pi
        cz, cs, cp = t.values(x + r * math.cos(a), y + r * math.sin(a))
        if math.isnan(cz) or cz < 0.5: continue
        rows.append(dict(kind="control", id=f"{m['id']}_c{made}", tile=t.name, dem_m=cz, sink=cs, tpi=cp, depth_m="", interior="", quality=""))
        made += 1
print("no tile", nt)
with open(OUT / "points.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
