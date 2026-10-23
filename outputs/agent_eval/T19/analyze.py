import csv, json, collections
rows=list(csv.DictReader(open("features.csv")))
D={"Destroyed (>50%)"}; N={"No Damage","Affected (1-9%)","Minor (10-25%)","Major (26-50%)"}
cnt=collections.Counter(); R=[]
for r in rows:
    d=r["damage"]
    if d in D: y=1
    elif d in N: y=0
    else:
        cnt["excl_none" if d=="" else "excl_"+d]+=1; continue
    cnt["destroyed" if y else "not_destroyed"]+=1
    rec={"y":y,"fire":r["fire"],"damage":d}
    for k in ("nn_distance_m","neighbors_50m","slope_deg","open_land_distance_m"):
        rec[k]=float(r[k]) if r[k]!="" else None
    R.append(rec)
print(cnt, len(rows))
def auc(data,k,sign):  # sign=-1 : lower is riskier
    d=[(sign*x[k]*-1 if False else (-x[k] if sign<0 else x[k]),x["y"]) for x in data if x[k] is not None]
    d.sort(key=lambda t:t[0]); n=len(d); P=sum(y for _,y in d); Nn=n-P
    i=0; rs=0.0
    while i<n:
        j=i
        while j<n and d[j][0]==d[i][0]: j+=1
        avg=(i+j+1)/2
        rs+=avg*sum(y for _,y in d[i:j]); i=j
    return (rs-P*(P+1)/2)/(P*Nn), n, P
dirs={"nn_distance_m":-1,"neighbors_50m":1,"slope_deg":1,"open_land_distance_m":-1}
out={"counts":dict(cnt)}
for scope in ("all","eaton","palisades"):
    data=R if scope=="all" else [x for x in R if x["fire"]==scope]
    out[scope]={"n":len(data),"destroyed":sum(x["y"] for x in data),"rate":sum(x["y"] for x in data)/len(data)}
    for k,s in dirs.items():
        a,n,P=auc(data,k,s); out[scope]["auc_"+k]=round(a,3); out[scope]["n_"+k]=n
    # bins on open land distance
    bins=[(0,25),(25,50),(50,100),(100,150),(150,250),(250,1e9)]
    b=[]
    sub=[x for x in data if x["open_land_distance_m"] is not None]
    for lo,hi in bins:
        s=[x for x in sub if lo<=x["open_land_distance_m"]<hi]
        b.append({"bin_m":f"{lo}-{hi if hi<1e8 else 'inf'}","n":len(s),"destroyed_rate":round(sum(x["y"] for x in s)/len(s),3) if s else None})
    out[scope]["open_land_bins"]=b
    # quartiles
    vals=sorted(x["open_land_distance_m"] for x in sub)
    q=[vals[int(len(vals)*f)] for f in (.25,.5,.75)]
    out[scope]["open_quartile_cuts"]=q
    qs=[]
    edges=[-1]+q+[1e12]
    for i in range(4):
        s=[x for x in sub if edges[i]<x["open_land_distance_m"]<=edges[i+1]]
        qs.append({"q":i+1,"n":len(s),"rate":round(sum(x["y"] for x in s)/len(s),3)})
    out[scope]["open_quartile_rates"]=qs
    # missing open distance
    out[scope]["n_open_missing"]=len(data)-len(sub)
    # missing = outside core (edge) : rate
    miss=[x for x in data if x["open_land_distance_m"] is None]
    out[scope]["rate_open_missing"]=round(sum(x["y"] for x in miss)/len(miss),3) if miss else None
    # stratified: within neighbors_50m tertile-like strata
    strat=[]
    for lo,hi in [(0,5),(5,15),(15,30),(30,1e9)]:
        s=[x for x in sub if lo<=x["neighbors_50m"]<hi]
        if len(s)>50 and sum(x["y"] for x in s) and sum(x["y"] for x in s)<len(s):
            a,n,P=auc(s,"open_land_distance_m",-1)
            strat.append({"nbr":f"{lo}-{hi}","n":n,"destroyed":P,"auc_open":round(a,3)})
    out[scope]["auc_open_within_density_strata"]=strat
    # correlation of open distance with neighbors
    import math
    xs=[(x["open_land_distance_m"],x["neighbors_50m"]) for x in sub]
    mx=sum(a for a,_ in xs)/len(xs); my=sum(b for _,b in xs)/len(xs)
    cov=sum((a-mx)*(b-my) for a,b in xs); sx=math.sqrt(sum((a-mx)**2 for a,_ in xs)); sy=math.sqrt(sum((b-my)**2 for _,b in xs))
    out[scope]["corr_open_vs_neighbors"]=round(cov/(sx*sy),3)
    out[scope]["median_open_m"]=q[1]
json.dump(out,open("analysis.json","w"),indent=1)
print(json.dumps(out,indent=1))
