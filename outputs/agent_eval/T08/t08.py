"""Hand-compute Spearman r for 5 rows (exact fractions) and compare with proveit.score. Test vectors are synthetic, for verifying the formula only."""
import sys, json
from fractions import Fraction as F
sys.path.insert(0, "/Users/user/Desktop/Esri/proveit")
from proveit import score

def hand_ranks(v):  # average ranks for ties
    return [F(sum(1 for b in v if b < a)) + F(sum(1 for b in v if b == a) + 1, 2) for a in v]

def hand_spearman(x, y):
    rx, ry = hand_ranks(x), hand_ranks(y)
    mx, my = sum(rx)/len(rx), sum(ry)/len(ry)
    sxy = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
    sxx = sum((a-mx)**2 for a in rx); syy = sum((b-my)**2 for b in ry)
    return float(sxy) / float((sxx*syy)) ** 0.5, rx, ry

res = {}
# Case A: no ties. d = rank differences; rho = 1 - 6*sum(d^2)/(n(n^2-1))
xa, ya = [10, 20, 30, 40, 50], [3, 1, 4, 5, 2]
rx, ry = [1,2,3,4,5], [3,1,4,5,2]
d2 = sum((a-b)**2 for a, b in zip(rx, ry))
rho_shortcut = 1 - 6*d2/(5*24)
rho_h, _, _ = hand_spearman(xa, ya)
res["A_no_ties"] = {"x": xa, "y": ya, "sum_d2": d2, "shortcut": rho_shortcut, "hand_pearson_on_ranks": rho_h, "proveit": score.spearman(xa, ya)}
# Case B: ties in both
xb, yb = [1, 2, 2, 4, 5], [5, 3, 3, 3, 1]
rho_hb, rxb, ryb = hand_spearman(xb, yb)
shortcut_b = 1 - 6*sum((a-b)**2 for a, b in zip(rxb, ryb))/(5*24)
res["B_ties"] = {"x": xb, "y": yb, "ranks_x": [float(r) for r in rxb], "ranks_y": [float(r) for r in ryb],
                 "hand": rho_hb, "shortcut_formula_on_tied_ranks(wrong with ties)": float(shortcut_b), "proveit": score.spearman(xb, yb)}
# Case C: through score_pairs (continuous, as Score My Layer does): rounding, higher_means=less, min_records
pairs = [{"id": i, "pred": p, "outcome": o, "n": 2} for i, (p, o) in enumerate(zip(xa, ya))]
def card(hm):
    meta = {"name": "T08", "config": {"higher_means": hm, "prediction_date": "2025-01-01", "start": "2025-01-01"}, "test": "continuous",
            "source": {"id": "x", "name": "x", "outcome": {"describes": "x"}, "traps": []}, "truth": {}, "pairing": {}}
    return score.score_pairs(meta, pairs)
res["C_score_pairs_more"] = card("more")["metrics"]
res["C_score_pairs_less"] = card("less")["metrics"]
res["C_scored_n_and_traps"] = [(t["id"], t["status"]) for t in card("more")["traps"]]
res["C_hand_negated"] = round(-rho_h, 3)
print(json.dumps(res, indent=1, default=str))
json.dump(res, open("/Users/user/Desktop/Esri/proveit/outputs/agent_eval/T08/results.json", "w"), indent=1, default=str)
