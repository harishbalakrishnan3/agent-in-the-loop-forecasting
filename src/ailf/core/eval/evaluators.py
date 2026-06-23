"""Domain-agnostic LangSmith evaluator harness (promoted from the POC).

Holds the record adapter + the OUTCOME-ONLY evaluators (they read only ``outcome.*`` — no use-case
family branching) + the ``build_evaluator_set`` compose seam. Use-case-specific evaluators
(boundary recall, family-match, the LLM-judge) are defined in the PIPELINE's eval package and
injected here via ``build_evaluator_set(base, extra=...)`` — core never imports a pipeline
(Principle VII).

Each evaluator is a ``fn(run, example) -> {"key", "score"[, "comment"|"value"]}`` (the LangSmith
contract); ``score=None`` means "not applicable / categorical".
"""

from __future__ import annotations

from typing import Any, Callable

Evaluator = Callable[[Any, Any], dict[str, Any]]


def record_of(run, example) -> dict[str, Any]:
    """Pull the golden record from a LangSmith Run/Example (``.outputs``) or a plain dict.

    Prefers ``run.outputs`` (the prediction side); falls back to ``example.outputs`` (so a REPLAY
    target that echoes the record through the example still works)."""
    out = getattr(run, "outputs", None)
    if not out and isinstance(run, dict):
        out = run.get("outputs")
    if not out:
        out = getattr(example, "outputs", None) or (
            example.get("outputs") if isinstance(example, dict) else None)
    return out or {}


# --- outcome-only evaluators (domain-agnostic; read only outcome.*) ----------------------------

def beat_naive(run, example) -> dict[str, Any]:
    """PRIMARY headline: did the agent beat the naive baseline on test MAE? (2-way, not 3-way.)"""
    rec = record_of(run, example)
    return {"key": "beat_naive", "score": 1 if rec.get("outcome", {}).get("beat_naive") else 0}


def agent_is_winner(run, example) -> dict[str, Any]:
    """3-way winner (agent beats naive AND the strong baseline). Diagnostic, not headline."""
    rec = record_of(run, example)
    return {"key": "agent_is_winner", "score": 1 if rec.get("outcome", {}).get("agent_is_winner") else 0}


def agent_minus_naive_mae(run, example) -> dict[str, Any]:
    """Continuous margin (agent.mae - naive.mae); negative = agent better."""
    rec = record_of(run, example)
    return {"key": "agent_minus_naive_mae",
            "score": float(rec.get("outcome", {}).get("agent_minus_naive_mae", 0.0))}


def build_evaluator_set(base: list[Evaluator], extra: list[Evaluator] | None = None) -> list[Evaluator]:
    """Compose the evaluator list: ``base`` (typically the core outcome-only evaluators) plus any
    pipeline-injected ``extra`` (family-aware evaluators, the LLM-judge). ``extra=None`` -> base only.
    This is the seam that keeps core free of pipeline imports."""
    return list(base) + list(extra or [])
