"""Score a case's outputs against its real-world answer key.

Kept separate from the analysis code (and free of arcpy) so that whoever, or
whatever, wrote the analysis does not also grade it.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]


def pearson(x: list[float], y: list[float]) -> float:
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sx = math.sqrt(sum((a - mx) ** 2 for a in x))
    sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sxy / (sx * sy) if sx and sy else float("nan")


def ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=v.__getitem__)
    r = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(x: list[float], y: list[float]) -> float:
    return pearson(ranks(x), ranks(y))


def agreement(model: list[float], observed: list[float], tolerance: float) -> dict:
    err = [o - m for m, o in zip(model, observed)]
    return {
        "n": len(model),
        "pearson_r": round(pearson(model, observed), 3),
        "spearman_r": round(spearman(model, observed), 3),
        "median_bias_min": round(statistics.median(err), 2),
        "mae_min": round(statistics.fmean(abs(e) for e in err), 2),
        "share_within_tolerance": round(sum(abs(e) <= tolerance for e in err) / len(err), 3),
        # Descriptive only: the bias is estimated on the same areas it is then removed from.
        "share_within_tolerance_after_bias_in_sample": round(
            sum(abs(e - statistics.median(err)) <= tolerance for e in err) / len(err), 3
        ),
        # Out of sample: each area is corrected with the median bias of all the other areas.
        "share_within_tolerance_after_loo_bias": round(
            sum(abs(e - statistics.median(err[:i] + err[i + 1:])) <= tolerance for i, e in enumerate(err)) / len(err), 3
        ) if len(err) > 1 else float("nan"),
    }


def evaluate_traps(case: dict, summary: dict) -> list[dict]:
    """Each trap's `detect` is a small expression over the run summary."""
    out = []
    for trap in case["traps"]:
        try:
            caught = bool(eval(trap["detect"], {"__builtins__": {}}, dict(summary)))
        except Exception as exc:  # missing evidence counts as not caught
            caught, trap = False, trap | {"error": str(exc)}
        out.append({"id": trap["id"], "caught": caught, "check": trap["check"]})
    return out


def score_fire_ems(case: dict, out_dir: Path) -> dict:
    key = case["answer_key"]
    rows = list(csv.DictReader(open(out_dir / "results_by_zip.csv", encoding="utf-8")))
    summary = json.loads((out_dir / "run_summary.json").read_text())
    usable, excluded = [], []
    for r in rows:
        if r["model_median_min"] == "" or r["obs_travel_min"] == "":
            excluded.append({"modzcta": r["modzcta"], "reason": "no model" if r["model_median_min"] == "" else "no observations"})
        elif int(r["obs_incidents"]) < key["min_incidents"]:
            excluded.append({"modzcta": r["modzcta"], "reason": f"fewer than {key['min_incidents']} incidents"})
        else:
            usable.append(r)
    model = [float(r["model_median_min"]) for r in usable]
    travel = [float(r["obs_travel_min"]) for r in usable]
    response = [float(r["obs_response_min"]) for r in usable]
    tol = key["tolerance_minutes"]
    worst = sorted(usable, key=lambda r: -abs(float(r["obs_travel_min"]) - float(r["model_median_min"])))[:5]
    return {
        "case": case["id"],
        "against_observed_travel": agreement(model, travel, tol),
        # What a careless analysis would report: driving time vs total response time.
        "if_compared_to_total_response": agreement(model, response, tol),
        "tolerance_min": tol,
        "excluded_areas": len(excluded),
        "excluded_reasons": {k: sum(e["reason"] == k for e in excluded) for k in {e["reason"] for e in excluded}},
        "largest_gaps": [
            {"modzcta": r["modzcta"], "model_min": float(r["model_median_min"]), "observed_min": float(r["obs_travel_min"]),
             "incidents": int(r["obs_incidents"])}
            for r in worst
        ],
        "traps": evaluate_traps(case, summary),
        "unmatched_zip_incidents": sum(u["incidents"] for u in summary.get("unmatched_zips", [])),
    }


def auc(pos: list[float], neg: list[float]) -> float:
    """Probability a random positive scores higher than a random negative (ties count half)."""
    r = ranks(pos + neg)
    n1, n0 = len(pos), len(neg)
    return (sum(r[:n1]) - n1 * (n1 + 1) / 2) / (n1 * n0) if n1 and n0 else float("nan")


