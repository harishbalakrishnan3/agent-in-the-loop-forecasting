"""T011 — closed-form tests for forecast metrics (Constitution Principle II, test-first)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ailf.core.metrics.metrics import metrics


def test_perfect_forecast_is_all_zero():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    m = metrics(y, y.copy())
    assert m["mae"] == 0.0
    assert m["rmse"] == 0.0
    assert m["wape"] == 0.0
    assert m["smape"] == 0.0


def test_closed_form_values():
    # errors = [+2, -2, +2, -2]; |err| = 2 each
    y_true = np.array([10.0, 10.0, 10.0, 10.0])
    yhat = np.array([8.0, 12.0, 8.0, 12.0])
    m = metrics(y_true, yhat)
    assert m["mae"] == pytest.approx(2.0)
    assert m["rmse"] == pytest.approx(2.0)  # sqrt(mean(4)) = 2
    # WAPE = sum|err| / sum|y_true| * 100 = 8 / 40 * 100 = 20
    assert m["wape"] == pytest.approx(20.0)
    # sMAPE = mean( 2|err| / (|y|+|yhat|) ) * 100
    expected_smape = float(np.mean([2 * 2 / (10 + 8), 2 * 2 / (10 + 12)] * 2) * 100)
    assert m["smape"] == pytest.approx(expected_smape)


def test_rmse_penalizes_large_errors_more_than_mae():
    y_true = np.array([0.0, 0.0, 0.0])
    yhat = np.array([0.0, 0.0, 3.0])
    m = metrics(y_true, yhat)
    assert m["mae"] == pytest.approx(1.0)
    assert m["rmse"] == pytest.approx(math.sqrt(3.0))
    assert m["rmse"] > m["mae"]


def test_returns_exactly_the_four_keys():
    m = metrics(np.array([1.0, 2.0]), np.array([1.0, 3.0]))
    assert set(m) == {"mae", "rmse", "wape", "smape"}
