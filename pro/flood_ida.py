"""Case 2: terrain low spots vs USGS high-water marks from Hurricane Ida (NYC, 2021).

Runs inside ArcGIS Pro (Spatial Analyst). For each elevation tile: fill sinks,
sink depth = filled - original, and local relative elevation (TPI). Values are
read at every mark and at random control points nearby. Writes
outputs/flood_ida/points.csv and run_summary.json; scoring is separate.
"""

from __future__ import annotations

import csv
import math
import random
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS, PROJECT, RAW, WORK, check_out, log, provenance, read_json, write_json  # noqa: E402

import arcpy  # noqa: E402
import numpy as np  # noqa: E402

CASE = read_json(PROJECT / "cases" / "flood_ida.json")
DATA = RAW / "flood_ida"
OUT = OUTPUTS / "flood_ida"
FT = 0.3048
REVIEWED_INTERIOR = set(CASE["interior_reviewed"]["hwm_ids"])
INTERIOR = re.compile(r"basement|cellar|inside|interior|garage|apartment|living room|bedroom|kitchen|indoor", re.I)
TPI_WINDOW = 51  # cells; 102 m at 2 m


def merc(lon: float, lat: float) -> tuple[float, float]:
    r = 6378137.0
    return math.radians(lon) * r, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r


def read_marks() -> list[dict]:
    src = CASE["sources"]["hwm"]
    lines = (DATA / src["file"]).read_text(encoding="utf-8-sig").splitlines()
    rows = list(csv.DictReader(lines[src["header_line"]:]))  # line 0 is a citation
    marks = []
    for r in rows:
        text = f"{r.get('hwm_locationdescription', '')} {r.get('hwm_notes', '')} {r.get('siteDescription', '')}"
        h = r.get("height_above_gnd", "").strip()
        marks.append({
            "id": r["hwm_id"],
            "lon": float(r["longitude_dd"]),
            "lat": float(r["latitude_dd"]),
            "obs_depth_m": float(h) * FT if h else None,
            "obs_ground_m": (float(r["elev_ft"]) - float(h)) * FT if h and r.get("elev_ft") else None,
            "interior": r["hwm_id"] in REVIEWED_INTERIOR,
            "keyword_interior": bool(INTERIOR.search(text)),  # old rule, kept for comparison
            "quality": r.get("hwmQualityName", ""),
            "site": r.get("site_no", ""),
        })
    return marks


class Tile:
    def __init__(self, tif: Path):
        local = WORK / "flood_ida" / tif.name
        local.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tif, local)
        dem = arcpy.Raster(str(local))
        d = arcpy.Describe(dem)
        self.name = tif.stem
        self.x0, self.y1 = d.extent.XMin, d.extent.YMax
        self.cw, self.ch = d.meanCellWidth, d.meanCellHeight
        self.extent = d.extent
        nod = dem.noDataValue
        z = arcpy.RasterToNumPyArray(dem, nodata_to_value=np.nan).astype("float64")
        if nod is not None:
            z[z == nod] = np.nan
        filled = arcpy.RasterToNumPyArray(arcpy.sa.Fill(dem), nodata_to_value=np.nan).astype("float64")
        mean = arcpy.RasterToNumPyArray(
            arcpy.sa.FocalStatistics(dem, arcpy.sa.NbrRectangle(TPI_WINDOW, TPI_WINDOW, "CELL"), "MEAN"),
            nodata_to_value=np.nan).astype("float64")
        self.z, self.sink, self.tpi = z, filled - z, z - mean
        # Web Mercator cells are smaller on the ground by cos(lat).
        self.k = math.cos(math.radians(math.degrees(2 * math.atan(math.exp(self.y1 / 6378137.0)) - math.pi / 2)))

    def contains(self, x: float, y: float, margin_m: float = 0) -> bool:
        m = margin_m / self.k
        return self.extent.XMin + m <= x <= self.extent.XMax - m and self.extent.YMin + m <= y <= self.extent.YMax - m

    def values(self, x: float, y: float) -> tuple[float, float, float]:
        col, row = int((x - self.x0) / self.cw), int((self.y1 - y) / self.ch)
        if not (0 <= row < self.z.shape[0] and 0 <= col < self.z.shape[1]):
            return (math.nan,) * 3
        return self.z[row, col], self.sink[row, col], self.tpi[row, col]

    def center_dist(self, x: float, y: float) -> float:
        return math.hypot(x - (self.extent.XMin + self.extent.XMax) / 2, y - (self.extent.YMin + self.extent.YMax) / 2)


