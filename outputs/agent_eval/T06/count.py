import json,collections
d=json.load(open('data/raw/wildfire_la/buildings_2023_with_dins.geojson'))
f=d['features']; P=[x['properties'] for x in f]
out={}
out['n']=len(P); out['exceeded']=d.get('exceededTransferLimit')
out['DAMAGE']=collections.Counter(repr(p['DAMAGE']) for p in P).most_common()
out['CODE']=collections.Counter(p['CODE'] for p in P).most_common()
out['STATUS']=collections.Counter(p['STATUS'] for p in P).most_common()
b=collections.Counter(p['BLD_ID'] for p in P); out['dup_bldid']=sum(1 for v in b.values() if v>1); out['null_bldid']=sum(1 for p in P if p['BLD_ID'] is None)
oid=len({p['OBJECTID'] for p in P}); out['uniq_oid']=oid
out['blank_or_ws']=sum(1 for p in P if isinstance(p['DAMAGE'],str) and p['DAMAGE'].strip()!=p['DAMAGE'])
out['null_geom']=sum(1 for x in f if not x.get('geometry'))
out['STRUCT_by_dmg_nonnull']=collections.Counter((p['STRUCTURET'] is not None) for p in P if p['DAMAGE'] is None).most_common()
json.dump(out,open('outputs/agent_eval/T06/counts.json','w'),indent=1)
print(json.dumps(out,indent=1))
