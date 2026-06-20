"""T036 — baselines: full-history Prophet + naive-window workflow selection."""

from __future__ import annotations

import pytest

from ailf.pipelines.changepoint.baselines import full_history_prophet, naive_workflow
from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.scenarios import load_scenario

_SID = "level_shift_loses_seasonality"


@pytest.fixture(scope="module")
def split_and_cps():
    sc = load_scenario(_SID)
    cps = detect_changepoints(sc.split.train_df, n_changepoints_to_detect=sc.n_changepoints_to_detect)
    return sc.split, cps


def test_full_history_prophet_scores_validation(split_and_cps):
    split, _ = split_and_cps
    cand = full_history_prophet(split)
    assert cand.label == "full_history_prophet"
    assert cand.val_metrics["mae"] > 0
    assert set(cand.val_metrics) == {"mae", "rmse", "wape", "smape"}


def test_naive_workflow_selects_min_val_mae(split_and_cps):
    split, cps = split_and_cps
    result = naive_workflow(split, cps)
    # full-history window (0) is always a candidate
    assert any(c.extra["window_start"] == 0 for c in result.candidates)
    # selected candidate has the minimum validation MAE among candidates
    assert result.selected.val_mae == min(c.val_mae for c in result.candidates)
    assert result.selected_window_start == result.selected.extra["window_start"]
