import json

from proveit import truth
from proveit.score import score_pairs


def test_catalog_entries_are_complete():
    for s in truth.sources():
        for key in ("id", "name", "topics", "adapter", "outcome", "traps", "coverage"):
            assert key in s, (s.get("id"), key)
        assert s["outcome"]["kind"] in {"event", "measure", "label", "presence", "areal_measure"}
        assert s["adapter"]["type"] in set(truth.ADAPTERS) | {"manual"}


def test_find_filters_by_area_and_topic():
    chicago = [-87.7, 41.8, -87.6, 41.9]
    ids = {s["id"] for s in truth.find(chicago, "permits")}
    assert "chicago_building_permits" in ids and "nyc_dob_now_permits" not in ids


def test_text_dates_are_filtered_after_download():
    assert truth._parse_date("06/17/2020", "%m/%d/%Y") == "2020-06-17"
    assert truth._in_window("2020-06-17", "2020-01-01", "2020-12-31")
    assert not truth._in_window("2019-06-17", "2020-01-01", "2020-12-31")


def _meta(test, **cfg):
    return {"name": "t", "test": test, "config": {"higher_means": "more"} | cfg, "truth": {"records": 4},
            "pairing": {}, "source": {"id": "s", "name": "S", "outcome": {"describes": "x"}, "traps": []}}


def test_binary_reports_excluded_labels_and_leakage():
    pairs = [{"id": 1, "pred": 0.9, "outcome": 1, "n": 1}, {"id": 2, "pred": 0.1, "outcome": 0, "n": 1},
             {"id": 3, "pred": 0.8, "outcome": None, "n": 1, "excluded": 1}]
    card = score_pairs(_meta("binary", prediction_date="2025-01-01", start="2024-06-01"), pairs)
    assert card["metrics"]["auc"] == 1.0
    ids = {t["id"]: t["status"] for t in card["traps"]}
    assert ids["excluded_as_negative"] == "handled" and ids["time_leakage"] == "warning"


def test_direction_flips_ranking():
    pairs = [{"id": i, "pred": i, "outcome": 10 - i, "n": 1} for i in range(10)]
    more = score_pairs(_meta("continuous"), pairs)["metrics"]["spearman_r"]
    less = score_pairs(_meta("continuous", higher_means="less"), pairs)["metrics"]["spearman_r"]
    assert more == -1.0 and less == 1.0


def test_binary_keeps_features_with_no_events():
    pairs = [{"id": 1, "pred": 0.9, "outcome": 1, "n": 2}, {"id": 2, "pred": 0.2, "outcome": 0, "n": 0},
             {"id": 3, "pred": 0.1, "outcome": 0, "n": 0}]
    card = score_pairs(_meta("binary", min_records=1), pairs)
    assert card["scored"] == 3 and card["metrics"]["auc"] == 1.0


def test_combine_areal_rolls_up_member_codes():
    recs = [{"key": "11211", "n": 176, "value": 200.0}, {"key": "11249", "n": 94, "value": 260.0},
            {"key": "10151", "n": 1, "value": 100.0}]
    out, unmatched = truth.combine_areal(recs, {"11211": "11211", "11249": "11211"})
    assert out["11211"]["n"] == 270 and out["11211"]["parts"] == 2
    assert abs(out["11211"]["value"] - (176 * 200 + 94 * 260) / 270) < 1e-9
    assert [u["key"] for u in unmatched] == ["10151"]
