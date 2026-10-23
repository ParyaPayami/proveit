"""T22: one ArcGIS Pro project (3 maps + ProveIt toolbox) under C:\\proveit_work\\T22 only."""
import csv, json, shutil, sys, zipfile
from pathlib import Path
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
from common import OUTPUTS, PRO_DIR, WORK, log
import arcpy

BASE = r"C:\Users\user\Desktop\PlatterOfPython.aprx"      # read-only; saveACopy only
DEST = Path(r"C:\proveit_work\T22"); APRX = DEST / "T22.aprx"; GDB = DEST / "T22.gdb"
SUMMARY = Path(r"\\Mac\Home\Desktop\Esri\proveit\outputs\agent_eval\T22\build_summary.json")
assert str(APRX).startswith(r"C:\proveit_work\T22")

def rd(p): return list(csv.DictReader(open(p, encoding="utf-8")))

def add_fields(fc, rows, fckey, csvkey, fields):
    byk = {r[csvkey]: r for r in rows}
    for n, t in fields.items(): arcpy.management.AddField(fc, n, t)
    with arcpy.da.UpdateCursor(fc, [fckey] + list(fields)) as cur:
        for row in cur:
            s = byk.get(str(row[0])); vals = []
            for n, t in fields.items():
                v = s.get(n, "") if s else ""
                vals.append(None if v == "" else (float(v) if t == "DOUBLE" else v))
            cur.updateRow([row[0]] + vals)

def zoom(m, fc):
    try:
        cam = m.defaultCamera
        cam.setExtent(arcpy.Describe(fc).extent.projectAs(m.spatialReference)); m.defaultCamera = cam
    except Exception as e: log(f"extent not set {m.name}: {e}")

def newmap(aprx, name):
    m = aprx.createMap(name, "MAP")
    try: m.addBasemap("Light Gray Canvas")
    except Exception as e: log(f"no basemap {name}: {e}")
    return m

def rgb(r, g, b): return {"RGB": [r, g, b, 100]}

def unique(lyr, field, colors):
    sym = lyr.symbology; sym.updateRenderer("UniqueValueRenderer")
    sym.renderer.fields = [field]
    lyr.symbology = sym
    sym = lyr.symbology
    for grp in sym.renderer.groups:
        for it in grp.items:
            v = it.values[0][0]
            if v in colors:
                it.symbol.color = rgb(*colors[v]); 
                try: it.symbol.outlineColor = rgb(110, 110, 110)
                except Exception: pass
    lyr.symbology = sym

