import arcpy, csv, json, math, os, glob
from pathlib import Path
raw=Path(r"\\Mac\Home\Desktop\Esri\proveit\data\raw\flood_ida")
out=Path(r"\\Mac\Home\Desktop\Esri\proveit\outputs\agent_eval\T27")
lines=(raw/"FilteredHWMs_NewYork.csv").read_text(encoding="utf-8",errors="replace").split("\n",1)[1].splitlines()
rows=list(csv.DictReader(lines))
tiles=[]
meta=[]
for f in sorted(glob.glob(str(raw/"elevation"/"*.tif"))):
    r=arcpy.Raster(f); d=arcpy.Describe(f)
    e=r.extent
    tiles.append((f,r,e))
    if len(meta)<2:
        meta.append(dict(f=f,sr=d.spatialReference.name,wkid=d.spatialReference.factoryCode,cell=(r.meanCellWidth,r.meanCellHeight),nodata=r.noDataValue,ptype=r.pixelType,bands=r.bandCount,vcs=d.spatialReference.VCS.name if d.spatialReference.VCS else None,ext=[e.XMin,e.YMin,e.XMax,e.YMax]))
print(json.dumps(meta,indent=1))
sr3857=arcpy.SpatialReference(3857); sr4326=arcpy.SpatialReference(4326)
res=[]
for r in rows:
    lat=float(r['latitude_dd']);lon=float(r['longitude_dd'])
    p=arcpy.PointGeometry(arcpy.Point(lon,lat),sr4326).projectAs(sr3857).firstPoint
    val=None;tile=None;n=0
    for f,ras,e in tiles:
        if e.XMin<=p.X<=e.XMax and e.YMin<=p.Y<=e.YMax:
            n+=1
            v=arcpy.GetCellValue_management(ras,f"{p.X} {p.Y}","1").getOutput(0)
            if v not in ("NoData","") and val is None:
                val=float(v);tile=os.path.basename(f)
    res.append(dict(hwm_id=r['hwm_id'],lat=lat,lon=lon,elev_ft=float(r['elev_ft']),hag=r['height_above_gnd'],dem_raw=val,tile=tile,ntiles=n,county=r['countyName'],q=r['hwmQualityName'],unc=r['uncertainty'],stillwater=r['stillwater']))
json.dump(dict(meta=meta,res=res),open(out/"raw_extract.json","w"),indent=1)
print(len(res),sum(1 for x in res if x['dem_raw'] is None))
