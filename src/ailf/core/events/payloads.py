"""Per-stage event payload builders (FR-027, contracts/event_contract.md).

Each builder returns the documented payload SHAPE for its stage, sourced from agent-facing / filtered
views so pre-final payloads carry no hidden-test or audit data (FR-029). Test metrics appear only in
the final_evaluation / run_complete payloads.
"""

from __future__ import annotations

from typing import Any


def config_resolved(effective_config: dict, *, hidden_diagnostics: list[str], removed_tools: list[str], visual_enabled: bool) -> dict[str, Any]:
    return {
        "effective_config": effective_config,
        "hidden_diagnostics": hidden_diagnostics,
        "removed_tools": removed_tools,
        "visual_analysis_enabled": visual_enabled,
    }


def split_built(provenance: dict) -> dict[str, Any]:
    return {"provenance": provenance}


def changepoint_detection(detected: list[dict]) -> dict[str, Any]:
    return {"n_detected": len(detected), "detected": [{"index": d["index"], "ds": str(d.get("ds", "")), "trend_delta": d["trend_delta"]} for d in detected]}


def baseline_full_history_prophet(val_metrics: dict) -> dict[str, Any]:
    return {"val_metrics": val_metrics}  # no test metrics pre-final


def baseline_naive_workflow(naive_summary: dict) -> dict[str, Any]:
    return {
        "candidates": [
            {"label": c["label"], "val_metrics": c["val_metrics"], "window_start": c.get("extra", {}).get("window_start")}
            for c in naive_summary.get("candidates", [])
        ],
        "selected_window_start": naive_summary.get("selected_window_start"),
    }


def diagnostics_computed(filtered_diagnostics: dict, *, hidden: list[str]) -> dict[str, Any]:
    return {"diagnostics": filtered_diagnostics, "hidden": hidden}


def visual_inspection(visual: dict, *, image_ref: str | None) -> dict[str, Any]:
    return {**visual, "image_ref": image_ref}


def decision_iteration(iteration: dict, *, menu: list[str]) -> dict[str, Any]:
    prop = iteration["proposal"]
    return {
        "i": iteration["i"],
        "proposal": {
            "tool": prop["tool"],
            "params": prop["params"],
            "action_signature": prop["action_signature"],
            "rationale": prop.get("rationale", ""),
            "expected_effect": prop.get("expected_effect", ""),
        },
        "menu": menu,
    }


def validation_outcome(iteration: dict) -> dict[str, Any]:
    val = iteration.get("val_result") or {}
    return {
        "i": iteration["i"],
        "action_signature": iteration["proposal"]["action_signature"],
        "beat_naive": bool(iteration.get("beat_naive")),
        "rejected_reason": val.get("rejected_reason"),
        # NOTE: val_metrics intentionally OMITTED — the agent never sees the score (FR-025).
    }


def final_evaluation(final_case: str, chosen: dict, test_metrics_by_method: dict) -> dict[str, Any]:
    return {
        "final_case": final_case,
        "chosen": {"tool": chosen.get("tool"), "params": chosen.get("params")},
        "test_metrics_by_method": test_metrics_by_method,
    }


def run_complete(*, winner: str, artifacts: list[str], run_dir: str) -> dict[str, Any]:
    return {"winner": winner, "artifacts": artifacts, "run_dir": run_dir}
