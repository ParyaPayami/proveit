"""Compare PlanArena's forecast with the soft-site rule on identical lots, from saved Score My Layer pairs.

Run after pro/proof_planarena.py: python3 -m proveit.compare_planarena
Writes outputs/proof_planarena_compare.json with:
- AUCs for both methods on the same lots, and a 95% confidence interval for their difference (DeLong's method for
  two AUCs on the same lots);
- the certificate comparison at several building-age cutoffs (how sensitive the result is to the timing filter);
- a check of the nearest-lot fallback: does each fallback match land on the record's own tax block?
"""

from __future__ import annotations

import bisect
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORECAST = ROOT / "data" / "planarena_forecast_2020.geojson"
CERTS = ROOT / "data" / "truth" / "nyc_certificates_of_occupancy"
SCORE = ROOT / "outputs" / "score"
OUT = ROOT / "outputs" / "proof_planarena_compare.json"
NEAR_M = 30


def _placements(scores, y):
    """DeLong placement values: for each positive, the share of negatives below it; for each negative, of positives above."""
    pos = sorted(s for s, o in zip(scores, y) if o)
    neg = sorted(s for s, o in zip(scores, y) if not o)

    def below(v, arr):
        lo, hi = bisect.bisect_left(arr, v), bisect.bisect_right(arr, v)
        return (lo + 0.5 * (hi - lo)) / len(arr)

    return [below(s, neg) for s, o in zip(scores, y) if o], [1 - below(s, pos) for s, o in zip(scores, y) if not o]


def _cov(x, z):
    mx, mz = sum(x) / len(x), sum(z) / len(z)
    return sum((i - mx) * (j - mz) for i, j in zip(x, z)) / (len(x) - 1)


def delong(a, b, y) -> dict:
    a10, a01 = _placements(a, y)
    b10, b01 = _placements(b, y)
    m, n = len(a10), len(a01)
    auc_a, auc_b = sum(a10) / m, sum(b10) / m
    var = ((_cov(a10, a10) + _cov(b10, b10) - 2 * _cov(a10, b10)) / m
           + (_cov(a01, a01) + _cov(b01, b01) - 2 * _cov(a01, b01)) / n)
    d, se = auc_a - auc_b, math.sqrt(var)
    return {"lots": m + n, "yes": m, "auc_forecast": round(auc_a, 3), "auc_rule": round(auc_b, 3),
            "difference": round(d, 3), "ci95": [round(d - 1.96 * se, 3), round(d + 1.96 * se, 3)]}


def compare(pairs: str, props: list[dict], cutoff: int | None = None, drop: set[str] = frozenset()) -> dict:
    """Forecast vs rule on lots that have a soft-site value (and, with cutoff, no building from that year or later)."""
    rows = list(csv.DictReader(open(SCORE / pairs / "pairs.csv")))
    assert len(rows) == len(props), "pairs.csv rows must follow the forecast layer's order"
    keep = [(float(r["pred"]), p["soft_site"], int(r["outcome"])) for r, p in zip(rows, props)
            if not r["excluded"] and p["soft_site"] is not None and p["bbl"] not in drop
            and (cutoff is None or (p["year_built_2020"] or 0) < cutoff)]
    return delong([k[0] for k in keep], [k[1] for k in keep], [k[2] for k in keep])


def _xy(lon, lat, kx=111320 * math.cos(math.radians(40.78)), ky=110540):
    return lon * kx, lat * ky


def _inside(p, ring):
    x, y, c = p[0], p[1], False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            c = not c
    return c


def _seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = 0 if dx == dy == 0 else max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def fallback_check(features: list[dict]) -> dict:
    """Records whose BBL is not a lot go to the nearest lot within NEAR_M; is that lot on the record's own tax block?"""
    lots = {f["properties"]["bbl"] for f in features}
    polys = []
    for f in features:
        g = f["geometry"]
        parts = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        rings = [[_xy(*pt[:2]) for pt in ring] for poly in parts for ring in poly]
        xs = [q[0] for r in rings for q in r]
        ys = [q[1] for r in rings for q in r]
        polys.append((f["properties"]["bbl"], rings, (min(xs), min(ys), max(xs), max(ys))))
    certs = max(CERTS.glob("*.json"), key=lambda q: q.stat().st_size)
    matches = []
    for r in json.loads(certs.read_text())["features"]:
        bbl = str(r["properties"].get("bbl") or "").split(".")[0]
        if bbl in lots:
            continue
        p = _xy(*r["geometry"]["coordinates"])
        best = (math.inf, None)
        for lot, rings, (x0, y0, x1, y1) in polys:
            if not (x0 - NEAR_M <= p[0] <= x1 + NEAR_M and y0 - NEAR_M <= p[1] <= y1 + NEAR_M):
                continue
            d = 0 if any(_inside(p, ring) for ring in rings) else min(
                _seg(p, ring[i], ring[i + 1]) for ring in rings for i in range(len(ring) - 1))
            best = min(best, (d, lot))
        if best[1] is not None and best[0] <= NEAR_M:
            matches.append((bbl, best[1]))
    other = sorted({lot for bbl, lot in matches if bbl and bbl[:6] != lot[:6]})
    by_number = {str(r["properties"].get("bbl") or "").split(".")[0]
                 for r in json.loads(certs.read_text())["features"]}
    return {"records": len(matches), "lots": len({lot for _, lot in matches}),
            "same_tax_block": sum(1 for bbl, lot in matches if bbl and bbl[:6] == lot[:6]),
            "no_bbl": sum(1 for bbl, _ in matches if not bbl),
            "other_block": sum(1 for bbl, lot in matches if bbl and bbl[:6] != lot[:6]),
            "other_block_lots_only_matched_this_way": sorted(set(other) - by_number)}


def main() -> None:
    features = json.loads(FORECAST.read_text())["features"]
    props = [f["properties"] for f in features]
    check = fallback_check(features)
    doubtful = set(check["other_block_lots_only_matched_this_way"])
    out = {
        "method": "AUCs on lots scored by both methods; 95% CI for the difference by DeLong's method (paired AUCs).",
        "permits": compare("planarena_started_planarena_model", props),
        "certificates_built_before_2015": compare("planarena_completed_all_lots", props, 2015),
        "timing_cutoffs": {str(c): compare("planarena_completed_all_lots", props, c) for c in (2000, 2010, 2015, 2018)},
        "nearest_lot_check": check,
        "certificates_without_doubtful_matches": {str(c): compare("planarena_completed_all_lots", props, c, doubtful)
                                                 for c in (2000, 2015)},
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
