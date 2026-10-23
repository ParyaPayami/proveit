"""Report what this ArcGIS Pro installation can do (run first on a new machine)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS, WORK, log, write_json  # noqa: E402

import arcpy  # noqa: E402

info = arcpy.GetInstallInfo()
report = {
    "product": f"{info.get('ProductName')} {info.get('Version')}",
    "license_level": info.get("LicenseLevel"),
    "license_type": info.get("LicenseType"),
    "python": sys.version.split()[0],
    "extensions": {e: arcpy.CheckExtension(e) for e in ["Network", "Spatial", "3D", "GeoStats", "ImageAnalyst"]},
    "portal": arcpy.GetActivePortalURL(),
    "work_dir": str(WORK),
}
for k, v in report.items():
    log(f"{k}: {v}")
write_json(OUTPUTS / "environment.json", report)
