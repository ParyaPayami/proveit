"""T15: sink depth and TPI (3 window sizes) at Ida marks and random controls. Reuses read_marks/Tile from pro/flood_ida.py (import only)."""
import sys, math, random, csv, shutil
from pathlib import Path
PROJECT = Path(r"\\Mac\Home\Desktop\Esri\proveit")
sys.path.insert(0, str(PROJECT / "pro"))
import flood_ida as F
import arcpy, numpy as np
from pathlib import Path
F.WORK = Path(r"C:\proveit_work\T15")   # keep tile copies inside the T15 scratch folder
F.check_out("Spatial")
arcpy.env.overwriteOutput = True
try:
    from scipy.ndimage import uniform_filter
except Exception:
    uniform_filter = None
OUT = PROJECT / "outputs" / "agent_eval" / "T15"
WINS = [25, 51, 101]

def tpi_nan(z, w):
    ok = np.isfinite(z)
    s = uniform_filter(np.where(ok, z, 0.0), size=w, mode="constant")
    c = uniform_filter(ok.astype("float64"), size=w, mode="constant")
    with np.errstate(invalid="ignore", divide="ignore"):
        return z - s / c

key = F.CASE["answer_key"]
rng = random.Random(42)
marks = F.read_marks()
tiles = []
for p in sorted((F.DATA / "elevation").glob("*.tif")):
    t = F.Tile(p)
    t.extra = {w: tpi_nan(t.z, w) for w in WINS if uniform_filter}
    tiles.append(t)
print(len(marks), "marks", len(tiles), "tiles", "scipy" if uniform_filter else "no scipy", flush=True)

def vals(t, x, y):
    col, row = int((x - t.x0) / t.cw), int((t.y1 - y) / t.ch)
    if not (0 <= row < t.z.shape[0] and 0 <= col < t.z.shape[1]):
        return None
    d = {"dem_m": t.z[row, col], "sink_depth_m": t.sink[row, col], "tpi51_arcpy": t.tpi[row, col]}
    for w, a in t.extra.items():
        d[f"tpi{w}"] = a[row, col]
    ex = t.extent
    d["edge_m"] = min(x - ex.XMin, ex.XMax - x, y - ex.YMin, ex.YMax - y) * t.k
    return d

rows = []
for m in marks:
    x, y = F.merc(m["lon"], m["lat"])
    inside = [t for t in tiles if t.contains(x, y)]
    if not inside:
        continue
    t = min(inside, key=lambda t: t.center_dist(x, y))
    v = vals(t, x, y)
    if v is None:
        continue
    rows.append(dict(kind="mark", id=m["id"], site=m["site"], tile=t.name, interior=m["interior"], obs_depth_m=m["obs_depth_m"], **v))
    made = tries = 0
    while made < key["control_points_per_mark"] and tries < 500:
        tries += 1
        r = key["control_radius_m"] * math.sqrt(rng.random()) / t.k
        a = rng.random() * 2 * math.pi
        cv = vals(t, x + r * math.cos(a), y + r * math.sin(a))
        if cv is None or not np.isfinite(cv["dem_m"]) or cv["dem_m"] < 0.5:
            continue
        rows.append(dict(kind="control", id=f"{m['id']}_c{made}", site=m["site"], tile=t.name, interior="", obs_depth_m="", **cv))
        made += 1
OUT.mkdir(parents=True, exist_ok=True)
with open(OUT / "points.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    for r in rows:
        w.writerow({k: (round(float(v), 4) if isinstance(v, (float, np.floating)) and np.isfinite(v) else ("" if isinstance(v, (float, np.floating)) else v)) for k, v in r.items()})
print("wrote", len(rows), "rows; marks", sum(r["kind"] == "mark" for r in rows))
