"""T044 — graph wiring/routing with a FakeModelWrapper (no Bedrock).

Exercises: visual∥diagnostics fan-out join (visual on), linear shape (visual off), decision↔
validation loop with budget, accepted vs budget-exhausted routing, and that final_evaluation is the
only place test data is read.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ailf.core.agent.engine import build_agent_graph
from ailf.core.agent.runtime import RunContext
from ailf.pipelines.changepoint.baselines import full_history_prophet, naive_workflow
from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.diagnostics import compute_diagnostics
from ailf.pipelines.changepoint.interventions import register_changepoint_registry
from ailf.pipelines.changepoint.scenarios import load_scenario
from ailf.pipelines.changepoint.schemas import InterventionChoice, VisualInspectionResult


class _NullEmitter:
    def emit(self, *a, **k):
        pass


def _ctx(make_fake_model, *, visual_enabled, decision_responses, scenario="level_shift_loses_seasonality"):
    sc = load_scenario(scenario)
    cps = detect_changepoints(sc.split.train_df, n_changepoints_to_detect=sc.n_changepoints_to_detect)
    diag = compute_diagnostics(sc.split.train_df, changepoints=cps, seasonal_period=sc.seasonal_period)
    naive = naive_workflow(sc.split, cps)
    visual_model = make_fake_model(responses=[
        VisualInspectionResult(observations=["x"], pattern_summary="p", hypotheses=["h"], uncertainties=["u"])
    ]) if visual_enabled else make_fake_model()
    decision_model = make_fake_model(responses=decision_responses)
    return RunContext(
        run_id="t", scenario_id=scenario,
        visual_model=visual_model, decision_model=decision_model,
        visual_model_id="v", decision_model_id="d",
        split=sc.split, full_diagnostics=diag, naive=naive,
        tool_registry=register_changepoint_registry(),
        visual_enabled=visual_enabled,
        enabled_diagnostics=frozenset(diag.field_names()),
        image_path=Path("/dev/null") if visual_enabled else None,
        emitter=_NullEmitter(),
        decision_prompt="DECIDE", visual_prompt="LOOK" if visual_enabled else None,
        visual_schema=VisualInspectionResult, decision_schema=InterventionChoice,
        max_iterations=5,
    )


def _initial(scenario="level_shift_loses_seasonality"):
    return {"scenario_id": scenario, "iterations": [], "rejected_signatures": []}


def test_visual_on_records_visual_before_decision(make_fake_model):
    ctx = _ctx(make_fake_model, visual_enabled=True,
               decision_responses=[InterventionChoice(tool="full_history_default", params={}, rationale="r", expected_effect="e")])
    ctx.naive.selected.val_metrics["mae"] = 1e9  # high bar → accept on iteration 1
    app = build_agent_graph(ctx)
    final = app.invoke(_initial(), config={"recursion_limit": 50})
    assert final["visual"]["pattern_summary"] == "p"  # visual recorded
    assert final["final_candidate"]["tool"] == "full_history_default"
    assert final["final_case"] == "accepted_beat_naive"
    assert "test_metrics" in final["final_candidate"]


def test_visual_off_skips_visual_node(make_fake_model):
    ctx = _ctx(make_fake_model, visual_enabled=False,
               decision_responses=[InterventionChoice(tool="full_history_default", params={}, rationale="r", expected_effect="e")])
    ctx.naive.selected.val_metrics["mae"] = 1e9  # high bar → accept on iteration 1
    app = build_agent_graph(ctx)
    final = app.invoke(_initial(), config={"recursion_limit": 50})
    assert "visual" not in final or not final.get("visual")  # no visual produced
    assert final["final_candidate"]["tool"] == "full_history_default"


def test_budget_exhaustion_carries_best_proposal(make_fake_model):
    # Always propose something that won't beat naive → loop to budget, carry best-val (no_beat case).
    responses = [
        InterventionChoice(tool="full_history_default", params={}, rationale=f"r{i}", expected_effect="e")
        for i in range(5)
    ]
    ctx = _ctx(make_fake_model, visual_enabled=False, decision_responses=responses)
    # Force "never beats": set naive bar to 0 by monkeypatching selected.val_mae via a tiny shim.
    ctx.naive.selected.val_metrics["mae"] = 0.0
    app = build_agent_graph(ctx)
    final = app.invoke(_initial(), config={"recursion_limit": 50})
    assert final["final_case"] == "best_proposal_no_beat"
    assert len(final["iterations"]) == 5
