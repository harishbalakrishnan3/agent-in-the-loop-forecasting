"""Forecast error metrics — deterministic, test-first (Constitution Principle II).

Promoted verbatim from ``pocs/changepoint/forecasting.metrics`` so the promoted path reproduces
the POC's numbers exactly (SC-001). Computes MAE / RMSE / WAPE / sMAPE (lower is better).

MASE and prediction-interval coverage are named by Principle II but DEFERRED for this
behavior-preserving promotion (plan Deviation 1). This function is the extension point: add them
here test-first in a later feature without changing call sites.
"""

from __future__ import annotations

import math

import numpy as np


def metrics(y_true: np.ndarray, yhat: np.ndarray) -> dict[str, float]:
    """Standard forecast error metrics (lower is better): MAE, RMSE, WAPE, sMAPE."""
    y_true = np.asarray(y_true, dtype=float)
    yhat = np.asarray(yhat, dtype=float)
    err = y_true - yhat
    mae = float(np.mean(np.abs(err)))
    rmse = float(math.sqrt(np.mean(err**2)))
    smape = float(
        np.mean(2.0 * np.abs(err) / np.maximum(np.abs(y_true) + np.abs(yhat), 1e-9)) * 100
    )
    wape = float(np.sum(np.abs(err)) / np.maximum(np.sum(np.abs(y_true)), 1e-9) * 100)
    return {"mae": mae, "rmse": rmse, "wape": wape, "smape": smape}
