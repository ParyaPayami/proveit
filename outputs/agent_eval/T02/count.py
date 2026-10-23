import arcpy, os, json, collections
w=r"C:\proveit_work"; g=w+r"\T02_streets.gdb"
src=w+r"\streets_cscl.geojson"
print("geojson bytes", os.path.getsize(src))
if not arcpy.Exists(g): arcpy.management.CreateFileGDB(w,"T02_streets.gdb")
raw=g+r"\raw"
if not arcpy.Exists(raw): arcpy.conversion.JSONToFeatures(src, raw, "POLYLINE")
print("total", arcpy.management.GetCount(raw)[0])
print([ (f.name,f.type) for f in arcpy.ListFields(raw) if f.name in("rw_type","trafdir")])
D="'1','2','3','4','9','10','13'"
where=f"rw_type IN ({D}) AND trafdir IN ('TW','FT','TF')"
lyr=arcpy.management.MakeFeatureLayer(raw,"d",where)[0]
print("drivable", arcpy.management.GetCount(lyr)[0])
c=collections.Counter()
with arcpy.da.SearchCursor(raw,["rw_type","trafdir"]) as cur:
    for r in cur: c[r]+=1
print("rw_type only", sum(v for (a,b),v in c.items() if a in {"1","2","3","4","9","10","13"}))
print("trafdir null/NV in drivable rw", {k:v for k,v in c.items() if k[1] not in("TW","FT","TF") and k[0] in {"1","2","3","4","9","10","13"}})
json.dump({"total":int(arcpy.management.GetCount(raw)[0]),"drivable":int(arcpy.management.GetCount(lyr)[0])},open(r"\\Mac\Home\Desktop\Esri\proveit\outputs\agent_eval\T02\arcpy_counts.json","w"))
