import csv, json, statistics as st, random
from collections import defaultdict
RAW="/Users/user/Desktop/Esri/proveit/data/raw/fire_ems/"
g=json.load(open(RAW+"modzcta.geojson"))
mem={}; 
for f in g["features"]:
    p=f["properties"]
    for z in [p["modzcta"]]+[s.strip() for s in (p.get("zcta") or "").split(",")]:
        if z: mem.setdefault(z,p["modzcta"])
label_extra={}
for f in g["features"]:
    p=f["properties"]
    for z in [s.strip() for s in p["label"].split(",")]:
        if z and z not in mem: label_extra[z]=p["modzcta"]
obs=json.load(open(RAW+"observed_by_zip_2025.json"))
acc=defaultdict(list); unm=[]
for r in obs:
    z=(r.get("zipcode") or "").split(".")[0]
    m=mem.get(z) or label_extra.get(z)
    if not m: unm.append((z or None,int(r["n"]))); continue
    acc[m].append((int(r["n"]),float(r["med_travel_s"]),float(r["med_response_s"])))
O={}
for m,parts in acc.items():
    n=sum(p[0] for p in parts)
    O[m]=(n,sum(p[0]*p[1] for p in parts)/n/60,sum(p[0]*p[2] for p in parts)/n/60)
pts=defaultdict(list); unreached=defaultdict(int)
for r in csv.DictReader(open("point_minutes.csv")):
    if r["minutes"]=="": unreached[r["modzcta"]]+=1
    else: pts[r["modzcta"]].append(float(r["minutes"]))
rows=[]
for m in O:
    if m in pts:
        rows.append(dict(z=m,n=O[m][0],obs=O[m][1],resp=O[m][2],mod=st.median(pts[m]),mean_mod=st.mean(pts[m]),unr=unreached[m],np=len(pts[m])))
MIN=20
use=[r for r in rows if r["n"]>=MIN]
excl=[(r["z"],r["n"]) for r in rows if r["n"]<MIN]
def stats(rs,key="mod"):
    d=[r["obs"]-r[key] for r in rs]
    w=[r["n"] for r in rs]
    tot=sum(w)
    mo=sum(r["obs"]*r["n"] for r in rs)/tot; mm=sum(r[key]*r["n"] for r in rs)/tot
    # regression obs ~ mod
    x=[r[key] for r in rs]; y=[r["obs"] for r in rs]
    mx,my=st.mean(x),st.mean(y)
    b=sum((a-mx)*(c-my) for a,c in zip(x,y))/sum((a-mx)**2 for a in x); a0=my-b*mx
    corr=st.correlation(x,y)
    return dict(n_areas=len(rs),mean_bias_min=st.mean(d),median_bias_min=st.median(d),mae=st.mean(abs(v) for v in d),
        rmse=(st.mean(v*v for v in d))**.5,weighted_obs=mo,weighted_mod=mm,weighted_bias=mo-mm,ratio_obs_over_mod=sum(y)/sum(x),
        pct_underestimated=100*sum(v>0 for v in d)/len(d),within_1min=100*sum(abs(v)<=1 for v in d)/len(d),
        slope=b,intercept=a0,r=corr,median_ratio=st.median([r["obs"]/r[key] for r in rs]))
res=stats(use)
random.seed(1)
bs=[]
for _ in range(2000):
    s=[random.choice(use) for _ in use]; bs.append(st.mean(r["obs"]-r["mod"] for r in s))
bs.sort(); res["mean_bias_ci95"]=[bs[50],bs[1949]]
# vs mean-point model and vs response time (wrong comparator, for illustration)
res["alt_mean_pointmodel_bias"]=st.mean(r["obs"]-r["mean_mod"] for r in use)
res["wrong_response_vs_model_bias"]=st.mean(r["resp"]-r["mod"] for r in use)
# bias by model-time tercile
use_s=sorted(use,key=lambda r:r["mod"]); k=len(use_s)//3
res["by_tercile"]=[dict(range=[t[0]["mod"],t[-1]["mod"]],mean_bias=st.mean(r["obs"]-r["mod"] for r in t),ratio=sum(r["obs"] for r in t)/sum(r["mod"] for r in t)) for t in (use_s[:k],use_s[k:2*k],use_s[2*k:])]
# borough by zip prefix
def boro(z):
    z=int(z)
    if 10000<=z<10300: return "Manhattan"
    if 10300<=z<10400: return "Staten Island"
    if 10400<=z<10500: return "Bronx"
    if 11200<=z<11257 and z not in(11004,): return "Brooklyn"
    if z in (11004,11005,11101,11102,11103,11104,11105,11106) or z>=11300: return "Queens"
    return "Brooklyn"
res["by_borough"]={}
for b in set(boro(r["z"]) for r in use):
    rs=[r for r in use if boro(r["z"])==b]
    res["by_borough"][b]=dict(n=len(rs),mean_bias=st.mean(r["obs"]-r["mod"] for r in rs),ratio=sum(r["obs"] for r in rs)/sum(r["mod"] for r in rs))
res["worst"]=[dict(z=r["z"],n=r["n"],obs=round(r["obs"],2),mod=round(r["mod"],2),bias=round(r["obs"]-r["mod"],2)) for r in sorted(use,key=lambda r:-abs(r["obs"]-r["mod"]))[:8]]
res["excluded_small"]=excl
res["unmatched_zips"]=unm
res["all_areas_incl_small"]=stats(rows)
res["unreached_points_total"]=sum(unreached.values()); res["points_total"]=sum(len(v) for v in pts.values())+sum(unreached.values())
res["median_obs_min"]=st.median(r["obs"] for r in use); res["median_mod_min"]=st.median(r["mod"] for r in use)
json.dump(res,open("analysis.json","w"),indent=1)
with open("area_comparison.csv","w",newline="") as f:
    w=csv.writer(f); w.writerow(["modzcta","incidents","obs_travel_min","model_median_min","bias_min","unreached_pts"]); 
    for r in sorted(rows,key=lambda r:r["z"]): w.writerow([r["z"],r["n"],round(r["obs"],3),round(r["mod"],3),round(r["obs"]-r["mod"],3),r["unr"]])
print(json.dumps(res,indent=1))
