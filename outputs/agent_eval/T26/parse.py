import csv, collections, statistics, json
rows=[]
with open('data/raw/flood_ida/FilteredHWMs_NewYork.csv',newline='',encoding='utf-8-sig',errors='replace') as f:
    r=csv.reader(f)
    lines=list(r)
print(len(lines)); 
hi=[i for i,l in enumerate(lines) if l and l[0]=='latitude_dd'][0]
hdr=lines[hi]; print(hi,len(hdr))
data=[l for l in lines[hi+1:]]
print('raw data rows',len(data), collections.Counter(len(l) for l in data))
recs=[dict(zip(hdr,l)) for l in data if any(x.strip() for x in l)]
print(len(recs))
def num(s):
    try: return float(s)
    except: return None
for c in ['latitude_dd','longitude_dd','elev_ft','height_above_gnd','uncertainty']:
    v=[num(x[c]) for x in recs]; ok=[a for a in v if a is not None]
    print(c,'missing/nonnum',len(v)-len(ok),'min',min(ok),'max',max(ok),'med',statistics.median(ok))
    print('  nonnum:',[x[c] for x in recs if num(x[c]) is None][:5])
for c in ['hwm_id','site_id','site_no','event_id','countyName','verticalDatumName','horizontalDatumName','hwmTypeName','hwmQualityName','hwm_environment','waterbody','stillwater','verticalMethodName','hwm_label']:
    cn=collections.Counter(x[c] for x in recs); print(c,len(cn),cn.most_common(8))
ids=collections.Counter(x['hwm_id'] for x in recs); print('dup ids',[k for k,v in ids.items() if v>1])
# full-row duplicates
print('dup rows',len(recs)-len({tuple(x.values()) for x in recs}))
co=collections.Counter((x['latitude_dd'],x['longitude_dd']) for x in recs); print('dup coords',sum(1 for v in co.values() if v>1))
# bbox
lat=[num(x['latitude_dd']) for x in recs];lon=[num(x['longitude_dd']) for x in recs]
print(min(lat),max(lat),min(lon),max(lon))
# neg height, zero
print('neg h',[ (x['hwm_id'],x['height_above_gnd']) for x in recs if num(x['height_above_gnd']) is not None and num(x['height_above_gnd'])<0])
print('h zero',sum(1 for x in recs if num(x['height_above_gnd'])==0))
print('blank elev',[x['hwm_id'] for x in recs if not x['elev_ft'].strip()])
print('blank h',[x['hwm_id'] for x in recs if not x['height_above_gnd'].strip()])
print('dates',collections.Counter(x['flag_date'] for x in recs).most_common(10), collections.Counter(x['survey_date'] for x in recs).most_common(5))
# elev vs lat check: elev minus height = ground elev
print('big elev',sorted(((num(x['elev_ft']),x['hwm_id'],x['countyName']) for x in recs if num(x['elev_ft']) is not None))[-5:])
print('big h',sorted(((num(x['height_above_gnd']),x['hwm_id']) for x in recs if num(x['height_above_gnd']) is not None))[-5:])
# county vs sign
print('encoding odd', sum('�' in ''.join(x.values()) for x in recs))
out=[{'id':x['hwm_id'],'latitude':num(x['latitude_dd']),'longitude':num(x['longitude_dd']),'elev_ft_navd88':num(x['elev_ft']),'height_above_gnd_ft':num(x['height_above_gnd']),'site':x['siteDescription'].strip(),'site_no':x['site_no'],'county':x['countyName'],'hwm_type':x['hwmTypeName'],'quality':x['hwmQualityName'],'uncertainty_ft':num(x['uncertainty'])} for x in recs]
with open('outputs/agent_eval/T26/hwm_clean.csv','w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
