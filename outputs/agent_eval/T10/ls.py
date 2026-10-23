import arcpy
arcpy.env.workspace=r"C:\proveit_work\fire_ems.gdb"
for d in arcpy.ListDatasets() or []:
    print(d, arcpy.ListFeatureClasses(feature_dataset=d))
print(arcpy.ListFeatureClasses(), arcpy.ListTables())
for fc in ["mids","firehouses","zips"]:
    print(fc,[f.name for f in arcpy.ListFields(fc)], arcpy.management.GetCount(fc))
