"""Deterministic baselines: full-history Prophet + naive changepoint-window workflow.

Promoted from ``pocs/changepoint/{forecasting,baselines,results}.py``. ``fit_predict_prophet`` and
``metrics`` stay pipeline-side (Prophet is the changepoint forecasting mechanism; ``metrics`` is
re-exported from core). Validation uses the single holdout (last ``val_rows`` of training): fit on
``fit_df``, score on ``val_df`` — the same protocol scores naive candidates and agent proposals.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from prophet import Prophet

from ailf.core.metrics.metrics import metrics
from ailf.pipelines.changepoint.detector import ChangepointSet
from ailf.pipelines.changepoint.scenarios import SeriesSplit

warnings.filterwarnings("ignore")
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
logging.getLogger("prophet").setLevel(logging.ERROR)

__all__ = [
    "metrics",
    "fit_predict_prophet",
    "CandidateResult",
    "NaiveWorkflowResult",
    "full_history_prophet",
    "naive_workflow",
    "fit_full_history_test_forecast",
    "fit_naive_test_forecast",
]


def fit_predict_prophet(
    train_df: pd.DataFrame,
    future_ds: pd.Series,
    *,
    regressors: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
    holidays: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
) -> np.ndarray:
    """Fit a Prophet model and predict over ``future_ds`` (deterministic, MAP estimation)."""
    params = dict(params or {})
    if holidays is not None and len(holidays) > 0:
        params["holidays"] = holidays
    model = Prophet(**params)
    df = train_df[["ds", "y"]].copy()
    regressors = regressors or {}
    for name, (train_vals, _future_vals) in regressors.items():
        df[name] = np.asarray(train_vals, dtype=float)
        model.add_regressor(name)
    model.fit(df)
    future = pd.DataFrame({"ds": pd.to_datetime(pd.Series(future_ds).reset_index(drop=True))})
    for name, (_train_vals, future_vals) in regressors.items():
        future[name] = np.asarray(future_vals, dtype=float)
    return model.predict(future)["yhat"].to_numpy()


@dataclass
class CandidateResult:
    label: str
    val_metrics: dict[str, float]
    forecast: np.ndarray | None = None
    test_metrics: dict[str, float] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def val_mae(self) -> float:
        return self.val_metrics["mae"]

    def summary_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "val_metrics": self.val_metrics,
            "test_metrics": self.test_metrics,
            **({"extra": self.extra} if self.extra else {}),
        }


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
    inner = pd.DataFrame(
        {"ds": split.ds.iloc[window_start : split.fit_end], "y": split.y.iloc[window_start : split.fit_end]}
    )
    val = split.val_df
    yhat = fit_predict_prophet(inner, val["ds"])
    return metrics(val["y"].to_numpy(), yhat)


def full_history_prophet(split: SeriesSplit) -> CandidateResult:
    """Full-history default Prophet (FR-010). Validation scored for comparability."""
    return CandidateResult(label="full_history_prophet", val_metrics=_validation_mae(split, window_start=0))


def naive_workflow(split: SeriesSplit, changepoints: ChangepointSet) -> NaiveWorkflowResult:
    """Full history + every detected changepoint window; select min validation MAE (FR-011/012)."""
    window_starts = [0, *sorted(changepoints.indices)]
    window_starts = [w for w in dict.fromkeys(window_starts) if split.fit_end - w >= 30]
    if not window_starts:
        window_starts = [0]
    candidates: list[CandidateResult] = []
    for w in window_starts:
        label = "full_history" if w == 0 else f"naive_window@{w}"
        candidates.append(
            CandidateResult(label=label, val_metrics=_validation_mae(split, w), extra={"window_start": w})
        )
    selected = min(candidates, key=lambda c: c.val_mae)
    return NaiveWorkflowResult(
        candidates=candidates, selected=selected, selected_window_start=int(selected.extra["window_start"])
    )


def fit_full_history_test_forecast(split: SeriesSplit) -> tuple[np.ndarray, dict[str, float]]:
    train, test = split.train_df, split.test_df
    yhat = fit_predict_prophet(train, test["ds"])
    return yhat, metrics(test["y"].to_numpy(), yhat)


def fit_naive_test_forecast(split: SeriesSplit, window_start: int) -> tuple[np.ndarray, dict[str, float]]:
    train = pd.DataFrame(
        {"ds": split.ds.iloc[window_start : split.train_end], "y": split.y.iloc[window_start : split.train_end]}
    )
    test = split.test_df
    yhat = fit_predict_prophet(train, test["ds"])
    return yhat, metrics(test["y"].to_numpy(), yhat)
