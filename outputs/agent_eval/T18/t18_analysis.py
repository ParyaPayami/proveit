import csv, random, math, json, statistics as st
from collections import Counter
D=[r for r in csv.DictReader(open('buildings_T18.csv'))]
F=["nn_distance_m","neighbors_50m","slope_deg","open_land_distance_m"]
DIR={"nn_distance_m":-1,"neighbors_50m":1,"slope_deg":1,"open_land_distance_m":-1}  # +1 = higher is riskier
DEST={"Destroyed (>50%)"}; NOT={"No Damage","Affected (1-9%)","Minor (10-25%)","Major (26-50%)"}
out={}
for r in D:
    r['y']=1 if r['damage'] in DEST else 0 if r['damage'] in NOT else None
    for f in F: r[f]=float(r[f]) if r[f]!='' else None
cnt={}
for fire in ("eaton","palisades"):
    rs=[r for r in D if r['fire']==fire]
    c=Counter('destroyed' if r['y']==1 else 'not_destroyed' if r['y']==0 else ('no_record' if r['damage']=='' else 'inaccessible') for r in rs)
    cnt[fire]=dict(c,total=len(rs))
print(cnt)
def auc(pos,neg):
    # P(score_pos > score_neg), ties 0.5, via rank
    allv=sorted([(v,1) for v in pos]+[(v,0) for v in neg]); n=len(allv); ranks=[0]*n; i=0; sr=0
    while i<n:
        j=i
        while j+1<n and allv[j+1][0]==allv[i][0]: j+=1
        rk=(i+j)/2+1
        for k in range(i,j+1):
            if allv[k][1]==1: sr+=rk
        i=j+1
    return (sr-len(pos)*(len(pos)+1)/2)/(len(pos)*len(neg))
def aucs(rs):
    res={}
    for f in F:
        ok=[r for r in rs if r['y'] is not None and r[f] is not None]
        p=[DIR[f]*r[f] for r in ok if r['y']==1]; n=[DIR[f]*r[f] for r in ok if r['y']==0]
        res[f]=(auc(p,n),len(ok))
    return res
random.seed(1)
data={fire:[r for r in D if r['fire']==fire and r['y'] is not None] for fire in ("eaton","palisades")}
res={}
for fire,rs in data.items():
    res[fire]=aucs(rs)
# bootstrap difference
B=200
diffs={f:[] for f in F}; cis={fire:{f:[] for f in F} for fire in data}
for b in range(B):
    bs={fire:aucs([random.choice(rs) for _ in rs]) for fire,rs in data.items()}
    for f in F:
        diffs[f].append(bs['eaton'][f][0]-bs['palisades'][f][0])
        for fire in data: cis[fire][f].append(bs[fire][f][0])
def q(a,p): a=sorted(a); return a[int(p*(len(a)-1))]
summary={}
for f in F:
    summary[f]={ 'auc_eaton':round(res['eaton'][f][0],3),'ci_eaton':[round(q(cis['eaton'][f],.025),3),round(q(cis['eaton'][f],.975),3)],
      'auc_palisades':round(res['palisades'][f][0],3),'ci_pal':[round(q(cis['palisades'][f],.025),3),round(q(cis['palisades'][f],.975),3)],
      'diff':round(res['eaton'][f][0]-res['palisades'][f][0],3),'diff_ci':[round(q(diffs[f],.025),3),round(q(diffs[f],.975),3)],'n_e':res['eaton'][f][1],'n_p':res['palisades'][f][1]}
    print(f,summary[f])
# medians by outcome
med={}
for fire,rs in data.items():
    med[fire]={f:{'destroyed':round(st.median([r[f] for r in rs if r['y']==1 and r[f] is not None]),2),'not_destroyed':round(st.median([r[f] for r in rs if r['y']==0 and r[f] is not None]),2)} for f in F}
    print(fire,'destroyed rate',round(sum(r['y'] for r in rs)/len(rs),3),med[fire])
