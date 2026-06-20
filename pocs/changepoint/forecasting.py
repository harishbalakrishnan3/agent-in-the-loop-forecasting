"""Prophet fit/predict helpers and forecast metrics (T007).

Deterministic for a fixed dataset (Prophet MAP estimation). Metrics: MAE/RMSE/WAPE/sMAPE.
"""

from __future__ import annotations

import logging
import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
from prophet import Prophet

warnings.filterwarnings("ignore")
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
logging.getLogger("prophet").setLevel(logging.ERROR)


def metrics(y_true: np.ndarray, yhat: np.ndarray) -> dict[str, float]:
    """Standard forecast error metrics (lower is better)."""
    y_true = np.asarray(y_true, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    err = y_true - yhat
    mae = float(np.mean(np.abs(err)))
    rmse = float(math.sqrt(np.mean(err**2)))
    smape = float(np.mean(2.0 * np.abs(err) / np.maximum(np.abs(y_true) + np.abs(yhat), 1e-9)) * 100)
    wape = float(np.sum(np.abs(err)) / np.maximum(np.sum(np.abs(y_true)), 1e-9) * 100)
    return {"mae": mae, "rmse": rmse, "wape": wape, "smape": smape}


def fit_predict_prophet(
    train_df: pd.DataFrame,
    future_ds: pd.Series,
    *,
    regressors: dict[str, tuple[np.ndarray, np.ndarray]] | None = None,
    holidays: pd.DataFrame | None = None,
    params: dict[str, Any] | None = None,
) -> np.ndarray:
    """Fit a Prophet model and predict over ``future_ds``.

    ``regressors`` maps name -> (train_values, future_values) for extra regressors.
    ``params`` passes bounded hyperparameters (changepoint_prior_scale, etc.).
    """
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
