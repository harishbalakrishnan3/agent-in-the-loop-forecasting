"""Test-first (Principle II) — domain-agnostic boundary-matching primitives in ailf.core.eval.matching.

match_intervals (IoU>=0.5, greedy 1:1) / match_points (+/-tolerance, greedy 1:1) + the
"found nothing => precision is None, not 1.0" rule + JSONL round-trip. No changepoint family
names appear here — these are pure functions over plain dicts/lists.
"""

from __future__ import annotations

import json

from ailf.core.eval.matching import (
    match_intervals,
    match_points,
    read_json,
    read_jsonl,
    write_jsonl,
)


def _iv(s, e, kind="event"):
    return {"kind": "interval", "start": s, "end": e, "interval_type": kind}


def test_interval_perfect_match():
    gt = [_iv(10, 20), _iv(40, 50)]
    pred = [{"start": 10, "end": 20}, {"start": 40, "end": 50}]
    m = match_intervals(gt, pred)
    assert m["tp"] == 2 and m["fp"] == 0 and m["fn"] == 0
    assert m["precision"] == 1.0 and m["recall"] == 1.0


def test_interval_one_missed_one_extra():
    gt = [_iv(10, 20), _iv(100, 120)]          # second is far from any pred
    pred = [{"start": 10, "end": 20}, {"start": 200, "end": 210}]  # second is a false positive
    m = match_intervals(gt, pred)
    assert m["tp"] == 1 and m["fp"] == 1 and m["fn"] == 1
    assert abs(m["recall"] - 0.5) < 1e-9 and abs(m["precision"] - 0.5) < 1e-9


def test_interval_iou_threshold_rejects_low_overlap():
    # gt [0,100); pred [80,180): inter=20, union=180 -> IoU ~0.111 < 0.5 -> no match
    m = match_intervals([_iv(0, 100)], [{"start": 80, "end": 180}])
    assert m["tp"] == 0 and m["fn"] == 1 and m["fp"] == 1


def test_interval_precision_none_when_no_predictions():
    # "found nothing" must NOT score precision 1.0 — it is undefined (None).
    m = match_intervals([_iv(10, 20)], [])
    assert m["tp"] == 0 and m["fp"] == 0 and m["fn"] == 1
    assert m["precision"] is None
    assert m["recall"] == 0.0


def test_interval_recall_none_when_no_ground_truth():
    m = match_intervals([], [{"start": 10, "end": 20}])
    assert m["recall"] is None


def test_point_match_within_tolerance_greedy():
    gt = [{"kind": "point", "index": 100}, {"kind": "point", "index": 500}]
    detected = [102, 480, 900]   # 102 matches 100 (d=2); 480 matches 500 (d=20<=25); 900 spurious
    m = match_points(gt, detected, tolerance=25)
    assert m["tp"] == 2 and m["fn"] == 0 and m["fp"] == 1
    assert m["measures"] == "detector"


def test_point_no_match_out_of_tolerance():
    gt = [{"kind": "point", "index": 100}]
    m = match_points(gt, [200], tolerance=25)   # |200-100|=100 > 25
    assert m["tp"] == 0 and m["fn"] == 1 and m["fp"] == 1


def test_point_one_detected_cannot_match_two_gt():
    # greedy 1:1: a single detected index must not satisfy two ground-truth points
    gt = [{"kind": "point", "index": 100}, {"kind": "point", "index": 110}]
    m = match_points(gt, [105], tolerance=25)
    assert m["tp"] == 1 and m["fn"] == 1


def test_jsonl_roundtrip(tmp_path):
    recs = [{"a": 1, "b": [1, 2]}, {"a": 2, "b": []}]
    p = tmp_path / "x.jsonl"
    write_jsonl(recs, p)
    assert read_jsonl(p) == recs
    # read_json reads a single json doc
    pj = tmp_path / "y.json"
    pj.write_text(json.dumps({"k": "v"}))
    assert read_json(pj) == {"k": "v"}
