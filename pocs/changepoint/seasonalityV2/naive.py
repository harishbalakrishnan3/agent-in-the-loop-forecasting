"""Naive Prophet baseline for the seasonalityV2 POC.

Fits Prophet with ALL default parameters on the training split.
Evaluates on val (for agent-loop config selection) and optionally on test
(final reporting only — never passed test_df during the agent loop).

Usage
-----
    from naive import run_naive_prophet

    # During agent loop (val only):
    result = run_naive_prophet(train_df, val_df, seed=42)
    print(result.val_mae)

    # After agent loop (final reporting):
    result_final = run_naive_prophet(train_df, val_df, test_df=test_df, seed=42)
    print(result_final.test_mae)
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Suppress Prophet/Stan verbose output
logging.getLogger("prophet").setLevel(logging.ERROR)
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)


@dataclass
class NaiveResult:
    val_mae:       float
    val_rmse:      float
    test_mae:      float | None        # None when test_df was not provided
    test_rmse:     float | None
    val_forecast:  pd.DataFrame        # columns: ds, yhat
    test_forecast: pd.DataFrame | None # columns: ds, yhat  (None if no test_df)


def _mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def _rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def _forecast(
    model,
    horizon_df: pd.DataFrame,
) -> tuple[pd.DataFrame, np.ndarray]:
    """Run model.predict on a future DataFrame aligned to horizon_df dates.

    Returns (forecast_df with ds+yhat, yhat array).
    """
    future = model.make_future_dataframe(periods=len(horizon_df), freq="D")
    forecast = model.predict(future)
    # Align to horizon dates
    fc = forecast[["ds", "yhat"]].tail(len(horizon_df)).reset_index(drop=True)
    return fc, fc["yhat"].to_numpy()


def run_naive_prophet(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame | None = None,
    seed: int = 42,
) -> NaiveResult:
    """Fit Prophet with all defaults on train_df; score on val (and optionally test).

    Parameters
    ----------
    train_df : pd.DataFrame
        Columns ``ds``, ``y``. Training split.
    val_df : pd.DataFrame
        Columns ``ds``, ``y``. Validation split. Used for agent-loop comparison.
    test_df : pd.DataFrame | None
        Columns ``ds``, ``y``. Hidden test split. Pass ONLY after the agent loop
        has completed — never during the agent loop (leakage guard).
    seed : int
        Stan seed for reproducibility where Prophet supports it.

    Returns
    -------
    NaiveResult
        val_mae and val_rmse are always populated.
        test_mae and test_rmse are None when test_df is not provided.
    """
    from prophet import Prophet  # lazy import to keep module importable without prophet

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = Prophet()   # all defaults — this is the naive baseline
        m.fit(train_df[["ds", "y"]])

    # Val forecast
    val_fc, val_yhat = _forecast(m, val_df)
    val_actual = val_df["y"].to_numpy()

    # Test forecast (only if requested)
    test_fc:   pd.DataFrame | None = None
    test_mae:  float | None = None
    test_rmse: float | None = None

    if test_df is not None:
        # Refit on train+val to forecast the test horizon
        # (mirrors agent evaluation: agent also fits on train_df, scores on test_df)
        # Actually: keep fitting on train_df only so both naive and agent are comparable
        test_horizon = len(val_df) + len(test_df)
        future_full = m.make_future_dataframe(periods=test_horizon, freq="D")
        fc_full = m.predict(future_full)
        test_fc_raw = fc_full[["ds", "yhat"]].tail(len(test_df)).reset_index(drop=True)
        test_fc = test_fc_raw
        test_yhat   = test_fc["yhat"].to_numpy()
        test_actual = test_df["y"].to_numpy()
        test_mae  = _mae(test_actual, test_yhat)
        test_rmse = _rmse(test_actual, test_yhat)

    return NaiveResult(
        val_mae=_mae(val_actual, val_yhat),
        val_rmse=_rmse(val_actual, val_yhat),
        test_mae=test_mae,
        test_rmse=test_rmse,
        val_forecast=val_fc,
        test_forecast=test_fc,
    )
