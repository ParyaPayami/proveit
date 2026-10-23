import math

from proveit.score import agreement, evaluate_traps, pearson, spearman


def test_pearson_and_spearman_known_values():
    x = [1, 2, 3, 4, 5]
    assert math.isclose(pearson(x, [2, 4, 6, 8, 10]), 1.0)
    assert math.isclose(pearson(x, [5, 4, 3, 2, 1]), -1.0)
    # monotone but non-linear: Spearman 1, Pearson below 1
    y = [1, 4, 9, 16, 100]
    assert math.isclose(spearman(x, y), 1.0)
    assert pearson(x, y) < 1.0


def test_spearman_handles_ties():
    assert math.isclose(spearman([1, 2, 2, 3], [1, 2, 2, 3]), 1.0)


def test_agreement_bias_and_tolerance():
    a = agreement([2, 3, 4], [3, 4, 5], tolerance=0.5)
    assert a["median_bias_min"] == 1.0
    assert a["share_within_tolerance"] == 0.0
    assert a["share_within_tolerance_after_bias_in_sample"] == 1.0
    assert a["share_within_tolerance_after_loo_bias"] == 1.0


def test_loo_bias_is_stricter_than_in_sample():
    # One outlier area: the in-sample correction absorbs nothing extra, the LOO one cannot use itself.
    a = agreement([0, 0, 0, 0], [1.0, 1.0, 1.0, 3.0], tolerance=0.5)
    assert a["share_within_tolerance_after_loo_bias"] <= a["share_within_tolerance_after_bias_in_sample"]


def test_traps_missing_evidence_is_not_caught():
    case = {"traps": [
        {"id": "a", "check": "", "detect": "observed_field_used == 'med_travel_s'"},
        {"id": "b", "check": "", "detect": "unmatched_zips_reported"},
    ]}
    out = evaluate_traps(case, {"observed_field_used": "med_travel_s"})
    assert [t["caught"] for t in out] == [True, False]


def test_auc_perfect_random_and_ties():
    from proveit.score import auc

    assert auc([3, 4], [1, 2]) == 1.0
    assert auc([1, 2], [3, 4]) == 0.0
    assert auc([1, 1], [1, 1]) == 0.5