def _num(v: str) -> float | None:
    return float(v) if v not in ("", None) else None


def score_flood_ida(case: dict, out_dir: Path) -> dict:
    key = case["answer_key"]
    rows = list(csv.DictReader(open(out_dir / "points.csv", encoding="utf-8")))
    summary = json.loads((out_dir / "run_summary.json").read_text())
    marks = [r for r in rows if r["kind"] == "mark" and _num(r["sink_depth_m"]) is not None]
    controls = [r for r in rows if r["kind"] == "control" and _num(r["sink_depth_m"]) is not None]
    thr = key["sink_threshold_m"]

    def detection(feature: str, sign: float) -> dict:
        pos = [sign * float(r[feature]) for r in marks]
        neg = [sign * float(r[feature]) for r in controls]
        # One value per site so heavily surveyed sites don't dominate.
        by_site: dict[str, tuple[list, list]] = {}
        for r in marks:
            by_site.setdefault(r["site"], ([], []))[0].append(sign * float(r[feature]))
        for r in controls:
            if r["site"] in by_site:
                by_site[r["site"]][1].append(sign * float(r[feature]))
        site_pos = [statistics.median(p) for p, n in by_site.values() if n]
        site_neg = [statistics.median(n) for p, n in by_site.values() if n]
        return {"auc_points": round(auc(pos, neg), 3), "auc_sites": round(auc(site_pos, site_neg), 3), "sites": len(site_pos)}

    in_sink = lambda rs: sum(float(r["sink_depth_m"]) >= thr for r in rs) / len(rs)  # noqa: E731
    street = [r for r in marks if r["interior"] == "False" and _num(r["obs_depth_m"]) is not None]
    old_rule = [r for r in marks if r.get("keyword_interior") == "False" and _num(r["obs_depth_m"]) is not None]
    ground = [(float(r["dem_m"]) - float(r["obs_ground_m"])) for r in marks if _num(r["obs_ground_m"]) is not None]
    return {
        "case": case["id"],
        "marks": len(marks),
        "controls": len(controls),
        "sink_depth": detection("sink_depth_m", 1),
        "low_relative_elevation": detection("tpi_m", -1),
        "share_in_sink": {"marks": round(in_sink(marks), 3), "controls": round(in_sink(controls), 3), "threshold_m": thr},
        "depth_vs_observed_street_marks": {
            "n": len(street),
            "spearman_r": round(spearman([float(r["sink_depth_m"]) for r in street], [float(r["obs_depth_m"]) for r in street]), 3),
            "median_observed_m": round(statistics.median(float(r["obs_depth_m"]) for r in street), 2),
            "median_modeled_m": round(statistics.median(float(r["sink_depth_m"]) for r in street), 2),
        },
        "depth_vs_observed_old_keyword_rule": {
            "n": len(old_rule),
            "spearman_r": round(spearman([float(r["sink_depth_m"]) for r in old_rule], [float(r["obs_depth_m"]) for r in old_rule]), 3) if old_rule else None,
        },
        "dem_minus_surveyed_ground_m": {"n": len(ground), "median": round(statistics.median(ground), 2),
                                        "mad": round(statistics.median(abs(g - statistics.median(ground)) for g in ground), 2)},
        "interior_marks": summary["interior_marks"],
        "interior_marks_old_keyword_rule": summary.get("keyword_interior_marks_old_rule"),
        "traps": evaluate_traps(case, summary),
    }