# logistic regression (standardized), Newton/IRLS in pure python
def solve(A,b):
    n=len(b); M=[A[i][:]+[b[i]] for i in range(n)]
    for i in range(n):
        p=max(range(i,n),key=lambda r:abs(M[r][i])); M[i],M[p]=M[p],M[i]
        for r in range(n):
            if r!=i:
                fct=M[r][i]/M[i][i]
                for c in range(i,n+1): M[r][c]-=fct*M[i][c]
    return [M[i][n]/M[i][i] for i in range(n)]
def fit(X,y,it=25):
    k=len(X[0]); w=[0.0]*k
    for _ in range(it):
        g=[0.0]*k; H=[[0.0]*k for _ in range(k)]
        for x,t in zip(X,y):
            z=sum(a*b for a,b in zip(w,x)); p=1/(1+math.exp(-max(-30,min(30,z))))
            for i in range(k):
                g[i]+=(t-p)*x[i]
                for j in range(k): H[i][j]+=p*(1-p)*x[i]*x[j]
        d=solve(H,g); w=[a+b for a,b in zip(w,d)]
        if max(abs(v) for v in d)<1e-7: break
    # SE
    k=len(w);H=[[0.0]*k for _ in range(k)]
    for x in X:
        z=sum(a*b for a,b in zip(w,x)); p=1/(1+math.exp(-z))
        for i in range(k):
            for j in range(k): H[i][j]+=p*(1-p)*x[i]*x[j]
    se=[math.sqrt(solve(H,[1.0 if i==j else 0.0 for i in range(k)])[j]) for j in range(k)]
    return w,se
def design(rs,mu,sd):
    return [[1.0]+[DIR[f]*(r[f]-mu[f])/sd[f] for f in F] for r in rs]
mods={}
cc={fire:[r for r in rs if all(r[f] is not None for f in F)] for fire,rs in data.items()}
for fire,rs in cc.items():
    mu={f:st.mean(r[f] for r in rs) for f in F}; sd={f:st.pstdev([r[f] for r in rs]) for f in F}
    X=design(rs,mu,sd); y=[r['y'] for r in rs]; w,se=fit(X,y)
    mods[fire]=dict(mu=mu,sd=sd,w=w,se=se,X=X,y=y)
    print(fire,'n',len(rs),'coef(risk-direction, per SD)',[round(a,3) for a in w],'se',[round(a,3) for a in se])
# pooled model with fire interactions: test coefficient differences via z
lr={}
for i,f in enumerate(F,1):
    a,b=mods['eaton'],mods['palisades']
    z=(a['w'][i]-b['w'][i])/math.sqrt(a['se'][i]**2+b['se'][i]**2)
    lr[f]={'coef_eaton':round(a['w'][i],3),'se_e':round(a['se'][i],3),'coef_pal':round(b['w'][i],3),'se_p':round(b['se'][i],3),'z_diff':round(z,2),'OR_eaton':round(math.exp(a['w'][i]),3),'OR_pal':round(math.exp(b['w'][i]),3)}
    print(f,lr[f])
# transfer: score fire B with fire A's raw-unit model
def score(m_from,rs):
    mf=m_from; xs=[[1.0]+[DIR[f]*(r[f]-mf['mu'][f])/mf['sd'][f] for f in F] for r in rs]
    return [sum(a*b for a,b in zip(mf['w'][1:],x[1:])) for x in xs]
tr={}
for a,b in (('eaton','palisades'),('palisades','eaton'),('eaton','eaton'),('palisades','palisades')):
    s=score(mods[a],cc[b]); y=[r['y'] for r in cc[b]]
    tr[f'{a}->{b}']=round(auc([v for v,t in zip(s,y) if t==1],[v for v,t in zip(s,y) if t==0]),3)
print(tr)
# edge sensitivity for open_land / nn
json.dump(dict(counts=cnt,univariate=summary,medians=med,logit=lr,transfer_auc=tr),open('t18_results.json','w'),indent=1)
