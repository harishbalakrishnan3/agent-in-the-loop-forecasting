"""Curated golden-set tests for the migrated src/ailf eval path.

- A DETERMINISTIC (unmarked) test: the committed curated records reproduce the committed baseline
  (the Principle-III no-regression gate; runs with no credentials).
- A GOLDEN-MARKER test: the LLM judge actually SCORES (live Bedrock) — score in {0,1} for the
  non-crash records, None only for the crash records. The verdict wording is NOT asserted
  (Principle III). Skipped without AWS creds.
"""

from __future__ import annotations

import os

import pytest

from ailf.pipelines.changepoint.eval import runner


def test_curated_records_reproduce_committed_baseline():
    """Deterministic: replaying the committed schema-1.1 records must match data/curated_baseline.json
    (3/10 beat_naive, interval_recall 1.0, per-case verdicts) — the no-regression reference."""
    recs = runner.load_curated_records()
    assert len(recs) == 10
    snap = runner.snapshot_dict(recs)
    baseline = runner.load_baseline()
    assert snap["summary"]["beat_naive_count"] == baseline["summary"]["beat_naive_count"]
    assert snap["summary"]["interval_recall_micro"] == baseline["summary"]["interval_recall_micro"]
    # per-case verdicts identical
    for sid, cur in snap["cases"].items():
        assert cur["beat_naive"] == baseline["cases"][sid]["beat_naive"]
        assert sorted(cur["failure_modes"]) == sorted(baseline["cases"][sid]["failure_modes"])


def test_self_contained_no_reports_dependency():
    """The committed curated dataset must not reference the gitignored reports/ dir."""
    assert "reports/" not in runner.CURATED_JSONL.read_text()


def _have_bedrock() -> bool:
    return bool(os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("AWS_PROFILE"))


@pytest.mark.golden
@pytest.mark.skipif(not _have_bedrock(), reason="LLM judge needs Bedrock credentials")
def test_judge_scores_noncrash_and_skips_crash():
    """Live: the rationale judge returns score in {0,1} for the 6 non-crash records (it actually
    runs — a silently-disabled all-None judge FAILS here) and None only for the 4 crash records."""
    from ailf.pipelines.changepoint.eval.judge import build_rationale_judge
    judge = build_rationale_judge()
    recs = runner.load_curated_records()
    for r in recs:
        out = judge({"outputs": r}, None)
        if "crash_info" in r:
            assert out["score"] is None
        else:
            assert out["score"] in (0, 1)