def score_wildfire_la(case: dict, out_dir: Path) -> dict:
    directions = case["answer_key"]["feature_directions"]
    sign = {f: (1 if d.startswith("higher") else -1) for f, d in directions.items()}
    rows = list(csv.DictReader(open(out_dir / "buildings.csv", encoding="utf-8")))
    summary = json.loads((out_dir / "run_summary.json").read_text())
    complete = [r for r in rows if all(r[f] != "" for f in sign)]

    def pct_ranks(rs: list[dict], f: str) -> list[float]:
        rk = ranks([sign[f] * float(r[f]) for r in rs])
        return [x / len(rs) for x in rk]

    def evaluate(rs: list[dict], label: str) -> dict:
        y = [r[label] == "1" for r in rs]
        out = {"n": len(rs), "destroyed_share": round(sum(y) / len(rs), 3)}
        combo = [0.0] * len(rs)
        for f in sign:
            pr = pct_ranks(rs, f)
            combo = [c + p / len(sign) for c, p in zip(combo, pr)]
            out[f] = round(auc([p for p, t in zip(pr, y) if t], [p for p, t in zip(pr, y) if not t]), 3)
        out["combined_equal_weights"] = round(auc([c for c, t in zip(combo, y) if t], [c for c, t in zip(combo, y) if not t]), 3)
        return out

    inspected = [r for r in complete if r["destroyed"] in ("0", "1")]
    # The careless version: every footprint without a destroyed record counts as a survivor.
    careless = [r | {"careless": "1" if r["destroyed"] == "1" else "0"} for r in complete]
    return {
        "case": case["id"],
        "feature_directions": directions,
        "all_fires": evaluate(inspected, "destroyed"),
        "by_fire": {fire: evaluate([r for r in inspected if r["fire"] == fire], "destroyed") for fire in ("eaton", "palisades")},
        "if_uninspected_counted_as_survivors": evaluate(careless, "careless"),
        "missing_feature_values": len(rows) - len(complete),
        "counts": summary["counts"],
        "traps": evaluate_traps(case, summary),
    }


SCORERS = {"fire_ems": score_fire_ems, "flood_ida": score_flood_ida, "wildfire_la": score_wildfire_la}


