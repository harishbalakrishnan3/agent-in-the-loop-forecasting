"""T030 — tool registry types, bounds validation, and for_run() projection (FR-014/FR-022/FR-023)."""

from __future__ import annotations

import pytest

from ailf.core.agent.errors import ToolBoundsError
from ailf.core.agent.registry import Proposal, ToolParamSchema, ToolRegistry, ToolSpec


def _spec(name="t1", structural=True, invoker=None, precondition=None):
    return ToolSpec(
        name=name,
        description=f"desc {name}",
        params=[ToolParamSchema(name="mode", kind="enum", allowed=["a", "b"], default="a")],
        structural=structural,
        invoker=invoker,
        precondition=precondition,
    )


def test_proposal_action_signature_is_stable():
    p1 = Proposal(tool="t", params={"b": 2, "a": 1})
    p2 = Proposal(tool="t", params={"a": 1, "b": 2})
    assert p1.action_signature == p2.action_signature  # sorted keys


def test_validate_params_accepts_allowed_and_fills_default():
    reg = ToolRegistry([_spec()])
    assert reg.validate_params("t1", {"mode": "b"}) == {"mode": "b"}
    assert reg.validate_params("t1", {}) == {"mode": "a"}  # default


def test_validate_params_rejects_out_of_bounds():
    reg = ToolRegistry([_spec()])
    with pytest.raises(ToolBoundsError, match="not in allowed"):
        reg.validate_params("t1", {"mode": "z"})


def test_validate_params_rejects_unknown_param():
    reg = ToolRegistry([_spec()])
    with pytest.raises(ToolBoundsError, match="unknown params"):
        reg.validate_params("t1", {"ghost": 1})


def test_unknown_tool_raises():
    reg = ToolRegistry([_spec()])
    with pytest.raises(ToolBoundsError, match="unknown tool"):
        reg.get("nope")


def test_for_run_prunes_menu_and_allowed_set():
    reg = ToolRegistry([_spec("t1"), _spec("t2"), _spec("fallback", structural=False)])
    projected = reg.for_run({"t1"})  # t2 disabled, fallback always kept
    names = projected.allowed_names()
    assert "t1" in names
    assert "t2" not in names
    assert "fallback" in names  # non-structural always retained (FR-016)
    menu_names = {m["name"] for m in projected.menu()}
    assert menu_names == {"t1", "fallback"}


def test_disabled_tool_get_raises():
    reg = ToolRegistry([_spec("t1"), _spec("t2")]).for_run({"t1"})
    with pytest.raises(ToolBoundsError, match="disabled"):
        reg.get("t2")


def test_invoke_runs_precondition_then_invoker():
    calls = []

    def precond(ctx):
        calls.append("precond")
        return None  # pass

    def invoker(ctx, params):
        calls.append("invoke")
        return {"yhat": [1.0, 2.0], "resolved_params": params}

    reg = ToolRegistry([_spec(invoker=invoker, precondition=precond)])
    result = reg.invoke("t1", {"training": [], "future": [], "diagnostics": {}}, {"mode": "b"})
    assert calls == ["precond", "invoke"]
    assert result["yhat"] == [1.0, 2.0]


def test_invoke_blocked_by_failing_precondition():
    reg = ToolRegistry([_spec(invoker=lambda c, p: {"yhat": []}, precondition=lambda c: "not recurring")])
    with pytest.raises(ToolBoundsError, match="precondition failed"):
        reg.invoke("t1", {}, {"mode": "a"})
