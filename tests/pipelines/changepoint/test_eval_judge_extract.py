"""Test-first (Principle II) — the deterministic judge extract (reads judged_iteration, no Bedrock).

Exercises ONLY the plumbing (_rationale_and_diag + that build_rationale_judge yields score=None on
a crash record). The judge VERDICT is never asserted (Principle III) — that's the golden-marker test.
"""

from __future__ import annotations

from ailf.pipelines.changepoint.eval.judge import _rationale_and_diag, build_rationale_judge


def test_extract_reads_judged_iteration():
    rec = {"judged_iteration": {"rationale": "I argue X", "tool_argued_for": "full_history_prophet_tuned_holidays",
                                "diag": {"transient_event_score": 1.2}}}
    rationale, tool, diag = _rationale_and_diag(rec)
    assert rationale == "I argue X"
    assert tool == "full_history_prophet_tuned_holidays"
    assert diag == {"transient_event_score": 1.2}


def test_extract_empty_on_crash_record():
    # crash records have no judged_iteration -> empty -> judge returns score=None (no model call)
    rec = {"crash_info": {"exception_type": "IndexError"}}
    assert _rationale_and_diag(rec) == ("", "", {})


def test_judge_returns_none_on_crash_record_without_model():
    ev = build_rationale_judge()  # builds the evaluator; model only constructed on a real rationale
    out = ev({"outputs": {"crash_info": {"exception_type": "IndexError"}}}, None)
    assert out["score"] is None and out["value"] == "n/a_no_rationale"
