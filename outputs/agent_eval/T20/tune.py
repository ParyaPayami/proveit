"""Tune feature weights for the wildfire exposure score; honest out-of-sample evaluation. Stdlib only."""
import csv, json, random, itertools
from pathlib import Path
D = Path(__file__).parent
F = ["nn_distance_m", "neighbors_50m", "slope_deg", "open_land_distance_m"]
SIGN = {"nn_distance_m": -1, "neighbors_50m": 1, "slope_deg": 1, "open_land_distance_m": -1}  # fixed by case file

def auc(scores, y):
    idx = sorted(range(len(y)), key=lambda i: scores[i])
    ranks = [0.0]*len(y); i = 0
    while i < len(idx):
        j = i
        while j+1 < len(idx) and scores[idx[j+1]] == scores[idx[i]]: j += 1
        r = (i+j)/2+1
        for k in range(i, j+1): ranks[idx[k]] = r
        i = j+1
    n1 = sum(y); n0 = len(y)-n1
    return (sum(r for r, v in zip(ranks, y) if v) - n1*(n1+1)/2)/(n1*n0)

rows = []
for r in csv.DictReader(open(D/"features.csv")):
    if r["destroyed"] == "": continue
    if any(r[f] == "" for f in F): continue
    rows.append(r)
allrows = list(csv.DictReader(open(D/"features.csv")))
print("rows total", len(allrows), "scored", len(rows))

def prank(vals):  # percentile rank 0..1 (ties averaged)
    idx = sorted(range(len(vals)), key=lambda i: vals[i]); out = [0.0]*len(vals); i = 0
    while i < len(idx):
        j = i
        while j+1 < len(idx) and vals[idx[j+1]] == vals[idx[i]]: j += 1
        for k in range(i, j+1): out[idx[k]] = ((i+j)/2)/(len(vals)-1)
        i = j+1
    return out

def build(sub):
    X = {f: [SIGN[f]*float(r[f]) for r in sub] for f in F}
    return {f: prank(X[f]) for f in F}   # higher = riskier
def y_of(sub): return [int(r["destroyed"]) for r in sub]

# weight grid on simplex, step 0.1 (non-negative, sum 1)
grid = [w for w in itertools.product(range(0, 11), repeat=4) if sum(w) == 10]
def comb(R, w): return [sum(w[k]*R[F[k]][i] for k in range(4)) for i in range(len(R[F[0]]))]

def best(sub):
    R = build(sub); y = y_of(sub)
    res = sorted(((auc(comb(R, w), y), w) for w in grid), reverse=True)
    return res[0], R, y

# Percentile ranks computed within each subset; to apply weights to a different set we rank within that set (same scheme).
out = {"n_scored": len(rows)}
y_all = y_of(rows)
out["n_destroyed"] = sum(y_all); out["base_rate"] = round(sum(y_all)/len(y_all), 4)
R_all = build(rows)
out["single_feature_auc_all"] = {f: round(auc(R_all[f], y_all), 4) for f in F}
out["equal_weight_auc_all"] = round(auc(comb(R_all, (1,1,1,1)), y_all), 4)
(b_auc, b_w), _, _ = best(rows)
out["in_sample_best"] = {"weights": [x/10 for x in b_w], "auc": round(b_auc, 4)}

# Out-of-sample: tune on one fire, test on the other
cross = {}
for tr, te in (("eaton", "palisades"), ("palisades", "eaton")):
    A = [r for r in rows if r["fire"] == tr]; B = [r for r in rows if r["fire"] == te]
    (a, w), _, _ = best(A)
    RB = build(B); yb = y_of(B)
    cross[f"train_{tr}_test_{te}"] = {"n_train": len(A), "n_test": len(B), "weights": [x/10 for x in w], "train_auc": round(a, 4),
        "test_auc": round(auc(comb(RB, w), yb), 4), "test_equal_weight_auc": round(auc(comb(RB, (1,1,1,1)), yb), 4)}
out["cross_fire"] = cross

# Random 50/50 split by spatial-ish key? no coordinates in csv; use 5-fold random CV, repeated
random.seed(20)
cv = []; eq = []
for rep in range(3):
    idx = list(range(len(rows))); random.shuffle(idx)
    for k in range(5):
        te = set(idx[k::5]); A = [rows[i] for i in idx if i not in te]; B = [rows[i] for i in te]
        (a, w), _, _ = best(A)
        RB = build(B); yb = y_of(B)
        cv.append(auc(comb(RB, w), yb)); eq.append(auc(comb(RB, (1,1,1,1)), yb))
out["random_5fold_cv_mean_auc_tuned"] = round(sum(cv)/len(cv), 4)
out["random_5fold_cv_mean_auc_equal"] = round(sum(eq)/len(eq), 4)
# per fire in-sample best
for fire in ("eaton", "palisades"):
    S = [r for r in rows if r["fire"] == fire]; (a, w), _, _ = best(S)
    out[f"in_sample_best_{fire}"] = {"n": len(S), "weights": [x/10 for x in w], "auc": round(a, 4)}
json.dump(out, open(D/"tune_results.json", "w"), indent=1)
print(json.dumps(out, indent=1))
