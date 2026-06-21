"""Generic agent node bodies (promoted from ``pocs/changepoint/graph/nodes.py``).

Each node takes ``(AgentState, RunContext)`` and returns a state delta. Non-serializable handles
live on ``RunContext``; ``AgentState`` stays plain. Test data is read only in
``final_evaluation_node``. Import-clean of langgraph (the engine imports these).
"""

from __future__ import annotations

import json
from typing import Any

from ailf.core.agent.errors import StageError, ToolBoundsError
from ailf.core.agent.registry import Proposal
from ailf.core.agent.runtime import RunContext
from ailf.core.backtest.gate import evaluate_on_test, evaluate_on_validation


def visual_inspection_node(state: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """Visual node (FR-016): consumes ONLY the training-only image; produces visual observations."""
    result = ctx.visual_model.invoke_structured_with_image(
        prompt=ctx.visual_prompt, image_path=ctx.image_path, schema=ctx.visual_schema
    )
    return {"visual": result.model_dump()}


def diagnostics_node(state: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """Deterministic (FR-017): expose the FILTERED agent-facing diagnostics + naive summary."""
    return {
        "diagnostics": ctx.full_diagnostics.to_agent_dict(ctx.enabled_diagnostics),
        "naive_summary": ctx.naive.summary_dict(),
    }


def _build_decision_prompt(base: str, state: dict[str, Any], ctx: RunContext) -> str:
    parts = [base]
    if ctx.visual_enabled:
        parts += ["\n\n## Visual inspection (produced before this decision)\n",
                  json.dumps(state.get("visual", {}), indent=2)]
    parts += ["\n\n## Numeric diagnostics (training-only)\n",
              json.dumps(state.get("diagnostics", {}), indent=2, default=str),
              "\n\n## Naive workflow validation summary (the bar you must strictly beat)\n",
              json.dumps(state.get("naive_summary", {}), indent=2)]
    rejected = state.get("rejected_signatures", [])
    if rejected:
        parts += ["\n\n## Already-rejected action signatures (do NOT repeat)\n", json.dumps(rejected, indent=2)]
    return "".join(parts)


def decision_node(state: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """Decision node (FR-018): choose exactly one bounded intervention by name + params."""
    if ctx.visual_enabled and not state.get("visual"):
        # Visual-first ordering invariant (only when visual is enabled) — typed error, not bare assert.
        raise StageError("decision reached before visual inspection completed (visual_enabled=True)")
    prompt = _build_decision_prompt(ctx.decision_prompt, state, ctx)
    choice = ctx.decision_model.invoke_structured_text(prompt=prompt, schema=ctx.decision_schema)
    proposal = Proposal(tool=choice.tool, params=dict(choice.params), rationale=choice.rationale)
    iterations = list(state.get("iterations", []))
    iterations.append(
        {
            "i": len(iterations) + 1,
            "proposal": {
                "tool": proposal.tool,
                "params": proposal.params,
                "action_signature": proposal.action_signature,
                "rationale": choice.rationale,
                "expected_effect": choice.expected_effect,
            },
            "val_result": None,
            "beat_naive": None,
        }
    )
    return {"iterations": iterations}


def validation_node(state: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """Validation node (FR-019): the gate scores on the holdout; accept iff it strictly beats naive."""
    iterations = list(state.get("iterations", []))
    rejected = list(state.get("rejected_signatures", []))
    current = iterations[-1]
    prop = current["proposal"]
    proposal = Proposal(tool=prop["tool"], params=prop["params"])
    naive_mae = ctx.naive.selected.val_mae
    full_diag = ctx.full_diagnostics.to_agent_dict()  # tools see the FULL bundle
    try:
        out = evaluate_on_validation(
            proposal, ctx.split, ctx.tool_registry, full_diagnostics=full_diag, naive_val_mae=naive_mae
        )
        current["val_result"] = {"val_metrics": out["val_metrics"], "naive_val_mae": naive_mae}
        current["beat_naive"] = out["beat_naive"]
        accepted = None
        if out["beat_naive"]:
            accepted = {"proposal": prop, "val_result": current["val_result"]}
        elif prop["action_signature"] not in rejected:
            rejected.append(prop["action_signature"])
        return {"iterations": iterations, "rejected_signatures": rejected, "accepted": accepted}
    except ToolBoundsError as exc:
        # Out-of-bounds / disabled / precondition fail = NORMAL rejection (re-prompt), not a failure.
        current["val_result"] = {"rejected_reason": str(exc)}
        current["beat_naive"] = False
        if prop["action_signature"] not in rejected:
            rejected.append(prop["action_signature"])
        return {"iterations": iterations, "rejected_signatures": rejected, "accepted": None}


def route_after_validation(state: dict[str, Any], max_iterations: int = 5) -> str:
    if state.get("accepted"):
        return "final_evaluation"
    if len(state.get("iterations", [])) >= max_iterations:
        return "final_evaluation"
    return "decision"


def _best_proposal(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("accepted"):
        return state["accepted"]["proposal"]
    scored = [
        it for it in state.get("iterations", [])
        if it.get("val_result") and "val_metrics" in it["val_result"]
    ]
    if not scored:
        return state["iterations"][0]["proposal"]
    best = min(scored, key=lambda it: it["val_result"]["val_metrics"]["mae"])
    return best["proposal"]


def final_evaluation_node(state: dict[str, Any], ctx: RunContext) -> dict[str, Any]:
    """Final eval (FR-021): the ONLY place test data is read. Scores all three methods."""
    from ailf.pipelines.changepoint.baselines import (  # local import: keeps core import-clean of pipeline
        fit_full_history_test_forecast,
        fit_naive_test_forecast,
    )

    accepted = state.get("accepted")
    final_case = "accepted_beat_naive" if accepted else "best_proposal_no_beat"
    prop = _best_proposal(state)
    proposal = Proposal(tool=prop["tool"], params=prop["params"])
    full_diag = ctx.full_diagnostics.to_agent_dict()

    agent_yhat, agent_test = evaluate_on_test(proposal, ctx.split, ctx.tool_registry, full_diagnostics=full_diag)
    full_yhat, full_test = fit_full_history_test_forecast(ctx.split)
    naive_yhat, naive_test = fit_naive_test_forecast(ctx.split, ctx.naive.selected_window_start)

    return {
        "final_candidate": {
            "label": f"agent:{prop['action_signature']}",
            "tool": prop["tool"],
            "params": prop["params"],
            "test_metrics": agent_test,
        },
        "final_case": final_case,
        "_final_eval": {
            "agent": {"yhat": list(map(float, agent_yhat)), "test_metrics": agent_test, "tool": prop["tool"]},
            "full_history_prophet": {"yhat": list(map(float, full_yhat)), "test_metrics": full_test},
            "naive_workflow": {
                "yhat": list(map(float, naive_yhat)),
                "test_metrics": naive_test,
                "selected_window": f"window_start={ctx.naive.selected_window_start}",
            },
        },
    }
