import arcpy
a = arcpy.mp.ArcGISProject(r"C:\proveit_work\T22\T22.aprx")
for m in a.listMaps():
    for l in m.listLayers():
        if l.isFeatureLayer:
            r = l.symbology.renderer
            extra = ""
            if r.type == "UniqueValueRenderer": extra = [(i.label, i.symbol.color) for g in r.groups for i in g.items]
            print(m.name, "|", l.name, "|", r.type, getattr(r, "classificationField", ""), extra)
