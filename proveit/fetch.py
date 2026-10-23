"""Download a case's public data into data/raw/<case>/ with a provenance manifest.

Raw files are never edited after download (a hook enforces this for agents);
analysis copies them into a scratch geodatabase.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
CASES = PROJECT / "cases"
RAW = PROJECT / "data" / "raw"
UA = {"User-Agent": "proveit/0.1 (research; public open data)"}


def load_case(case_id: str) -> dict:
    return json.loads((CASES / f"{case_id}.json").read_text())


def source_url(src: dict) -> str:
    url = src["url"]
    if "soql" in src:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(src["soql"])
    return url


def download(url: str, dest: Path, timeout: int = 1800) -> dict:
    # curl uses the system certificate store; python.org builds often have none.
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    subprocess.run(
        ["curl", "-fsSL", "--retry", "3", "-m", str(timeout), "-A", UA["User-Agent"], "-o", str(tmp), url],
        check=True,
    )
    h = hashlib.sha256()
    with open(tmp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    size = tmp.stat().st_size
    if size == 0:
        tmp.unlink()
        raise RuntimeError(f"empty download: {url}")
    tmp.replace(dest)
    return {
        "url": url,
        "file": dest.name,
        "bytes": size,
        "sha256": h.hexdigest(),
        "downloaded": dt.datetime.now().isoformat(timespec="seconds"),
    }


def download_arcgis_layer(layer_url: str, dest: Path, where: str = "1=1", page: int = 2000) -> dict:
    """Page through an ArcGIS feature layer into one GeoJSON file (WGS84)."""
    features, offset, pages = [], 0, []
    tmp = dest.with_suffix(".page.json")
    while True:
        q = urllib.parse.urlencode({"where": where, "outFields": "*", "outSR": 4326, "f": "geojson",
                                    "resultOffset": offset, "resultRecordCount": page, "orderByFields": "OBJECTID"})
        info = download(f"{layer_url}/query?{q}", tmp)
        batch = json.loads(tmp.read_text())
        if "error" in batch:
            raise RuntimeError(batch["error"])
        features += batch.get("features", [])
        pages.append(info["sha256"])
        if len(batch.get("features", [])) < page:
            break
        offset += page
    tmp.unlink()
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return {"url": layer_url, "where": where, "file": dest.name, "features": len(features),
            "bytes": dest.stat().st_size, "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            "page_sha256": pages, "downloaded": dt.datetime.now().isoformat(timespec="seconds")}


def download_elevation_tile(bbox_wgs84: tuple[float, float, float, float], dest: Path, cell_m: float = 1.0) -> dict:
    """USGS 3DEP bare-earth elevation (meters, NAVD88) for a lon/lat box, as GeoTIFF in Web Mercator."""
    import math

    x0, y0 = _merc(bbox_wgs84[0], bbox_wgs84[1])
    x1, y1 = _merc(bbox_wgs84[2], bbox_wgs84[3])
    # Web Mercator stretches distance by 1/cos(lat); size the image in true meters.
    k = 1 / math.cos(math.radians((bbox_wgs84[1] + bbox_wgs84[3]) / 2))
    w, h = min(8000, round((x1 - x0) / (cell_m * k))), min(8000, round((y1 - y0) / (cell_m * k)))
    q = urllib.parse.urlencode({"bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": 3857, "imageSR": 3857,
                                "size": f"{w},{h}", "format": "tiff", "pixelType": "F32",
                                "interpolation": "RSP_BilinearInterpolation", "f": "image"})
    url = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage?" + q
    return download(url, dest) | {"bbox_wgs84": bbox_wgs84, "size_px": [w, h], "cell_m": cell_m}


def _merc(lon: float, lat: float) -> tuple[float, float]:
    import math

    r = 6378137.0
    return math.radians(lon) * r, math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * r


def fetch_case(case_id: str, force: bool = False, only: list[str] | None = None) -> dict:
    case = load_case(case_id)
    folder = RAW / case_id
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    for key, src in case["sources"].items():
        if only and key not in only:
            continue
        dest = folder / src["file"]
        if dest.exists() and key in manifest and not force:
            print(f"  {key}: have {dest.name} ({manifest[key]['bytes']:,} bytes)")
            continue
        print(f"  {key}: downloading {src['about']}", flush=True)
        if "arcgis_layer" in src:
            manifest[key] = download_arcgis_layer(src["arcgis_layer"], dest, src.get("where", "1=1"))
        else:
            manifest[key] = download(source_url(src), dest)
        manifest[key]["about"] = src["about"]
        print(f"  {key}: {manifest[key]['bytes']:,} bytes")
        manifest_path.write_text(json.dumps(manifest, indent=2))
    if "elevation" in case and (not only or "elevation" in only):
        tiles = ELEVATION_TILES[case_id](case, folder)
        for name, bbox in tiles.items():
            dest = folder / "elevation" / f"{name}.tif"
            k = f"elevation/{name}"
            if dest.exists() and k in manifest and not force:
                continue
            manifest[k] = download_elevation_tile(bbox, dest, case["elevation"]["cell_m"]) | {"about": "USGS 3DEP bare-earth DEM"}
            manifest_path.write_text(json.dumps(manifest, indent=2))
        print(f"  elevation: {len(tiles)} tiles")
    return manifest


def _ida_tiles(case: dict, folder: Path) -> dict:
    """One elevation window around each group of high-water marks."""
    import csv

    lines = (folder / case["sources"]["hwm"]["file"]).read_text(encoding="utf-8-sig").splitlines()
    rows = list(csv.DictReader(lines[case["sources"]["hwm"]["header_line"]:]))
    half = case["elevation"]["window_deg"] / 2
    tiles: dict[str, tuple] = {}
    for r in rows:
        lat, lon = float(r["latitude_dd"]), float(r["longitude_dd"])
        cell = (round(lat / (2 * half)), round(lon / (2 * half)))  # snap so nearby marks share a tile
        name = f"t{cell[0]}_{cell[1]}".replace("-", "m")
        cy, cx = cell[0] * 2 * half, cell[1] * 2 * half
        tiles[name] = (cx - 2 * half, cy - 2 * half, cx + 2 * half, cy + 2 * half)
    return tiles


def _dins_tiles(case: dict, folder: Path, n: int = 3) -> dict:
    """Split each study box into n x n tiles; the elevation service rejects large requests."""
    tiles = {}
    for name, (x0, y0, x1, y1) in case["elevation"]["boxes"].items():
        dx, dy = (x1 - x0) / n, (y1 - y0) / n
        for i in range(n):
            for j in range(n):
                tiles[f"{name}_{i}{j}"] = (x0 + i * dx, y0 + j * dy, x0 + (i + 1) * dx, y0 + (j + 1) * dy)
    return tiles


ELEVATION_TILES = {"flood_ida": _ida_tiles, "wildfire_la": _dins_tiles}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fetch_case(args[0], force="--force" in sys.argv, only=args[1:] or None)
