"""Test-first (Principle II) — the domain-agnostic evaluator harness in ailf.core.eval.evaluators.

record_of(run, example) adapter (LangSmith-like .outputs objects, plain dicts, example fallback);
the outcome-only evaluators (no family branching); build_evaluator_set composition.
"""

from __future__ import annotations

from ailf.core.eval.evaluators import (
    agent_is_winner,
    agent_minus_naive_mae,
    beat_naive,
    build_evaluator_set,
    record_of,
)


class _Obj:
    def __init__(self, outputs):
        self.outputs = outputs


def _rec(beat=True, winner="agent", a=2.0, n=5.0):
    return {"outcome": {"beat_naive": beat, "agent_is_winner": winner == "agent",
                        "winner": winner, "agent_minus_naive_mae": a - n,
                        "agent_test_metrics": {"mae": a}, "naive_test_metrics": {"mae": n}}}


def test_record_of_accepts_object_dict_and_example_fallback():
    rec = _rec()
    assert record_of(_Obj(rec), None) == rec                     # .outputs object
    assert record_of({"outputs": rec}, None) == rec              # plain dict with outputs
    assert record_of(_Obj(None), _Obj(rec)) == rec               # falls back to example.outputs


def test_beat_naive_binary():
    assert beat_naive(_Obj(_rec(beat=True)), None)["score"] == 1
    assert beat_naive(_Obj(_rec(beat=False)), None)["score"] == 0
    assert beat_naive(_Obj(_rec(beat=True)), None)["key"] == "beat_naive"


def test_agent_is_winner_binary():
    assert agent_is_winner(_Obj(_rec(winner="agent")), None)["score"] == 1
    assert agent_is_winner(_Obj(_rec(winner="naive_workflow")), None)["score"] == 0


def test_agent_minus_naive_mae_continuous():
    r = agent_minus_naive_mae(_Obj(_rec(a=2.0, n=5.0)), None)
    assert abs(r["score"] - (-3.0)) < 1e-9   # agent better -> negative


def test_build_evaluator_set_composition():
    base = build_evaluator_set([beat_naive, agent_is_winner])
    assert [e.__name__ for e in base] == ["beat_naive", "agent_is_winner"]

    def extra_eval(run, example):  # a pipeline-injected evaluator
        return {"key": "extra", "score": 1}

    composed = build_evaluator_set([beat_naive], extra=[extra_eval])
    names = [e.__name__ for e in composed]
    assert "beat_naive" in names and "extra_eval" in names
    # extra=None -> base only
    assert build_evaluator_set([beat_naive], extra=None) == [beat_naive]
