"""LangGraph node implementations (T020/T023/T025/T026/T027, contracts/graph_nodes.md).

Non-serializable runtime objects (split, diagnostics, models, naive result) live on a
``RunContext`` captured by the node closures, so ``AgentState`` stays serializable. Test data is
read only inside ``final_evaluation_node``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_aws import ChatBedrockConverse

from pocs.changepoint.baselines import (
    NaiveWorkflowResult,
    fit_full_history_test_forecast,
    fit_naive_test_forecast,
)
from pocs.changepoint.config import PocConfig
from pocs.changepoint.diagnostics import DiagnosticsBundle
from pocs.changepoint.graph.state import (
    AgentState,
    InterventionChoice,
    VisualInspectionResult,
)
from pocs.changepoint.interventions import (
    InterventionError,
    Proposal,
    evaluate_on_test,
    evaluate_on_validation,
)
from pocs.changepoint.llm import invoke_structured_text, invoke_structured_with_image
from pocs.changepoint.scenarios import Scenario

MAX_ITERATIONS = 5
_PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"


@dataclass
class RunContext:
    config: PocConfig
    scenario: Scenario
    diagnostics: DiagnosticsBundle
    naive: NaiveWorkflowResult
    visual_model: ChatBedrockConverse
    react_model: ChatBedrockConverse
    image_path: Path


def _read_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text()


def make_visual_node(ctx: RunContext):
    prompt = _read_prompt("visual_inspection_v1.md")

    def visual_inspection_node(state: AgentState) -> dict[str, Any]:
        result = invoke_structured_with_image(
            ctx.visual_model,
            model_id=ctx.config.visual_model_id,
            prompt=prompt,
            image_path=ctx.image_path,
            schema=VisualInspectionResult,
        )
        return {"visual": result.model_dump()}

    return visual_inspection_node


def make_diagnostics_node(ctx: RunContext):
    def diagnostics_node(state: AgentState) -> dict[str, Any]:
        # Deterministic, no LLM. Diagnostics are precomputed; expose the agent-facing view + naive.
        return {
            "diagnostics": ctx.diagnostics.to_agent_dict(),
            "naive_summary": ctx.naive.summary_dict(),
        }

    return diagnostics_node


def _build_decision_prompt(base: str, state: AgentState) -> str:
    import json

    parts = [
        base,
        "\n## Visual inspection (produced before this decision)\n",
        json.dumps(state.get("visual", {}), indent=2),
        "\n## Numeric diagnostics (training-only)\n",
        json.dumps(state.get("diagnostics", {}), indent=2, default=str),
        "\n## Naive workflow validation summary (the bar you must strictly beat)\n",
        json.dumps(state.get("naive_summary", {}), indent=2),
    ]
    rejected = state.get("rejected_signatures", [])
    if rejected:
        parts += ["\n## Already-rejected action signatures (do NOT repeat)\n", json.dumps(rejected, indent=2)]
    return "".join(parts)


def make_decision_node(ctx: RunContext):
    base_prompt = _read_prompt("react_decision_v1.md")

    def react_decision_node(state: AgentState) -> dict[str, Any]:
        # Leakage invariant (SC-003): a completed visual result must exist before any decision,
        # and the decision is never handed test data or audit fields.
        assert state.get("visual"), "react_decision reached before visual inspection completed"
        prompt = _build_decision_prompt(base_prompt, state)
        choice = invoke_structured_text(
            ctx.react_model, model_id=ctx.config.react_model_id, prompt=prompt, schema=InterventionChoice
        )
        proposal = Proposal(tool=choice.tool, params=dict(choice.params))
        iterations = list(state.get("iterations", []))
        iterations.append(
            {
                "i": len(iterations) + 1,
                "proposal": {
                    "tool": proposal.tool,
                    "params": proposal.params,
                    "action_signature": proposal.action_signature,
                    "visual_first_rationale": choice.visual_first_rationale,
                    "expected_effect": choice.expected_effect,
                },
                "val_result": None,
                "beat_naive": None,
            }
        )
        return {"iterations": iterations}

    return react_decision_node


def make_validation_node(ctx: RunContext):
    def validation_node(state: AgentState) -> dict[str, Any]:
        iterations = list(state.get("iterations", []))
        rejected = list(state.get("rejected_signatures", []))
        current = iterations[-1]
        prop = current["proposal"]
        proposal = Proposal(tool=prop["tool"], params=prop["params"])
        naive_mae = ctx.naive.selected.val_mae

        try:
            val_metrics = evaluate_on_validation(proposal, ctx.scenario.split, ctx.diagnostics)
            beat = val_metrics["mae"] < naive_mae  # strictly beat (no ties) — clarification
            current["val_result"] = {"val_metrics": val_metrics, "naive_val_mae": naive_mae}
            current["beat_naive"] = bool(beat)
            accepted = None
            if beat:
                accepted = {"proposal": prop, "val_result": current["val_result"]}
            elif prop["action_signature"] not in rejected:
                rejected.append(prop["action_signature"])
            return {"iterations": iterations, "rejected_signatures": rejected, "accepted": accepted}
        except InterventionError as exc:
            # Out-of-bounds / disallowed proposal: reject the signature, re-prompt (no validation score).
            current["val_result"] = {"rejected_reason": str(exc)}
            current["beat_naive"] = False
            if prop["action_signature"] not in rejected:
                rejected.append(prop["action_signature"])
            return {"iterations": iterations, "rejected_signatures": rejected, "accepted": None}

    return validation_node


def route_after_validation(state: AgentState) -> str:
    """Accepted → final; else loop unless budget exhausted."""
    if state.get("accepted"):
        return "final_evaluation"
    if len(state.get("iterations", [])) >= MAX_ITERATIONS:
        return "final_evaluation"
    return "react_decision"


def _best_proposal(state: AgentState) -> dict[str, Any]:
    """Pick the accepted proposal, else the best-validation-scoring generated proposal."""
    if state.get("accepted"):
        return state["accepted"]["proposal"]
    scored = [
        it
        for it in state.get("iterations", [])
        if it.get("val_result") and "val_metrics" in it["val_result"]
    ]
    if not scored:
        # Degenerate guard: no scored proposal at all — fall back to the first proposal.
        return state["iterations"][0]["proposal"]
    best = min(scored, key=lambda it: it["val_result"]["val_metrics"]["mae"])
    return best["proposal"]


def make_final_evaluation_node(ctx: RunContext):
    def final_evaluation_node(state: AgentState) -> dict[str, Any]:
        accepted = state.get("accepted")
        final_case = "accepted_beat_naive" if accepted else "best_proposal_no_beat"
        prop = _best_proposal(state)
        proposal = Proposal(tool=prop["tool"], params=prop["params"])

        # The ONLY place test data is read.
        agent_yhat, agent_test = evaluate_on_test(proposal, ctx.scenario.split, ctx.diagnostics)
        full_yhat, full_test = fit_full_history_test_forecast(ctx.scenario.split)
        naive_yhat, naive_test = fit_naive_test_forecast(ctx.scenario.split, ctx.naive.selected_window_start)

        final_candidate = {
            "label": f"agent:{prop['action_signature']}",
            "tool": prop["tool"],
            "params": prop["params"],
            "test_metrics": agent_test,
        }
        return {
            "final_candidate": final_candidate,
            "final_case": final_case,
            # Stash forecasts/metrics for run_poc to write artifacts (kept out of agent reasoning).
            "_final_eval": {
                "agent": {"yhat": agent_yhat.tolist(), "test_metrics": agent_test, "tool": prop["tool"]},
                "full_history_prophet": {"yhat": full_yhat.tolist(), "test_metrics": full_test},
                "naive_workflow": {
                    "yhat": naive_yhat.tolist(),
                    "test_metrics": naive_test,
                    "selected_window": f"window_start={ctx.naive.selected_window_start}",
                },
            },
        }

    return final_evaluation_node
