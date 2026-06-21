"""Deterministic single validation-holdout gate — the sole scoring authority (FR-025/FR-034).

The agent proposes; the gate disposes (Constitution Principle IV). The gate validates the proposal's
params (bounds), runs the tool's precondition, invokes the tool on the validation holdout, scores
MAE, and applies the strictly-beat-naive accept rule. The agent NEVER sees the numeric validation
score — only accept / rejected-signature. Hidden-test evaluation happens only at final evaluation.

NOTE: this is a SINGLE validation-holdout gate (the last ``val_rows`` of training), not a
rolling-origin backtest. See ``ailf/core/backtest/__init__.py`` for the rolling-origin note.
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from ailf.core.agent.registry import Proposal, ToolContext, ToolRegistry
from ailf.core.metrics.metrics import metrics


class _SplitLike(Protocol):
    ds: pd.Series
    y: pd.Series

    @property
    def fit_end(self) -> int: ...
    @property
    def train_end(self) -> int: ...
    @property
    def test_horizon(self) -> int: ...


def _build_context(
    ds: pd.Series, y: pd.Series, *, fit_end: int, future_ds: pd.Series, diagnostics: dict[str, Any]
) -> ToolContext:
    """Plain-data ToolContext: training records up to ``fit_end`` + future ISO timestamps + diag."""
    training = [
        {"ds": pd.Timestamp(d).isoformat(), "y": float(v)}
        for d, v in zip(ds.iloc[:fit_end], y.iloc[:fit_end], strict=True)
    ]
    future = [pd.Timestamp(d).isoformat() for d in future_ds]
    return {"training": training, "future": future, "diagnostics": diagnostics}


def evaluate_on_validation(
    proposal: Proposal,
    split: _SplitLike,
    registry: ToolRegistry,
    *,
    full_diagnostics: dict[str, Any],
    naive_val_mae: float,
) -> dict[str, Any]:
    """Score the proposal on the validation holdout; return metrics + whether it beat naive.

    Fits on ``[0, fit_end)`` and predicts the holdout ``[fit_end, train_end)``. Raises
    ``ToolBoundsError`` (a NORMAL rejection, caught by the caller) for out-of-bounds / disabled /
    precondition-failed proposals; a genuine tool crash propagates (a stage failure).
    """
    val_ds = split.ds.iloc[split.fit_end : split.train_end]
    context = _build_context(
        split.ds, split.y, fit_end=split.fit_end, future_ds=val_ds, diagnostics=full_diagnostics
    )
    result = registry.invoke(proposal.tool, context, proposal.params)
    val_y = split.y.iloc[split.fit_end : split.train_end].to_numpy()
    val_metrics = metrics(val_y, result["yhat"])
    beat = val_metrics["mae"] < naive_val_mae  # strictly beat — no ties (POC clarification)
    return {"val_metrics": val_metrics, "beat_naive": bool(beat)}


def evaluate_on_test(
    proposal: Proposal,
    split: _SplitLike,
    registry: ToolRegistry,
    *,
    full_diagnostics: dict[str, Any],
) -> tuple[list[float], dict[str, float]]:
    """Final eval ONLY: fit on full training, forecast + score on the hidden test."""
    test_end = split.train_end + split.test_horizon
    test_ds = split.ds.iloc[split.train_end : test_end]
    context = _build_context(
        split.ds, split.y, fit_end=split.train_end, future_ds=test_ds, diagnostics=full_diagnostics
    )
    result = registry.invoke(proposal.tool, context, proposal.params)
    test_y = split.y.iloc[split.train_end : test_end].to_numpy()
    return result["yhat"], metrics(test_y, result["yhat"])
