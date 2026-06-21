"""T032 — changepoint tools: invoke purity, bounds, holiday precondition, fallback (FR-016/FR-031)."""

from __future__ import annotations

import pandas as pd
import pytest

from ailf.core.agent.errors import ToolBoundsError
from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.diagnostics import compute_diagnostics
from ailf.pipelines.changepoint.interventions import (
    FALLBACK_TOOL_NAME,
    STRUCTURAL_TOOL_NAMES,
    register_changepoint_registry,
    structural_tool_names,
)
from ailf.pipelines.changepoint.scenarios import load_scenario


def _context(scenario_id: str, *, to_validation: bool = True):
    sc = load_scenario(scenario_id)
    split = sc.split
    cps = detect_changepoints(split.train_df, n_changepoints_to_detect=sc.n_changepoints_to_detect)
    diag = compute_diagnostics(split.train_df, changepoints=cps, seasonal_period=sc.seasonal_period)
    fit_end = split.fit_end if to_validation else split.train_end
    end = split.train_end if to_validation else split.train_end + split.test_horizon
    future_ds = split.ds.iloc[fit_end:end]
    training = [
        {"ds": pd.Timestamp(d).isoformat(), "y": float(v)}
        for d, v in zip(split.ds.iloc[:fit_end], split.y.iloc[:fit_end], strict=True)
    ]
    return {
        "training": training,
        "future": [pd.Timestamp(d).isoformat() for d in future_ds],
        "diagnostics": diag.to_agent_dict(),
    }, len(future_ds)


def test_structural_names_are_the_five():
    assert structural_tool_names() == STRUCTURAL_TOOL_NAMES
    assert len(STRUCTURAL_TOOL_NAMES) == 5


def test_registry_has_five_structural_plus_fallback():
    reg = register_changepoint_registry()
    names = set(reg.allowed_names())
    assert set(STRUCTURAL_TOOL_NAMES) <= names
    assert FALLBACK_TOOL_NAME in names


def test_fallback_is_nonstructural_and_always_kept():
    reg = register_changepoint_registry().for_run(set())  # all structural disabled
    assert reg.allowed_names() == {FALLBACK_TOOL_NAME}


@pytest.mark.parametrize("tool", ["full_history_step_regressor", "full_history_ramp_regressor"])
def test_invoke_returns_yhat_of_horizon_length(tool):
    reg = register_changepoint_registry()
    ctx, horizon = _context("level_shift_loses_seasonality")
    result = reg.invoke(tool, ctx, {})
    assert len(result["yhat"]) == horizon
    assert all(isinstance(v, float) for v in result["yhat"])


def test_fallback_invoke_works_without_diagnostics():
    reg = register_changepoint_registry()
    ctx, horizon = _context("level_shift_loses_seasonality")
    result = reg.invoke(FALLBACK_TOOL_NAME, ctx, {})
    assert len(result["yhat"]) == horizon


def test_tuned_param_out_of_grid_rejected():
    reg = register_changepoint_registry()
    ctx, _ = _context("prophet_prior_tuning_recurring_event")
    with pytest.raises(ToolBoundsError, match="not in allowed"):
        reg.invoke("full_history_prophet_tuned_holidays", ctx, {"changepoint_prior_scale": 0.99})


def test_clean_event_accepts_block_list_by_index_and_by_dict():
    # The agent references candidate blocks the way it reads them: by positional index, by the
    # {start_ds,end_ds} date dict it was shown, or by the {start,end} integer-bound dict. All three
    # resolve to the SAME candidate block, so all three yield a horizon-length forecast.
    reg = register_changepoint_registry()
    ctx, horizon = _context("temporary_event_not_regime_change")
    blocks = ctx["diagnostics"]["candidate_event_blocks"]
    b0 = blocks[0]
    by_index = reg.invoke("full_history_clean_event", ctx, {"blocks": [0]})
    by_dates = reg.invoke(
        "full_history_clean_event", ctx, {"blocks": [{"start_ds": b0["start_ds"], "end_ds": b0["end_ds"]}]}
    )
    by_bounds = reg.invoke(
        "full_history_clean_event", ctx, {"blocks": [{"start": b0["start"], "end": b0["end"]}]}
    )
    assert len(by_index["yhat"]) == horizon
    assert by_dates["yhat"] == by_index["yhat"]  # same block selected → identical forecast
    assert by_bounds["yhat"] == by_index["yhat"]


def test_clean_event_malformed_block_list_is_bounds_rejection_not_crash():
    # Regression (caught by the live golden eval): out-of-range ints, dicts matching no candidate
    # block, and non-index/dict entries must each raise ToolBoundsError (a normal rejection →
    # re-prompt), never a TypeError/IndexError crash (which would become a stage failure).
    reg = register_changepoint_registry()
    ctx, _ = _context("temporary_event_not_regime_change")
    with pytest.raises(ToolBoundsError, match="out of range"):
        reg.invoke("full_history_clean_event", ctx, {"blocks": [9999]})
    with pytest.raises(ToolBoundsError, match="matches no candidate"):
        reg.invoke("full_history_clean_event", ctx, {"blocks": [{"start": 1, "end": 2}]})
    with pytest.raises(ToolBoundsError, match="index or block dict"):
        reg.invoke("full_history_clean_event", ctx, {"blocks": ["nonsense"]})


def test_holiday_precondition_blocks_non_recurring_scenario():
    reg = register_changepoint_registry()
    # level_shift is NOT calendar-recurring → precondition must block (FR-031)
    ctx, _ = _context("level_shift_loses_seasonality")
    with pytest.raises(ToolBoundsError, match="not calendar-recurring"):
        reg.invoke(
            "full_history_prophet_tuned_holidays",
            ctx,
            {
                "changepoint_prior_scale": 0.05,
                "seasonality_prior_scale": 10.0,
                "holidays_prior_scale": 10.0,
                "seasonality_mode": "additive",
                "changepoint_range": 0.8,
            },
        )
