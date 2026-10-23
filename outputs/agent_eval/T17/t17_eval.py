import csv, json, random, statistics
rows=list(csv.DictReader(open('buildings.csv')))
F={"nn_distance_m":-1,"neighbors_50m":1,"slope_deg":1,"open_land_distance_m":-1}  # sign: risk direction
def auc(sc,y):
    pairs=sorted(zip(sc,y)); n=len(pairs); r=[0]*n; i=0
    while i<n:
        j=i
        while j<n and pairs[j][0]==pairs[i][0]: j+=1
        for k in range(i,j): r[k]=(i+j+1)/2
        i=j
    pos=sum(y); neg=n-pos
    return (sum(r[k] for k in range(n) if pairs[k][1]==1)-pos*(pos+1)/2)/(pos*neg)
def get(sub, feats):
    out=[]
    for r in sub:
        if r['destroyed']=='' : continue
        v=[r[f] for f in feats]
        if any(x=='' for x in v): continue
        out.append((int(r['destroyed']),[float(x) for x in v]))
    return out
res={}
for name,sub in [('all',rows),('eaton',[r for r in rows if r['fire']=='eaton']),('palisades',[r for r in rows if r['fire']=='palisades'])]:
    d={}
    lab=[r for r in sub if r['destroyed']!='']
    d['n_labelled']=len(lab); d['destroyed_share']=round(sum(int(r['destroyed']) for r in lab)/len(lab),4)
    for f,s in F.items():
        g=get(sub,[f]); d[f]={'n':len(g),'auc':round(auc([s*x[1][0] for x in g],[x[0] for x in g]),4),
          'missing':len(lab)-len(g)}
    # composite: mean of percentile ranks (fixed direction, equal weights, not fitted)
    g=get(sub,list(F))
    cols=list(zip(*[x[1] for x in g]))
    def pr(c,s):
        o=sorted(range(len(c)),key=lambda i:s*c[i]); rk=[0]*len(c)
        for k,i in enumerate(o): rk[i]=k/(len(c)-1)
        return rk
    prs=[pr(c,s) for c,s in zip(cols,F.values())]
    comp=[sum(p[i] for p in prs)/4 for i in range(len(g))]
    y=[x[0] for x in g]
    d['composite']={'n':len(g),'auc':round(auc(comp,y),4)}
    # bootstrap CI for composite
    random.seed(1); bs=[]
    for _ in range(100):
        idx=[random.randrange(len(g)) for _ in g]; bs.append(auc([comp[i] for i in idx],[y[i] for i in idx]))
    bs.sort(); d['composite']['boot95']=[round(bs[2],4),round(bs[97],4)]
    # top-decile precision
    o=sorted(range(len(g)),key=lambda i:-comp[i]); k=len(g)//10
    d['composite']['destroyed_share_top_decile']=round(sum(y[i] for i in o[:k])/k,4)
    d['composite']['destroyed_share_bottom_decile']=round(sum(y[i] for i in o[-k:])/k,4)
    # medians
    d['medians']={f:{'destroyed':round(statistics.median(x[1][j] for x in g if x[0]==1),2),'survived':round(statistics.median(x[1][j] for x in g if x[0]==0),2)} for j,f in enumerate(F)}
    res[name]=d
# inspected vs not inspected by features (selection check)
insp={}
for lab,cond in [('inspected',lambda r:r['destroyed']!=''),('no_record',lambda r:r['damage']=='')]:
    s=[r for r in rows if cond(r)]
    insp[lab]={f:round(statistics.median(float(r[f]) for r in s if r[f]!=''),2) for f in F}; insp[lab]['n']=len(s)
res['inspected_vs_no_record_medians']=insp
# small footprints (sheds) share
small=[r for r in rows if r['destroyed']!='' and float(r['area_m2'])<30]
res['n_labelled_footprints_lt_30m2']=len(small)
# area-only AUC
g=[(int(r['destroyed']),float(r['area_m2'])) for r in rows if r['destroyed']!='']
res['area_auc_bigger_destroyed']=round(auc([a for _,a in g],[y for y,_ in g]),4)
# missing counts
res['labelled_missing_slope']=sum(1 for r in rows if r['destroyed']!='' and r['slope_deg']=='')
res['labelled_missing_open']=sum(1 for r in rows if r['destroyed']!='' and r['open_land_distance_m']=='')
res['labelled_open_land_not_null']=sum(1 for r in rows if r['destroyed']!='' and r['open_land_distance_m']!='')
json.dump(res,open('metrics.json','w'),indent=1); print(json.dumps(res,indent=1))