def main():
    arcpy.env.overwriteOutput = True
    DEST.mkdir(parents=True, exist_ok=True)
    arcpy.mp.ArcGISProject(BASE).saveACopy(str(APRX))
    if not arcpy.Exists(str(GDB)): arcpy.management.CreateFileGDB(str(DEST), "T22.gdb")
    aprx = arcpy.mp.ArcGISProject(str(APRX))
    for l in aprx.listLayouts(): aprx.deleteItem(l)
    for m in aprx.listMaps(): aprx.deleteItem(m)
    aprx.homeFolder = str(DEST)
    aprx.updateDatabases([{"databasePath": str(GDB), "isDefaultDatabase": True}])
    aprx.defaultGeodatabase = str(GDB)
    aprx.updateToolboxes([{"toolboxPath": str(PRO_DIR / "ProveIt.pyt"), "isDefaultToolbox": True}])
    aprx.updateFolderConnections([{"connectionString": str(DEST), "alias": "", "isHomeFolder": True}])
    S = {}

    # ---- 1 Fire coverage
    fire = arcpy.management.CopyFeatures(str(WORK / "fire_ems.gdb" / "zip_results"), str(GDB / "fire_zip_results"))[0]
    rows = rd(OUTPUTS / "fire_ems" / "results_by_zip.csv")
    add_fields(fire, rows, "modzcta", "modzcta", {"model_median_min": "DOUBLE", "obs_travel_min": "DOUBLE", "obs_incidents": "DOUBLE"})
    arcpy.management.AddField(fire, "scored", "TEXT"); arcpy.management.AddField(fire, "gap_min", "DOUBLE")
    with arcpy.da.UpdateCursor(fire, ["model_median_min", "obs_travel_min", "obs_incidents", "scored", "gap_min"]) as cur:
        for mod, obs, n, _, _ in cur:
            ok = mod is not None and obs is not None and (n or 0) >= 20      # same rule as the score (>=20 incidents)
            cur.updateRow([mod, obs, n, "Yes" if ok else "No (no model/observation or <20 incidents)",
                           (obs - mod) if ok else None])
    arcpy.management.CopyFeatures(str(WORK / "fire_ems.gdb" / "firehouses"), str(GDB / "firehouses"))
    m = newmap(aprx, "1 Fire coverage vs FDNY travel times")
    l = m.addDataFromPath(fire); l.name = "ZIP areas: observed minus modeled travel (min), scored areas only"
    try:
        sym = l.symbology; sym.updateRenderer("GraduatedColorsRenderer")
        sym.renderer.classificationField = "gap_min"; sym.renderer.breakCount = 5
        r = aprx.listColorRamps("Yellow-Orange-Red (5 Classes)") or aprx.listColorRamps("Red-Blue (Continuous)")
        if r: sym.renderer.colorRamp = r[0]
        l.symbology = sym
    except Exception as e: log(f"fire symbology: {e}")
    f = m.addDataFromPath(str(GDB / "firehouses")); f.name = "Firehouses"
    zoom(m, fire)
    with arcpy.da.SearchCursor(fire, ["scored", "gap_min"]) as c: rr = list(c)
    S["fire"] = {"zip_areas": len(rr), "scored": sum(1 for a, g in rr if a == "Yes"),
                 "not_scored": sum(1 for a, g in rr if a != "Yes"),
                 "firehouses": int(arcpy.management.GetCount(str(GDB / "firehouses"))[0])}

    # ---- 2 Ida flood
    pts = arcpy.management.XYTableToPoint(str(OUTPUTS / "flood_ida" / "points.csv"), str(GDB / "ida_points"),
                                          "x", "y", coordinate_system=arcpy.SpatialReference(3857))[0]
    arcpy.management.AddField(pts, "role", "TEXT")
    with arcpy.da.UpdateCursor(pts, ["kind", "interior", "role"]) as cur:
        for k, i, _ in cur:
            role = ("Control point (not a surveyed flood location)" if k == "control" else
                    "High-water mark, interior/basement (depth not comparable)" if str(i) == "True" else
                    "High-water mark, street/outdoor")
            cur.updateRow([k, i, role])
    m = newmap(aprx, "2 Ida flood marks vs terrain low spots")
    l = m.addDataFromPath(pts); l.name = "Ida high-water marks and control points"
    try:
        unique(l, "role", {"Control point (not a surveyed flood location)": (150, 150, 150),
                           "High-water mark, interior/basement (depth not comparable)": (255, 170, 0),
                           "High-water mark, street/outdoor": (0, 90, 200)})
    except Exception as e: log(f"flood symbology: {e}")
    zoom(m, pts)
    with arcpy.da.SearchCursor(pts, ["role"]) as c:
        d = {}
        for (r,) in c: d[r] = d.get(r, 0) + 1
    S["flood"] = {"points_total": sum(d.values()), "by_role": d}

    # ---- 3 Wildfire
    bld = arcpy.management.CopyFeatures(str(WORK / "wildfire_la.gdb" / "buildings"), str(GDB / "wildfire_buildings"))[0]
    add_fields(bld, rd(OUTPUTS / "wildfire_la" / "buildings.csv"), "OBJECTID", "oid",
               {"destroyed": "TEXT", "nn_distance_m": "DOUBLE", "neighbors_50m": "DOUBLE", "slope_deg": "DOUBLE", "open_land_distance_m": "DOUBLE"})
    arcpy.management.AddField(bld, "outcome", "TEXT")
    with arcpy.da.UpdateCursor(bld, ["DAMAGE", "destroyed", "outcome"]) as cur:
        for dmg, dest, _ in cur:
            if dest in ("True", "true", "1", "Yes", "yes"): o = "Destroyed"
            elif dest in ("False", "false", "0", "No", "no"): o = "Not destroyed (inspected)"
            elif dmg is None or str(dmg).strip() == "": o = "No inspection record (excluded, not 'undamaged')"
            else: o = "Inspected, outcome not used (e.g. inaccessible)"
            cur.updateRow([dmg, dest, o])
    m = newmap(aprx, "3 Wildfire structures vs damage inspections")
    l = m.addDataFromPath(bld); l.name = "Structures by inspection outcome (Eaton + Palisades)"
    try:
        unique(l, "outcome", {"Destroyed": (200, 30, 30), "Not destroyed (inspected)": (60, 160, 80),
                              "No inspection record (excluded, not 'undamaged')": (200, 200, 200),
                              "Inspected, outcome not used (e.g. inaccessible)": (240, 200, 60)})
    except Exception as e: log(f"wildfire symbology: {e}")
    zoom(m, bld)
    with arcpy.da.SearchCursor(bld, ["outcome", "DAMAGE", "destroyed"]) as c:
        d = {}; dm = {}; dd = {}
        for o, dg, de in c:
            d[o] = d.get(o, 0) + 1; dm[str(dg)] = dm.get(str(dg), 0) + 1; dd[str(de)] = dd.get(str(de), 0) + 1
    S["wildfire"] = {"structures_total": sum(d.values()), "by_outcome": d, "by_DAMAGE": dm, "by_destroyed_field": dd}

    aprx.save()
    S["maps"] = [mm.name for mm in aprx.listMaps()]
    S["layers"] = {mm.name: [ly.name for ly in mm.listLayers()] for mm in aprx.listMaps()}
    S["toolboxes"] = [str(t) for t in aprx.toolboxes] if hasattr(aprx, "toolboxes") else None
    S["uris"] = sorted(mp.getDefinition("V3").uRI for mp in aprx.listMaps())
    SUMMARY.write_text(json.dumps(S, indent=2, default=str))
    log("saved " + str(APRX))

if __name__ == "__main__":
    if "--views" in sys.argv:
        sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
        sys.argv = sys.argv[:1]
        from make_project import open_views
        S = json.loads(SUMMARY.read_text())
        open_views(APRX, S["uris"], APRX)
        a = arcpy.mp.ArcGISProject(str(APRX))
        v = {"maps": [m.name for m in a.listMaps()], "layouts": len(a.listLayouts()), "default_gdb": a.defaultGeodatabase,
             "toolboxes": [str(t) for t in a.toolboxes] if hasattr(a, "toolboxes") else None,
             "broken": {m.name: [l.name for l in m.listLayers() if l.isBroken] for m in a.listMaps()},
             "counts": {m.name: {l.name: int(arcpy.management.GetCount(l)[0]) for l in m.listLayers() if l.isFeatureLayer} for m in a.listMaps()}}
        S["verify"] = v; SUMMARY.write_text(json.dumps(S, indent=2, default=str)); print(json.dumps(v, indent=1))
    else:
        main()
