import csv, json, math, random
FT=0.3048
R=list(csv.DictReader(open('points.csv')))
def f(x): return float(x) if x not in ('',None) else None
M=[r for r in R if r['kind']=='mark']; C=[r for r in R if r['kind']=='control']
def rank(v):
    o=sorted(range(len(v)),key=lambda i:v[i]); rk=[0]*len(v); i=0
    while i<len(v):
        j=i
        while j+1<len(v) and v[o[j+1]]==v[o[i]]: j+=1
        for k in range(i,j+1): rk[o[k]]=(i+j)/2+1
        i=j+1
    return rk
def pear(a,b):
    n=len(a); ma=sum(a)/n; mb=sum(b)/n
    sa=math.sqrt(sum((x-ma)**2 for x in a)); sb=math.sqrt(sum((x-mb)**2 for x in b))
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/(sa*sb) if sa and sb else float('nan')
def spear(a,b): return pear(rank(a),rank(b))
def boot(a,b,n=2000):
    rng=random.Random(1); idx=range(len(a)); v=[]
    for _ in range(n):
        s=[rng.choice(idx) for _ in idx]; v.append(spear([a[i] for i in s],[b[i] for i in s]))
    v=sorted(x for x in v if x==x); return round(v[int(.025*len(v))],2),round(v[int(.975*len(v))],2)
def auc(pos,neg):
    allv=pos+neg; rk=rank(allv); r=sum(rk[:len(pos)]); n1,n2=len(pos),len(neg)
    return (r-n1*(n1+1)/2)/(n1*n2)
out={}
print(len(M),len(C))
ok=[r for r in M if r['h_ft']!='' and r['sink0']!='']
print('marks with depth+sink',len(ok), 'missing depth',sum(r['h_ft']=='' for r in M),'no sink',sum(r['sink0']=='' for r in M))
# DEM ground check
d=[(f(r['elev_ft'])-f(r['h_ft']))*FT-f(r['dem_m']) for r in ok if r['elev_ft'] and r['dem_m']]
d.sort(); print('surveyed ground - DEM (m): median',d[len(d)//2],'p10',d[len(d)//10],'p90',d[9*len(d)//10],'n',len(d))
out['ground_minus_dem_m']={'median':round(d[len(d)//2],2),'p10':round(d[len(d)//10],2),'p90':round(d[9*len(d)//10],2),'n':len(d)}
def sets():
    yield 'all',ok
    yield 'excl_strict_interior',[r for r in ok if r['strict']!='True']
    yield 'excl_loose_interior(garage etc)',[r for r in ok if r['loose']!='True']
    yield 'excl_strict_and_edge<100m',[r for r in ok if r['strict']!='True' and f(r['edge_m'])>=100]
    yield 'excl_strict_stillwater0',[r for r in ok if r['strict']!='True' and r['stillwater']=='0']
    yield 'excl_strict_depth>0',[r for r in ok if r['strict']!='True' and f(r['h_ft'])>0]
    yield 'excl_strict_Good/Excellent',[r for r in ok if r['strict']!='True' and not r['quality'].startswith(('Poor','Fair'))]
res={}
for name,S in sets():
    for col in ['sink0','sink5','sink10','sink20']:
        a=[f(r[col]) for r in S]; b=[f(r['h_ft'])*FT for r in S]
        res[(name,col)]=(len(S),round(spear(a,b),3),round(pear(a,b),3),boot(a,b) if name in('all','excl_strict_interior') else None, sum(x>0.15 for x in a), sum(x>0 for x in a))
        print(name,col,res[(name,col)])
S=[r for r in ok if r['strict']!='True']
for col in ['sink0','sink5','sink10','sink20']:
    pos=[f(r[col]) for r in S]; neg=[f(r[col]) for r in C if r[col]!='']
    print(col,'AUC marks vs controls',round(auc(pos,neg),3),'median marks',sorted(pos)[len(pos)//2],'controls',sorted(neg)[len(neg)//2],'frac>0.15 marks',sum(x>0.15 for x in pos)/len(pos),'ctrl',sum(x>0.15 for x in neg)/len(neg))
a=[f(r['sink0']) for r in S]; print('sink0 quantiles',sorted(a)[::len(a)//10], 'n zero',sum(x==0 for x in a),len(a))
# binned
for lo,hi in [(0,0.15),(0.15,10)]:
    g=[f(r['h_ft'])*FT for r in S if lo<=f(r['sink0'])<hi]; print('sink0 bin',lo,hi,len(g),sum(g)/len(g) if g else None)
g=[f(r['h_ft'])*FT for r in S if f(r['sink10'])>=0.15]; h=[f(r['h_ft'])*FT for r in S if f(r['sink10'])<0.15]
print('depth m, sink10>=0.15:',len(g),sum(g)/len(g),' <0.15:',len(h),sum(h)/len(h))
# regression slope all
a=[f(r['sink10']) for r in S]; b=[f(r['h_ft'])*FT for r in S]; n=len(a); ma=sum(a)/n; mb=sum(b)/n
sl=sum((x-ma)*(y-mb) for x,y in zip(a,b))/sum((x-ma)**2 for x in a); print('slope',sl,'r2',pear(a,b)**2)
print('modeled sink vs observed depth magnitude: mean sink10',ma,'mean obs',mb)
# top worst
for r in sorted(S,key=lambda r:-f(r['h_ft']))[:6]: print(r['id'],r['h_ft'],r['sink0'],r['sink10'],r['desc'])
# by county
for c in set(r['county'] for r in S):
    T=[r for r in S if r['county']==c]
    print(c,len(T),round(spear([f(r['sink10']) for r in T],[f(r['h_ft']) for r in T]),2) if len(T)>4 else None)
json.dump({str(k):v for k,v in res.items()},open('stats.json','w'),indent=1)
print(out)
