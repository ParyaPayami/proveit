import arcpy, glob, os
from pathlib import Path
for p in [r"C:\proveit_work\fire_ems.gdb", r"C:\proveit_work\wildfire_la.gdb"]:
    arcpy.env.workspace=p
    for fc in arcpy.ListFeatureClasses():
        d=arcpy.Describe(fc); print(p, fc, arcpy.management.GetCount(fc)[0], d.shapeType, d.spatialReference.factoryCode, [f.name for f in arcpy.ListFields(fc)])
print(glob.glob(str(Path.home()/"Desktop"/"*.aprx")))
print(glob.glob(r"C:\Users\user\Documents\ArcGIS\Projects\*\*.aprx"))
print(os.path.exists(r"C:\proveit_work\T22"))
import csv
rows=list(csv.DictReader(open(r"\\Mac\Home\Desktop\Esri\proveit\outputs\fire_ems\results_by_zip.csv")))
print(len(rows), sum(1 for r in rows if r['obs_travel_min']), sum(1 for r in rows if r['obs_travel_min'] and int(r['obs_incidents'] or 0)<20), rows[0].keys())
