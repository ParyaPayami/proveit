"""Shared helpers for scripts that run inside ArcGIS Pro's Python."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import time
from pathlib import Path

PRO_DIR = Path(__file__).resolve().parent
PROJECT = PRO_DIR.parent
RAW = PROJECT / "data" / "raw"
OUTPUTS = PROJECT / "outputs"
WORK = Path(os.environ.get("PROVEIT_WIN_WORK", r"C:\proveit_work"))

_T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - _T0:7.1f}s] {msg}", flush=True)


def work_gdb(name: str, fresh: bool = False) -> str:
    """Local Windows file geodatabase for scratch work."""
    import arcpy

    WORK.mkdir(parents=True, exist_ok=True)
    gdb = WORK / f"{name}.gdb"
    if fresh and arcpy.Exists(str(gdb)):
        arcpy.management.Delete(str(gdb))
    if not arcpy.Exists(str(gdb)):
        arcpy.management.CreateFileGDB(str(WORK), f"{name}.gdb")
    return str(gdb)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def provenance(case: str, inputs: list[Path], params: dict, script: str) -> dict:
    """Record what an output was built from: data hashes, code hash, parameters."""
    import arcpy

    info = arcpy.GetInstallInfo()
    return {
        "case": case,
        "created": dt.datetime.now().isoformat(timespec="seconds"),
        "arcgis_pro": f"{info.get('ProductName')} {info.get('Version')}",
        "python": sys.version.split()[0],
        "script": script,
        "script_sha256": sha256(Path(script)),
        "inputs": {str(Path(p).relative_to(PROJECT)): sha256(Path(p)) for p in inputs},
        "params": params,
    }


def check_out(*extensions: str) -> None:
    import arcpy

    for ext in extensions:
        if arcpy.CheckExtension(ext) != "Available":
            raise RuntimeError(f"ArcGIS extension {ext} is not available")
        arcpy.CheckOutExtension(ext)
