"""T063/T064 — lift-and-shift readiness (SC-011) + boundary purity (cross-cutting note 4).

A tool whose in-process implementation is replaced by a contract-equivalent stub (same
(ToolContext, params) -> ToolResult) is a drop-in: the gate scores it and the loop/trace are
unchanged. The ToolContext/ToolResult crossing carries only JSON-native data.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from ailf.core.agent.registry import Proposal, ToolRegistry, ToolSpec
from ailf.core.backtest.gate import evaluate_on_validation
from ailf.core.events.leakage import to_json
from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.diagnostics import compute_diagnostics
from ailf.pipelines.changepoint.scenarios import load_scenario


@pytest.fixture(scope="module")
def setup():
    sc = load_scenario("level_shift_loses_seasonality")
    cps = detect_changepoints(sc.split.train_df, n_changepoints_to_detect=sc.n_changepoints_to_detect)
    diag = compute_diagnostics(sc.split.train_df, changepoints=cps, seasonal_period=sc.seasonal_period)
    return sc.split, diag.to_agent_dict()


def test_out_of_process_stub_is_drop_in(setup):
    split, diag = setup
    captured = {}

    def stub_invoker(context, params):
        # An "MCP-served" stub: receives plain data, returns a plain ToolResult of horizon length.
        captured["context_keys"] = set(context)
        captured["context"] = context
        horizon = len(context["future"])
        return {"yhat": [0.0] * horizon, "resolved_params": params}

    registry = ToolRegistry([
        ToolSpec(name="stub_tool", description="contract-equivalent stub", params=[], invoker=stub_invoker)
    ])
    prop = Proposal(tool="stub_tool", params={})
    out = evaluate_on_validation(prop, split, registry, full_diagnostics=diag, naive_val_mae=1e9)
    # Gate scored the stub exactly like a real tool — no change to gate/loop required (SC-011).
    assert "val_metrics" in out and "beat_naive" in out
    assert captured["context_keys"] == {"training", "future", "diagnostics"}


def test_tool_context_is_json_native(setup):
    split, diag = setup
    captured = {}

    def capture_invoker(context, params):
        captured["context"] = context
        return {"yhat": [1.0] * len(context["future"]), "resolved_params": params}

    registry = ToolRegistry([ToolSpec(name="cap", description="", params=[], invoker=capture_invoker)])
    evaluate_on_validation(Proposal(tool="cap", params={}), split, registry, full_diagnostics=diag, naive_val_mae=1e9)
    ctx = captured["context"]
    # The crossing data must serialize through the strict serializer (no numpy/Timestamp/handles).
    to_json(ctx)
    # training is a list of {ds: str, y: float}; future is a list of ISO strings.
    assert isinstance(ctx["training"], list) and isinstance(ctx["training"][0]["ds"], str)
    assert isinstance(ctx["training"][0]["y"], float)
    assert all(isinstance(s, str) for s in ctx["future"])
