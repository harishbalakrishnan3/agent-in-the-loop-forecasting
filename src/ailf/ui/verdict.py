"""Derive the end-of-run verdict (winner + margin) from the run's final evaluation (data-model §4).

PURE module. Mirrors the backend's own winner logic (``reporting/artifacts.py``: winner = min test
MAE across the three methods; ``delta_vs_naive = naive_mae - agent_mae``) so the UI verdict and the
written report always agree (FR-023). Accepts the ``final_eval`` dict returned by ``run_scenario``.
"""

from __future__ import annotations

from dataclasses import dataclass

# Method ordering MUST match reporting/artifacts.write_metrics_json so the UI verdict and the
# written report break ties identically (min() returns the first minimum) — FR-023.
_METHODS = ("full_history_prophet", "naive_workflow", "agent")
_LABELS = {
    "agent": "Agent",
    "full_history_prophet": "Full-history Prophet",
    "naive_workflow": "Naive baseline",
}


@dataclass(frozen=True)
class Verdict:
    winner: str  # one of _METHODS
    winner_label: str
    agent_mae: float
    full_history_mae: float
    naive_mae: float
    margin_vs_naive: float  # naive_mae - agent_mae (positive => agent better than naive)
    headline: str


def _mae(final_eval: dict, method: str) -> float:
    return float(final_eval[method]["test_metrics"]["mae"])


def derive(final_eval: dict) -> Verdict:
    """Compute the verdict from a ``final_eval`` dict (keys: agent, full_history_prophet, naive_workflow)."""
    maes = {m: _mae(final_eval, m) for m in _METHODS}
    winner = min(_METHODS, key=lambda m: maes[m])
    agent_mae, full_mae, naive_mae = maes["agent"], maes["full_history_prophet"], maes["naive_workflow"]
    margin = naive_mae - agent_mae

    if winner == "agent":
        if naive_mae > 0:
            pct = (margin / naive_mae) * 100.0
            headline = f"Agent wins — {pct:.1f}% lower MAE than the naive baseline."
        else:
            headline = "Agent wins on hidden-test MAE."
    else:
        headline = (
            f"{_LABELS[winner]} wins on hidden-test MAE — the agent did not beat the baseline."
        )

    return Verdict(
        winner=winner,
        winner_label=_LABELS[winner],
        agent_mae=agent_mae,
        full_history_mae=full_mae,
        naive_mae=naive_mae,
        margin_vs_naive=margin,
        headline=headline,
    )