def main(case_id: str, out_name: str | None = None) -> dict:
    """Score a case; out_name picks another output folder (e.g. fire_ems_112 for a study-area run)."""
    case = json.loads((PROJECT / "cases" / f"{case_id}.json").read_text())
    out_dir = PROJECT / "outputs" / (out_name or case_id)
    result = SCORERS[case_id](case, out_dir)
    (out_dir / "score.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None), indent=2))


# ------------------------------------------------------------ general scoring
# Used by Score My Layer (pro/score_layer.py) for any prediction and truth source.

def _fmt(x, digits=3):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(x, digits)


def _count_metrics(pred: list[float], out: list[float]) -> dict:
    order = sorted(range(len(pred)), key=lambda i: -pred[i])
    top = order[: max(1, round(0.2 * len(order)))]
    total = sum(out) or float("nan")
    capture = sum(out[i] for i in top) / total
    return {"spearman_r": _fmt(spearman(pred, out)),
            "pearson_r_log": _fmt(pearson(pred, [math.log1p(v) for v in out])),
            "top20_capture": _fmt(capture), "top20_lift": _fmt(capture / (len(top) / len(order))),
            "total_events": sum(out), "features_with_none": sum(v == 0 for v in out)}


def _binary_metrics(pred: list[float], out: list[int]) -> dict:
    pos = [p for p, o in zip(pred, out) if o == 1]
    neg = [p for p, o in zip(pred, out) if o == 0]
    order = sorted(range(len(pred)), key=lambda i: -pred[i])
    top = order[: max(1, round(0.1 * len(order)))]
    base = len(pos) / len(out) if out else float("nan")
    prec = sum(out[i] for i in top) / len(top) if top else float("nan")
    return {"auc": _fmt(auc(pos, neg)), "yes": len(pos), "no": len(neg), "base_rate": _fmt(base),
            "top10_rate": _fmt(prec), "top10_lift": _fmt(prec / base if base else float("nan"))}


def score_pairs(meta: dict, pairs: list[dict]) -> dict:
    cfg, test = meta["config"], meta["test"]
    sign = -1.0 if cfg.get("higher_means") == "less" else 1.0
    min_n = cfg.get("min_records") or 1
    traps = [{"id": t["id"], "status": "handled" if t.get("handled") else "check", "detail": t["check"]}
             for t in meta["source"].get("traps", [])]

    def usable(p):
        if p["pred"] in (None, "") or p["outcome"] in (None, ""):
            return False
        # The minimum-records rule applies to averaged outcomes only; a yes/no "none happened" is a real answer.
        return test != "continuous" or int(p.get("n") or 0) >= min_n

    ok = [p for p in pairs if usable(p)]
    pred = [sign * float(p["pred"]) for p in ok]
    out = [float(p["outcome"]) for p in ok]
    if test == "continuous":
        metrics = {"spearman_r": _fmt(spearman(pred, out)), "pearson_r": _fmt(pearson(pred, out))}
        if cfg.get("same_units"):
            metrics["same_units"] = agreement([float(p["pred"]) for p in ok], out, cfg.get("tolerance") or 0)
        headline = f"Rank agreement {metrics['spearman_r']} (Spearman) across {len(ok)} features"
    elif test == "count":
        metrics = _count_metrics(pred, out)
        headline = (f"Top 20% of predicted features held {metrics['top20_capture']:.0%} of {int(metrics['total_events']):,} "
                    f"events ({metrics['top20_lift']}x random); Spearman {metrics['spearman_r']}")
    elif test == "binary":
        metrics = _binary_metrics(pred, [int(o) for o in out])
        headline = f"AUC {metrics['auc']}: {metrics['yes']:,} yes vs {metrics['no']:,} no"
        careless = [p for p in pairs if p["pred"] not in (None, "") and (p["outcome"] not in (None, "") or int(p.get("excluded") or 0))]
        if any(int(p.get("excluded") or 0) for p in careless):
            alt = _binary_metrics([sign * float(p["pred"]) for p in careless],
                                  [0 if p["outcome"] in (None, "") else int(float(p["outcome"])) for p in careless])
            traps.append({"id": "excluded_as_negative", "status": "handled",
                          "detail": f"Records without a valid label were excluded. Counting them as 'no' would give AUC "
                                    f"{alt['auc']} and a base rate of {alt['base_rate']} instead of {metrics['base_rate']}."})
    else:  # presence
        metrics = _binary_metrics(pred, [int(o) for o in out])
        metrics["controls"] = metrics.pop("no")
        metrics["records"] = metrics.pop("yes")
        headline = f"AUC {metrics['auc']} for {metrics['records']:,} records vs {metrics['controls']:,} random control points"
        traps.append({"id": "presence_only_controls", "status": "handled",
                      "detail": "Records exist only where the outcome happened, so they are compared with random control points. "
                                "False alarms can't be counted directly."})

    t, pairing = meta["truth"], meta.get("pairing", {})
    pdate, start = cfg.get("prediction_date"), cfg.get("start")
    if not pdate:
        traps.append({"id": "time_leakage", "status": "check",
                      "detail": "No prediction date given, so ProveIt can't confirm the outcomes came after the prediction."})
    elif not start or start < pdate:
        traps.append({"id": "time_leakage", "status": "warning",
                      "detail": f"Outcomes from before the prediction date ({pdate}) are included; the score may reward hindsight."})
    else:
        traps.append({"id": "time_leakage", "status": "handled", "detail": f"Only outcomes from {start} on, after the prediction date {pdate}."})
    if t.get("truncated"):
        traps.append({"id": "truncated", "status": "warning", "detail": "The download hit its row limit; narrow the area, dates or filter."})
    dropped = {k: v for k, v in (t.get("dropped") or {}).items() if v}
    if dropped:
        traps.append({"id": "records_dropped", "status": "handled", "detail": f"Records set aside while reading the source: {dropped}."})
    for key, label in (("truth_unmatched", "records fell outside every prediction feature"),
                       ("truth_keys_unmatched", "area codes in the source matched no prediction feature")):
        if pairing.get(key):
            traps.append({"id": key, "status": "check", "detail": f"{pairing[key]:,} {label}"
                          + (f" ({pairing['truth_records_unmatched']:,} records)." if key == "truth_keys_unmatched" else ".")})
    if pairing.get("truth_within_distance") is not None:
        traps.append({"id": "records_beside_polygons", "status": "warning",
                      "detail": f"Only {pairing['truth_total'] - pairing['truth_unmatched']:,} of {pairing['truth_total']:,} records fall inside "
                                f"a prediction polygon, but {pairing['truth_within_distance']:,} lie within "
                                f"{meta['config'].get('distance_m')} m of one. They are probably geocoded to a street frontage; "
                                "rerun with polygon_match = nearest."})
    if pairing.get("subset_where"):
        traps.append({"id": "subset", "status": "handled",
                      "detail": f"Scored only features where {pairing['subset_where']}; {pairing['subset_excluded_features']:,} left out, "
                                f"{pairing['subset_excluded_with_outcome']:,} of them with an outcome record."})
    if pairing.get("matched_by_key"):
        traps.append({"id": "matching", "status": "handled",
                      "detail": f"{pairing['matched_by_key']:,} records matched by ID and {pairing.get('matched_by_location', 0):,} by "
                                f"location; {pairing.get('truth_unmatched', 0):,} matched nothing (outside the study area or without an ID or nearby feature)."})
    skipped = len(pairs) - len(ok)
    if skipped:
        traps.append({"id": "not_scored", "status": "handled",
                      "detail": f"{skipped:,} features had no prediction, no outcome, or fewer than {min_n} records."})
    if len(ok) < 30:
        traps.append({"id": "small_sample", "status": "warning", "detail": f"Only {len(ok)} scored features; treat results as indicative."})
    if cfg.get("same_units") and not meta["source"]["outcome"].get("unit"):
        traps.append({"id": "units_unknown", "status": "warning", "detail": "The source doesn't state its unit; check before comparing values."})

    return {
        "name": meta["name"], "headline": headline, "test": test, "scored": len(ok), "metrics": metrics,
        "direction": "higher prediction = more outcome" if sign > 0 else "higher prediction = less outcome",
        "source": {"id": meta["source"]["id"], "name": meta["source"]["name"], "describes": meta["source"]["outcome"]["describes"],
                   "unit": meta["source"]["outcome"].get("unit"), "docs": meta["source"].get("docs"), "license": meta["source"].get("license")},
        "truth": {k: t.get(k) for k in ("records", "rows", "downloaded", "sha256", "request")},
        "prediction": {"layer": meta.get("prediction_layer"), "field": cfg.get("field"), "shape": meta.get("shape")},
        "traps": traps,
    }


def report_html(card: dict) -> str:
    import html as h

    color = {"handled": "#1b7f4b", "check": "#8a6d00", "warning": "#b42318"}
    rows = "".join(f"<tr><td><span style='color:{color[t['status']]};font-weight:600'>{t['status']}</span></td>"
                   f"<td>{h.escape(t['id'])}</td><td>{h.escape(t['detail'])}</td></tr>" for t in card["traps"])
    mets = "".join(f"<tr><td>{h.escape(k)}</td><td>{h.escape(json.dumps(v))}</td></tr>" for k, v in card["metrics"].items())
    s = card["source"]
    return f"""<!doctype html><meta charset="utf-8"><title>ProveIt: {h.escape(card['name'])}</title>
<style>body{{font:15px/1.5 system-ui,Segoe UI,Helvetica,sans-serif;max-width:920px;margin:32px auto;padding:0 16px;color:#1f2933}}
h1{{font-size:22px;margin:0 0 4px}}.lead{{font-size:18px;background:#f2f6f9;padding:14px 16px;border-left:4px solid #0b6e99}}
table{{border-collapse:collapse;width:100%;margin:8px 0 20px}}td,th{{border-bottom:1px solid #d5dce3;padding:6px 8px;text-align:left;vertical-align:top}}
.muted{{color:#5f6b7a;font-size:13px}}</style>
<h1>ProveIt scorecard: {h.escape(card['name'])}</h1>
<p class="muted">Prediction: {h.escape(str(card['prediction']['layer']))} | field {h.escape(str(card['prediction']['field']))} | {h.escape(card['direction'])}</p>
<p class="lead">{h.escape(card['headline'])}</p>
<h2>Answer key</h2><p>{h.escape(s['name'])}: {h.escape(s['describes'])}. {card['truth']['records']:,} records,
downloaded {h.escape(str(card['truth']['downloaded']))}. <a href="{h.escape(str(s['docs']))}">Source</a> | {h.escape(str(s['license']))}</p>
<h2>Metrics ({h.escape(card['test'])} test, {card['scored']:,} features scored)</h2><table>{mets}</table>
<h2>Trap check</h2><table><tr><th>Status</th><th>Trap</th><th>Detail</th></tr>{rows}</table>
<p class="muted">Truth data SHA-256 {h.escape(str(card['truth']['sha256']))}. Request: {h.escape(json.dumps(card['truth']['request']))}</p>"""
