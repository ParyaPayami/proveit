import sys, math, random, json, csv
from pathlib import Path
sys.path.insert(0, r"\\Mac\Home\Desktop\Esri\proveit\pro")
import flood_ida as F
from pathlib import Path
import numpy as np, arcpy
F.WORK = Path(r"C:\proveit_work\T28")
F.WORK.mkdir(parents=True, exist_ok=True)
arcpy.env.scratchWorkspace = str(F.WORK)
arcpy.env.overwriteOutput = True
F.check_out("Spatial")
OUT = Path(r"\\Mac\Home\Desktop\Esri\proveit\outputs\agent_eval\T28")
key = F.CASE["answer_key"]; TH = key["sink_threshold_m"]
marks = F.read_marks()
tiles = [F.Tile(p) for p in sorted((F.DATA/"elevation").glob("*.tif"))]
F.log(f"{len(marks)} marks {len(tiles)} tiles")

def win_max(t, x, y, rad_cells):
    col, row = int((x-t.x0)/t.cw), int((t.y1-y)/t.ch)
    r0, r1 = max(row-rad_cells,0), row+rad_cells+1
    c0, c1 = max(col-rad_cells,0), col+rad_cells+1
    w = t.sink[r0:r1, c0:c1]
    return float(np.nanmax(w)) if w.size and not np.all(np.isnan(w)) else math.nan

def edge_dist_m(t, x, y):
    e = t.extent
    return min(x-e.XMin, e.XMax-x, y-e.YMin, e.YMax-y)*t.k

rng = random.Random(42)
rows=[]; notile=0
for m in marks:
    x,y = F.merc(m["lon"], m["lat"])
    ins=[t for t in tiles if t.contains(x,y)]
    if not ins: notile+=1; continue
    t=min(ins,key=lambda t:t.center_dist(x,y))
    z,s,tpi=t.values(x,y)
    rows.append(dict(kind="mark",id=m["id"],site=m["site"],tile=t.name,dem=z,sink=s,sink_r3=win_max(t,x,y,3),sink_r8=win_max(t,x,y,8),
        obs_depth_m=m["obs_depth_m"],interior=m["interior"],quality=m["quality"],edge_m=edge_dist_m(t,x,y)))
    made=tries=0
    while made<key["control_points_per_mark"] and tries<500:
        tries+=1
        r=key["control_radius_m"]*math.sqrt(rng.random())/t.k; a=rng.random()*2*math.pi
        cx,cy=x+r*math.cos(a),y+r*math.sin(a)
        cz,cs,_=t.values(cx,cy)
        if math.isnan(cz) or cz<0.5: continue
        rows.append(dict(kind="control",id=f"{m['id']}_c{made}",site=m["site"],tile=t.name,dem=cz,sink=cs,sink_r3=win_max(t,cx,cy,3),sink_r8=win_max(t,cx,cy,8),
            obs_depth_m=None,interior=None,quality=None,edge_m=edge_dist_m(t,cx,cy)))
        made+=1
def clean(v): return "" if v is None or (isinstance(v,float) and math.isnan(v)) else v
with open(OUT/"t28_points.csv","w",newline="") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader()
    for r in rows: w.writerow({k:clean(v) for k,v in r.items()})

def stats(sel, col):
    mk=[r for r in rows if r["kind"]=="mark" and sel(r)]; ct=[r for r in rows if r["kind"]=="control"]
    hit=lambda r: (not math.isnan(r[col])) and r[col]>TH
    tp=sum(hit(r) for r in mk); fn=len(mk)-tp
    cf=sum(hit(r) for r in ct)
    return dict(n_marks=len(mk),hits=tp,misses=fn,miss_rate=round(fn/len(mk),3) if mk else None,
                n_controls=len(ct),controls_flagged=cf,control_flag_rate=round(cf/len(ct),3))
res={"threshold_m":TH,"marks_total":len(marks),"marks_without_tile":notile}
allm=lambda r:True
res["all_cell"]=stats(allm,"sink"); res["all_r3_(+-6m)"]=stats(allm,"sink_r3"); res["all_r8_(+-16m)"]=stats(allm,"sink_r8")
nonint=lambda r: not r["interior"]
res["noninterior_cell"]=stats(nonint,"sink"); res["noninterior_r3"]=stats(nonint,"sink_r3"); res["noninterior_r8"]=stats(nonint,"sink_r8")
res["interior_cell"]=stats(lambda r:r["interior"],"sink")
mk=[r for r in rows if r["kind"]=="mark"]
res["interior_marks"]=sum(1 for r in mk if r["interior"])
res["marks_nodepth"]=sum(1 for r in mk if r["obs_depth_m"] is None)
res["marks_near_tile_edge_lt50m"]=sum(1 for r in mk if r["edge_m"]<50)
res["sink_nan_marks"]=sum(1 for r in mk if math.isnan(r["sink"]))
res["distinct_sites"]=len({r["site"] for r in mk})
sk=[r["sink"] for r in rows if r["kind"]=="control"]
res["control_sink_quantiles"]={q:round(float(np.nanpercentile(sk,q)),3) for q in (50,90,95,99)}
res["mark_sink_quantiles"]={q:round(float(np.nanpercentile([r["sink"] for r in mk],q)),3) for q in (50,75,90,95)}
# fraction of grid cells flagged overall (base rate)
tot=fl=0
for t in tiles:
    v=t.sink[~np.isnan(t.sink)]; tot+=v.size; fl+=int((v>TH).sum())
res["all_tiles_cell_fraction_sink_gt_thr"]=round(fl/tot,4)
# same threshold with pairs: wilson-ish note; also sensitivity thresholds
for th in (0.05,0.10,0.30):
    res[f"thr{th}"]=dict(miss_rate=round(sum(1 for r in mk if not r["sink"]>th)/len(mk),3),ctl_flag=round(sum(1 for r in rows if r["kind"]=="control" and r["sink"]>th)/sum(1 for r in rows if r["kind"]=="control"),3))
(OUT/"t28_results.json").write_text(json.dumps(res,indent=2,default=str))
print(json.dumps(res,indent=1,default=str))
