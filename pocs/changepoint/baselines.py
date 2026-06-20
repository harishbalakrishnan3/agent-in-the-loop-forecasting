"""Deterministic baselines: full-history Prophet + naive changepoint workflow (T011/T012).

Validation uses the single holdout (last ``validation_horizon`` rows of training): fit on
``fit_df``, score MAE on ``val_df``. The same protocol scores naive candidates and (later) agent
proposals, so they are directly comparable (FR-019, clarification). Prophet-only — NO ARIMA.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from pocs.changepoint.detector import ChangepointSet
from pocs.changepoint.forecasting import fit_predict_prophet, metrics
from pocs.changepoint.results import CandidateResult
from pocs.changepoint.scenarios import SeriesSplit


@dataclass
class NaiveWorkflowResult:
    candidates: list[CandidateResult]
    selected: CandidateResult
    selected_window_start: int

    def summary_dict(self) -> dict[str, object]:
        return {
            "candidates": [c.summary_dict() for c in self.candidates],
            "selected": self.selected.summary_dict(),
            "selected_window_start": self.selected_window_start,
        }


def _validation_mae(split: SeriesSplit, window_start: int) -> dict[str, float]:
    """Fit on [window_start, fit_end), score on the holdout [fit_end, train_end)."""
    inner = pd.DataFrame(
        {
            "ds": split.ds.iloc[window_start : split.fit_end],
            "y": split.y.iloc[window_start : split.fit_end],
        }
    )
    val = split.val_df
    yhat = fit_predict_prophet(inner, val["ds"])
    return metrics(val["y"].to_numpy(), yhat)


def full_history_prophet(split: SeriesSplit) -> CandidateResult:
    """Full-history default Prophet (FR-010). Validation scored for comparability."""
    val_metrics = _validation_mae(split, window_start=0)
    return CandidateResult(label="full_history_prophet", val_metrics=val_metrics)


def naive_workflow(split: SeriesSplit, changepoints: ChangepointSet) -> NaiveWorkflowResult:
    """Full history + every detected changepoint window; select min validation MAE (FR-011/012)."""
    window_starts = [0, *sorted(changepoints.indices)]
    # Drop windows that leave too little data before the holdout to fit.
    window_starts = [w for w in dict.fromkeys(window_starts) if split.fit_end - w >= 30]
    if not window_starts:
        window_starts = [0]

    candidates: list[CandidateResult] = []
    for w in window_starts:
        label = "full_history" if w == 0 else f"naive_window@{w}"
        candidates.append(CandidateResult(label=label, val_metrics=_validation_mae(split, w), extra={"window_start": w}))

    selected = min(candidates, key=lambda c: c.val_mae)
    return NaiveWorkflowResult(
        candidates=candidates,
        selected=selected,
        selected_window_start=int(selected.extra["window_start"]),
    )


def fit_full_history_test_forecast(split: SeriesSplit) -> "tuple[object, dict[str, float]]":
    """Final-eval helper: fit full history on train, forecast + score on hidden test."""
    train = split.train_df
    test = split.test_df
    yhat = fit_predict_prophet(train, test["ds"])
    return yhat, metrics(test["y"].to_numpy(), yhat)


def fit_naive_test_forecast(split: SeriesSplit, window_start: int) -> "tuple[object, dict[str, float]]":
    """Final-eval helper: fit the selected naive window on train, forecast + score on hidden test."""
    train = pd.DataFrame({"ds": split.ds.iloc[window_start : split.train_end], "y": split.y.iloc[window_start : split.train_end]})
    test = split.test_df
    yhat = fit_predict_prophet(train, test["ds"])
    return yhat, metrics(test["y"].to_numpy(), yhat)
