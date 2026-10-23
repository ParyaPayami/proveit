import csv, sys, json, statistics, random
sys.path.insert(0, "/Users/user/Desktop/Esri/proveit")
from proveit.score import auc, spearman, pearson
rows = list(csv.DictReader(open("/Users/user/Desktop/Esri/proveit/outputs/agent_eval/T15/points.csv")))
f = lambda r, k: float(r[k]) if r[k] != "" else None
M = [r for r in rows if r["kind"] == "mark"]; C = [r for r in rows if r["kind"] == "control"]
print("marks", len(M), "controls", len(C), "interior", sum(r["interior"] == "True" for r in M), "sites", len({r["site"] for r in M}))
feats = {"sink": ("sink_depth_m", 1), "low_tpi25": ("tpi25", -1), "low_tpi51": ("tpi51", -1), "low_tpi101": ("tpi101", -1), "low_tpi51_arcpy": ("tpi51_arcpy", -1)}
def det(Ms, Cs, k, s):
    Ms = [r for r in Ms if f(r, k) is not None]; Cs = [r for r in Cs if f(r, k) is not None]
    pos = [s * f(r, k) for r in Ms]; neg = [s * f(r, k) for r in Cs]
    sites = {}
    for r in Ms: sites.setdefault(r["site"], ([], []))[0].append(s * f(r, k))
    for r in Cs:
        if r["site"] in sites: sites[r["site"]][1].append(s * f(r, k))
    sp = [statistics.median(p) for p, n in sites.values() if n]; sn = [statistics.median(n) for p, n in sites.values() if n]
    # paired: each mark vs its own controls (control id prefix)
    ctl = {}
    for r in Cs: ctl.setdefault(r["id"].rsplit("_c", 1)[0], []).append(s * f(r, k))
    wins = [] 
    for r in Ms:
        c = ctl.get(r["id"])
        if c: wins.append(sum(s * f(r, k) > x for x in c) / len(c) + 0.5 * sum(s * f(r, k) == x for x in c) / len(c))
    # bootstrap CI over sites for site AUC
    rng = random.Random(1); idx = list(range(len(sp))); b = []
    for _ in range(500):
        i = [rng.choice(idx) for _ in idx]; b.append(auc([sp[j] for j in i], [sn[j] for j in i]))
    b.sort()
    return {"n_marks": len(pos), "n_ctl": len(neg), "auc_points": round(auc(pos, neg), 3), "auc_sites": round(auc(sp, sn), 3), "sites": len(sp),
            "site_auc_ci95": [round(b[12], 3), round(b[487], 3)], "mean_within_mark_percentile": round(statistics.fmean(wins), 3)}
res = {}
for name, sub in [("all", (M, C)), ("street_only", ([r for r in M if r["interior"] == "False"], C)),
                  ("interior_only", ([r for r in M if r["interior"] == "True"], C)),
                  ("edge>=60m", ([r for r in M if f(r, "edge_m") >= 60], [r for r in C if f(r, "edge_m") >= 60]))]:
    res[name] = {n: det(sub[0], sub[1], k, s) for n, (k, s) in feats.items()}
    print(name); [print("  ", n, v) for n, v in res[name].items()]
# thresholds / shares
def share(rs, k, fn): 
    v = [f(r, k) for r in rs if f(r, k) is not None]; return round(sum(fn(x) for x in v) / len(v), 3)
sh = {}
for nm, rs in [("marks", M), ("controls", C)]:
    sh[nm] = {"sink>=0.15": share(rs, "sink_depth_m", lambda x: x >= .15), "tpi51<=-0.5": share(rs, "tpi51", lambda x: x <= -.5),
              "tpi51<0": share(rs, "tpi51", lambda x: x < 0), "tpi51<=-1": share(rs, "tpi51", lambda x: x <= -1),
              "median_tpi51": round(statistics.median([f(r, "tpi51") for r in rs if f(r, "tpi51") is not None]), 3),
              "median_sink": round(statistics.median([f(r, "sink_depth_m") for r in rs if f(r, "sink_depth_m") is not None]), 3)}
print(sh)
# agreement
def pair(rs):
    rs = [r for r in rs if f(r, "sink_depth_m") is not None and f(r, "tpi51") is not None]
    a = [f(r, "sink_depth_m") for r in rs]; b = [f(r, "tpi51") for r in rs]
    both = sum(x >= .15 and y <= -.5 for x, y in zip(a, b)); sk = sum(x >= .15 for x in a); lw = sum(y <= -.5 for y in b)
    agree = sum((x >= .15) == (y <= -.5) for x, y in zip(a, b))
    return {"n": len(a), "spearman_sink_vs_tpi": round(spearman(a, b), 3), "sink_cells": sk, "tpi_low_cells": lw, "both": both,
            "share_of_sink_that_is_tpi_low": round(both / sk, 3) if sk else None, "share_of_tpi_low_that_is_sink": round(both / lw, 3) if lw else None,
            "classification_agreement": round(agree / len(a), 3)}
ag = {"all": pair(rows), "marks": pair(M), "controls": pair(C)}
print(ag)
# depth relation
st = [r for r in M if r["interior"] == "False" and f(r, "obs_depth_m") is not None]
dep = {}
for k in ["sink_depth_m", "tpi51"]:
    x = [f(r, k) for r in st if f(r, k) is not None]; y = [f(r, "obs_depth_m") for r in st if f(r, k) is not None]
    dep[k] = {"n": len(x), "spearman": round(spearman(x, y), 3)}
print(dep)
# top-decile enrichment
alls = [r for r in rows if f(r, "sink_depth_m") is not None and f(r, "tpi51") is not None]
json.dump({"detect": res, "shares": sh, "agreement": ag, "depth": dep}, open("/Users/user/Desktop/Esri/proveit/outputs/agent_eval/T15/results.json", "w"), indent=1)
