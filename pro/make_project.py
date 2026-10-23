"""Build an ArcGIS Pro project with one map per case and the ProveIt toolbox.

Pro can't create a project from scratch in ArcPy, so this copies an existing
project (read-only use of the original), strips its maps, layouts and
connections, and fills it with ProveIt results.
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import OUTPUTS, PRO_DIR, PROJECT, WORK, log  # noqa: E402

import arcpy  # noqa: E402

BASE = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else Path.home() / "Desktop" / "PlatterOfPython.aprx"
DEST_DIR = Path.home() / "Documents" / "ArcGIS" / "Projects" / "ProveIt"
APRX = DEST_DIR / "ProveIt.aprx"
GDB = DEST_DIR / "ProveIt.gdb"


def fresh_project() -> arcpy.mp.ArcGISProject:
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    if APRX.exists():
        APRX.unlink()
    arcpy.mp.ArcGISProject(str(BASE)).saveACopy(str(APRX))
    if not arcpy.Exists(str(GDB)):
        arcpy.management.CreateFileGDB(str(DEST_DIR), GDB.name)
    aprx = arcpy.mp.ArcGISProject(str(APRX))
    for lyt in aprx.listLayouts():
        aprx.deleteItem(lyt)
    for m in aprx.listMaps():
        aprx.deleteItem(m)
    aprx.homeFolder = str(DEST_DIR)
    aprx.updateDatabases([{"databasePath": str(GDB), "isDefaultDatabase": True}])
    aprx.defaultGeodatabase = str(GDB)
    aprx.updateToolboxes([{"toolboxPath": str(PRO_DIR / "ProveIt.pyt"), "isDefaultToolbox": True}])
    aprx.updateFolderConnections([{"connectionString": str(DEST_DIR), "alias": "", "isHomeFolder": True},
                                  {"connectionString": str(PROJECT), "alias": "ProveIt kit", "isHomeFolder": False}])
    return aprx


def add_fields_from_csv(fc: str, csv_path: Path, fc_key: str, csv_key: str, fields: dict[str, str]) -> None:
    rows = {r[csv_key]: r for r in csv.DictReader(open(csv_path, encoding="utf-8"))}
    for name, ftype in fields.items():
        arcpy.management.AddField(fc, name, ftype)
    with arcpy.da.UpdateCursor(fc, [fc_key] + list(fields)) as cur:
        for row in cur:
            src = rows.get(str(row[0]))
            vals = []
            for name, ftype in fields.items():
                v = src.get(name, "") if src else ""
                vals.append(None if v == "" else (float(v) if ftype == "DOUBLE" else v))
            cur.updateRow([row[0]] + vals)


def zoom_to(m, fc: str) -> None:
    """Make the map open on its data instead of the whole world."""
    try:
        cam = m.defaultCamera
        cam.setExtent(arcpy.Describe(fc).extent.projectAs(m.spatialReference))
        m.defaultCamera = cam
    except Exception as exc:
        log(f"default extent not set for {m.name}: {exc}")


def _map_view(uri: str, instance: int) -> dict:
    # Same shape Pro writes for an open map tab; the camera comes from the map's default.
    return {"type": "CIMMapView", "viewableObjectPath": uri, "viewType": "esri_mapping_mapPane",
            "instanceID": instance, "viewingMode": "Map", "verticalExaggerationScaleFactor": 1,
            "timeDisplay": {"type": "CIMMapTimeDisplay", "defaultTimeIntervalUnits": "esriTimeUnitsUnknown",
                            "timeRelation": "esriTimeRelationOverlaps"},
            "sceneDrawingMode": "Perspective", "fieldOfView": 55, "colorVisionDeficiencyMode": "None"}


def _pane_layout(layout_xml: str, count: int) -> str:
    """Point the saved pane layout at `count` open map tabs (ids 1..count)."""
    import html
    import re
    import uuid
    from xml.sax.saxutils import escape

    head, rest = layout_xml.split("<PaneState>", 1)
    inner, tail = rest.split("</PaneState>", 1)
    dock = html.unescape(inner)
    ids = [str(uuid.uuid4()) for _ in range(count)]
    windows = "".join(
        f'<DocumentWindow UniqueId="{u}" SerializationId="esri_mapping_mapPane_{i}" Name="esri_mapping_mapPane_{i}" '
        f'IsOpen="true" State="Document"><Tag xsi:type="xsd:unsignedInt">{i}</Tag></DocumentWindow>'
        for i, u in enumerate(ids, 1))
    refs = "".join(f'<UIElement xsi:type="DocumentWindowRef" UniqueId="{u}" />' for u in ids)
    dock = re.sub(r"<DocumentWindows>.*?</DocumentWindows>|<DocumentWindows\s*/>",
                  f"<DocumentWindows>{windows}</DocumentWindows>", dock, flags=re.S)
    dock = re.sub(r'<Content xsi:type="TabbedMdiContainer"[^>]*?(/>|>.*?</Content>)',
                  f'<Content xsi:type="TabbedMdiContainer" SelectedWindowUniqueId="{ids[0]}">{refs}</Content>',
                  dock, count=1, flags=re.S)
    return head + "<PaneState>" + escape(dock) + "</PaneState>" + tail


def open_views(aprx_path: Path, map_uris: list[str], out_path: Path | None = None) -> None:
    """Record the maps as open tabs, so Pro shows them when the project opens.

    ArcPy can't open a view. Pro restores a tab only when it is listed both in
    `views` and in the pane layout (viewLayoutXML) of GISProject.json.
    """
    out_path = out_path or aprx_path
    tmp = out_path.with_suffix(".tmp")
    with zipfile.ZipFile(aprx_path) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename == "GISProject.json":
                g = json.loads(data.decode("utf-8-sig"))
                g["views"] = [_map_view(uri, i) for i, uri in enumerate(map_uris, 1)]
                if g.get("viewLayoutXML") and "<PaneState>" in g["viewLayoutXML"]:
                    g["viewLayoutXML"] = _pane_layout(g["viewLayoutXML"], len(map_uris))
                data = json.dumps(g).encode("utf-8")
            dst.writestr(item, data)
    shutil.move(tmp, out_path)


def new_map(aprx, name: str):
    m = aprx.createMap(name, "MAP")
    try:
        m.addBasemap("Light Gray Canvas")
    except Exception as exc:  # basemaps need a portal connection
        log(f"no basemap for {name}: {exc}")
    return m


def graduated(lyr, field: str, classes: int = 5, ramp: str = "Red-Blue (Continuous)") -> None:
    try:
        sym = lyr.symbology
        sym.updateRenderer("GraduatedColorsRenderer")
        sym.renderer.classificationField = field
        sym.renderer.breakCount = classes
        ramps = aprx_ramps(ramp)
        if ramps:
            sym.renderer.colorRamp = ramps[0]
        lyr.symbology = sym
    except Exception as exc:
        log(f"symbology skipped for {lyr.name}: {exc}")


def unique(lyr, field: str) -> None:
    try:
        sym = lyr.symbology
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [field]
        lyr.symbology = sym
    except Exception as exc:
        log(f"symbology skipped for {lyr.name}: {exc}")


_APRX = None


def aprx_ramps(name: str):
    return _APRX.listColorRamps(name) if _APRX else []


def main() -> None:
    global _APRX
    arcpy.env.overwriteOutput = True
    aprx = _APRX = fresh_project()

    # 1. Fire coverage: model vs observed by ZIP area.
    fire = arcpy.management.CopyFeatures(str(WORK / "fire_ems.gdb" / "zip_results"), str(GDB / "fire_zip_results"))[0]
    add_fields_from_csv(fire, OUTPUTS / "fire_ems" / "results_by_zip.csv", "modzcta", "modzcta",
                        {"model_median_min": "DOUBLE", "obs_travel_min": "DOUBLE", "obs_incidents": "DOUBLE"})
    arcpy.management.CalculateField(fire, "gap_min", "None if !obs_travel_min! is None or !model_median_min! is None "
                                    "else !obs_travel_min! - !model_median_min!", "PYTHON3", field_type="DOUBLE")
    arcpy.management.CopyFeatures(str(WORK / "fire_ems.gdb" / "firehouses"), str(GDB / "firehouses"))
    m = new_map(aprx, "1 Fire coverage vs FDNY travel times")
    graduated(m.addDataFromPath(str(fire)), "gap_min")
    m.addDataFromPath(str(GDB / "firehouses"))
    zoom_to(m, fire)

    # 2. Ida flood: marks and control points with sink depth.
    pts = arcpy.management.XYTableToPoint(str(OUTPUTS / "flood_ida" / "points.csv"), str(GDB / "ida_points"),
                                          "x", "y", coordinate_system=arcpy.SpatialReference(3857))[0]
    m = new_map(aprx, "2 Ida flood marks vs terrain low spots")
    unique(m.addDataFromPath(str(pts)), "kind")
    zoom_to(m, pts)

    # 3. Wildfire: inspected structures with features.
    bld = arcpy.management.CopyFeatures(str(WORK / "wildfire_la.gdb" / "buildings"), str(GDB / "wildfire_buildings"))[0]
    add_fields_from_csv(bld, OUTPUTS / "wildfire_la" / "buildings.csv", "OBJECTID", "oid",
                        {"destroyed": "TEXT", "nn_distance_m": "DOUBLE", "neighbors_50m": "DOUBLE",
                         "slope_deg": "DOUBLE", "open_land_distance_m": "DOUBLE"})
    m = new_map(aprx, "3 Wildfire structures vs damage inspections")
    unique(m.addDataFromPath(str(bld)), "DAMAGE")
    zoom_to(m, bld)

    aprx.save()
    uris = sorted(mp.getDefinition("V3").uRI for mp in aprx.listMaps())
    (DEST_DIR / "views.json").write_text(json.dumps(uris))
    log(f"project saved: {APRX}; now run with --views to open the maps on startup")


if __name__ == "__main__":
    if "--views" in sys.argv:
        # Separate process: ArcPy holds the .aprx open until its process exits.
        out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
        open_views(APRX, json.loads((DEST_DIR / "views.json").read_text()), out)
        log("map views recorded")
    else:
        main()
