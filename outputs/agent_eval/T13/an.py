import csv, random, statistics as S, collections, json
R=list(csv.DictReader(open('points.csv')))
def f(x):
    try: return float(x)
    except: return None
by=collections.defaultdict(list)
for r in R: by[r['id'].split('_c')[0]].append(r)
marks=[g[0] for g in by.values() if g[0]['kind']=='mark']
print(len(marks), sum(1 for g in by.values() for r in g if r['kind']=='control'))
import re
print('interior',sum(r['interior']=='True' for r in marks))
def analyse(sel, label):
    out={}
    for var in ('sink','tpi','dem_m'):
        aucs=[];rk=[]; mk=[];ct=[]
        for g in by.values():
            m=g[0]
            if m['id'] not in sel: continue
            mv=f(m[var]); cs=[f(c[var]) for c in g[1:] if f(c[var]) is not None]
            if mv is None or not cs: continue
            # fraction of controls lower/less: for sink, higher=lower spot
            if var=='sink': a=sum(mv>c for c in cs)+0.5*sum(mv==c for c in cs)
            else: a=sum(mv<c for c in cs)+0.5*sum(mv==c for c in cs)
            aucs.append(a/len(cs)); mk.append(mv); ct+=cs
        n=len(aucs); mean=S.mean(aucs)
        # bootstrap over marks
        rng=random.Random(1); bs=sorted(S.mean(rng.choices(aucs,k=n)) for _ in range(2000))
        # sign test
        out[var]=dict(n=n,paired_auc=round(mean,3),ci=[round(bs[50],3),round(bs[1950],3)],median_mark=round(S.median(mk),3),median_ctrl=round(S.median(ct),3),mean_mark=round(S.mean(mk),3),mean_ctrl=round(S.mean(ct),3),
          share_mark_sink_gt015=round(sum(v>0.15 for v in mk)/n,3) if var=='sink' else None, share_ctrl_sink_gt015=round(sum(v>0.15 for v in ct)/len(ct),3) if var=='sink' else None,
          share_mark_tpi_neg=round(sum(v<0 for v in mk)/n,3) if var=='tpi' else None, share_ctrl_tpi_neg=round(sum(v<0 for v in ct)/len(ct),3) if var=='tpi' else None)
    print(label); print(json.dumps(out,indent=1)); return out
allm={m['id'] for m in marks}
res={}
res['all']=analyse(allm,'ALL')
res['noninterior']=analyse({m['id'] for m in marks if m['interior']!='True'},'NONINT')
res['good']=analyse({m['id'] for m in marks if m['quality'].startswith(('Good','Excellent'))},'GOOD+')
# depth relation
d=[(f(m['sink']),f(m['tpi']),f(m['depth_m'])) for m in marks if f(m['depth_m']) is not None and f(m['tpi']) is not None]
def rank(v): 
    o=sorted(range(len(v)),key=lambda i:v[i]); r=[0]*len(v)
    for k,i in enumerate(o): r[i]=k
    return r
def sp(a,b):
    ra,rb=rank(a),rank(b); ma,mb=S.mean(ra),S.mean(rb)
    return sum((x-ma)*(y-mb) for x,y in zip(ra,rb))/ (sum((x-ma)**2 for x in ra)**.5*sum((y-mb)**2 for y in rb)**.5)
print('n depth',len(d),'spearman sink-depth',sp([x[0] for x in d],[x[2] for x in d]),'tpi-depth',sp([x[1] for x in d],[x[2] for x in d]))
res['spearman']=dict(n=len(d),sink_depth=sp([x[0] for x in d],[x[2] for x in d]),tpi_depth=sp([x[1] for x in d],[x[2] for x in d]))
print('depth m median',S.median([x[2] for x in d]))
print('marks nan tpi',sum(f(m['tpi']) is None for m in marks), 'sites', len({m['id'] for m in marks}))
json.dump(res,open('stats.json','w'),indent=1)
