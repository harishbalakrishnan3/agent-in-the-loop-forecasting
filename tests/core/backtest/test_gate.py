"""T034 — the gate: validate→precondition→invoke→score→strictly-beat-naive; failure classification."""

from __future__ import annotations

import pytest

from ailf.core.agent.errors import ToolBoundsError
from ailf.core.agent.registry import Proposal
from ailf.core.backtest.gate import evaluate_on_test, evaluate_on_validation
from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.diagnostics import compute_diagnostics
from ailf.pipelines.changepoint.interventions import register_changepoint_registry
from ailf.pipelines.changepoint.scenarios import load_scenario


@pytest.fixture(scope="module")
def setup():
    sc = load_scenario("level_shift_loses_seasonality")
    cps = detect_changepoints(sc.split.train_df, n_changepoints_to_detect=sc.n_changepoints_to_detect)
    diag = compute_diagnostics(sc.split.train_df, changepoints=cps, seasonal_period=sc.seasonal_period)
    reg = register_changepoint_registry()
    return sc.split, reg, diag.to_agent_dict()


def test_validation_scores_and_reports_beat(setup):
    split, reg, diag = setup
    prop = Proposal(tool="full_history_ramp_regressor", params={})
    # huge naive bar → must beat; tiny bar → must not beat. Confirms beat flag tracks the score.
    easy = evaluate_on_validation(prop, split, reg, full_diagnostics=diag, naive_val_mae=1e9)
    hard = evaluate_on_validation(prop, split, reg, full_diagnostics=diag, naive_val_mae=0.0)
    assert easy["beat_naive"] is True
    assert hard["beat_naive"] is False
    assert easy["val_metrics"]["mae"] == hard["val_metrics"]["mae"]  # same fit, deterministic


def test_out_of_bounds_proposal_raises_toolboundserror(setup):
    split, reg, diag = setup
    prop = Proposal(tool="recent_window", params={"window_start": "bogus"})
    with pytest.raises(ToolBoundsError):
        evaluate_on_validation(prop, split, reg, full_diagnostics=diag, naive_val_mae=1e9)


def test_disabled_tool_rejected_by_gate(setup):
    split, reg, diag = setup
    projected = reg.for_run({"full_history_ramp_regressor"})  # step disabled
    prop = Proposal(tool="full_history_step_regressor", params={})
    with pytest.raises(ToolBoundsError, match="disabled"):
        evaluate_on_validation(prop, split, projected, full_diagnostics=diag, naive_val_mae=1e9)


def test_evaluate_on_test_returns_horizon_yhat(setup):
    split, reg, diag = setup
    prop = Proposal(tool="full_history_default", params={})
    yhat, m = evaluate_on_test(prop, split, reg, full_diagnostics=diag)
    assert len(yhat) == split.test_horizon
    assert m["mae"] > 0
