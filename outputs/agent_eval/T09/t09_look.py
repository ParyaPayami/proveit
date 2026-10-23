import arcpy
g = r"C:\proveit_work\fire_ems.gdb"
arcpy.env.workspace = g
for ds in [None, "net"]:
    arcpy.env.workspace = g if ds is None else g + "\\" + ds
    print(ds, arcpy.ListFeatureClasses(), arcpy.ListDatasets())
for fc in ["firehouses", "zips", "mids"]:
    p = g + "\\" + fc
    print(fc, arcpy.management.GetCount(p)[0], [f.name for f in arcpy.ListFields(p)][:20])
print(arcpy.Describe(g+"\\net\\streets_nd").networkType if arcpy.Exists(g+"\\net\\streets_nd") else "no nd")