def main() -> None:
    check_out("Spatial")
    arcpy.env.overwriteOutput = True
    key = CASE["answer_key"]
    rng = random.Random(42)

    marks = read_marks()
    tiles = [Tile(p) for p in sorted((DATA / "elevation").glob("*.tif"))]
    log(f"{len(marks)} marks, {len(tiles)} elevation tiles processed")

    rows, no_tile = [], 0
    for m in marks:
        x, y = merc(m["lon"], m["lat"])
        inside = [t for t in tiles if t.contains(x, y)]
        if not inside:
            no_tile += 1
            continue
        tile = min(inside, key=lambda t: t.center_dist(x, y))
        z, sink, tpi = tile.values(x, y)
        rows.append({"kind": "mark", "id": m["id"], "site": m["site"], "tile": tile.name, "x": x, "y": y, "dem_m": z,
                     "sink_depth_m": sink, "tpi_m": tpi, "obs_depth_m": m["obs_depth_m"],
                     "obs_ground_m": m["obs_ground_m"], "interior": m["interior"],
                     "keyword_interior": m["keyword_interior"], "quality": m["quality"]})
        made, tries = 0, 0
        while made < key["control_points_per_mark"] and tries < 500:
            tries += 1
            r = key["control_radius_m"] * math.sqrt(rng.random()) / tile.k
            a = rng.random() * 2 * math.pi
            cx, cy = x + r * math.cos(a), y + r * math.sin(a)
            cz, csink, ctpi = tile.values(cx, cy)
            if math.isnan(cz) or cz < 0.5:  # skip open water and missing elevation
                continue
            rows.append({"kind": "control", "id": f"{m['id']}_c{made}", "site": m["site"], "tile": tile.name, "x": cx, "y": cy,
                         "dem_m": cz, "sink_depth_m": csink, "tpi_m": ctpi, "obs_depth_m": None,
                         "obs_ground_m": None, "interior": None, "keyword_interior": None, "quality": None})
            made += 1

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "points.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None or (isinstance(v, float) and math.isnan(v)) else
                            round(v, 2 if k in ("x", "y") else 4) if isinstance(v, float) else v) for k, v in r.items()})

    n_marks = sum(r["kind"] == "mark" for r in rows)
    write_json(OUT / "run_summary.json", {
        "header_line_used": CASE["sources"]["hwm"]["header_line"],
        "units_converted": "ft_to_m",
        "control_points": sum(r["kind"] == "control" for r in rows),
        "interior_marks_flagged": True,
        "interior_marks": sum(1 for r in rows if r["kind"] == "mark" and r["interior"]),
        "interior_method": "reviewed list (cases/flood_ida.json interior_reviewed)",
        "keyword_interior_marks_old_rule": sum(1 for r in rows if r["kind"] == "mark" and r["keyword_interior"]),
        "marks_used": n_marks,
        "marks_without_tile": no_tile,
        "marks_without_depth": sum(1 for r in rows if r["kind"] == "mark" and r["obs_depth_m"] is None),
        "assumptions": CASE["assumptions"],
        "xy_wkid": 3857,
        "params": {"tpi_window_cells": TPI_WINDOW, "cell_m": CASE["elevation"]["cell_m"], "seed": 42},
        "provenance": provenance("flood_ida", [DATA / CASE["sources"]["hwm"]["file"]] + sorted((DATA / "elevation").glob("*.tif")),
                                 {"tpi_window_cells": TPI_WINDOW, "seed": 42}, __file__),
    })
    log(f"wrote {n_marks} marks and {len(rows) - n_marks} controls; {no_tile} marks had no tile")


if __name__ == "__main__":
    main()
