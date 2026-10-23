import csv, json, collections
p="/Users/user/Desktop/Esri/proveit/data/raw/flood_ida/FilteredHWMs_NewYork.csv"
with open(p, encoding="utf-8", errors="replace", newline="") as f:
    f.readline()  # citation line
    rows=list(csv.DictReader(f))
n=len(rows)
sites=set(r["site_no"] for r in rows)
ids=[r["hwm_id"] for r in rows]
def num(x):
    try: return float(x)
    except: return None
bad_xy=[r["hwm_id"] for r in rows if num(r["latitude_dd"]) is None or num(r["longitude_dd"]) is None]
h=[num(r["height_above_gnd"]) for r in rows]
hv=[x for x in h if x is not None]
per=collections.Counter(r["site_no"] for r in rows)
kw=("interior","inside","basement","indoor","garage","stair","floor","apartment","vestibule")
interior=[r["hwm_id"] for r in rows if any(k in (r["hwm_locationdescription"]+" "+r["hwm_notes"]).lower() for k in kw)]
dup_coords=collections.Counter((r["latitude_dd"],r["longitude_dd"]) for r in rows)
out=dict(rows=n,unique_hwm_id=len(set(ids)),sites_site_no=len(sites),sites_site_id=len(set(r["site_id"] for r in rows)),
 counties=dict(collections.Counter(r["countyName"] for r in rows)),events=dict(collections.Counter(r["event_id"] for r in rows)),
 missing_xy=bad_xy,missing_height=n-len(hv),neg_or_zero_height=sum(1 for x in hv if x<=0),
 height_ft_min=min(hv),height_ft_max=max(hv),height_ft_median=sorted(hv)[len(hv)//2],
 marks_per_site_max=max(per.values()),sites_with_1=sum(1 for v in per.values() if v==1),sites_multi=sum(1 for v in per.values() if v>1),
 interior_keyword_marks=len(interior),dup_coord_groups=sum(1 for v in dup_coords.values() if v>1),
 quality=dict(collections.Counter(r["hwmQualityName"] for r in rows)),env=dict(collections.Counter(r["hwm_environment"] for r in rows)),
 lat_range=[min(num(r["latitude_dd"]) for r in rows),max(num(r["latitude_dd"]) for r in rows)],
 lon_range=[min(num(r["longitude_dd"]) for r in rows),max(num(r["longitude_dd"]) for r in rows)])
print(json.dumps(out,indent=1))
json.dump(out,open("hwm_summary.json","w"),indent=1)
