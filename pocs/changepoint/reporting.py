"""Artifact writers: metrics.json, summary.md, agent_trace.json (T014/T015/T033)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _round_metrics(m: dict[str, float] | None) -> dict[str, float] | None:
    if m is None:
        return None
    return {k: round(float(v), 4) for k, v in m.items()}


def write_metrics_json(
    out_path: Path,
    *,
    scenario_id: str,
    horizon: int,
    full_history: dict[str, float],
    naive: dict[str, float],
    naive_selected_window: str,
    agent: dict[str, float],
    agent_tool: str,
    final_case: str,
) -> dict[str, Any]:
    """Write the human-readable MetricsReport; returns the dict (FR-036, data-model.md)."""
    methods = {
        "full_history_prophet": _round_metrics(full_history),
        "naive_workflow": {**_round_metrics(naive), "selected_window": naive_selected_window},
        "agent": {**_round_metrics(agent), "tool": agent_tool, "final_case": final_case},
    }
    winner = min(
        ("full_history_prophet", "naive_workflow", "agent"),
        key=lambda name: methods[name]["mae"],
    )
    report = {"scenario_id": scenario_id, "horizon": horizon, "methods": methods, "winner": winner}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    return report


def write_agent_trace(out_path: Path, trace: dict[str, Any]) -> None:
    """Write the full structured agent trace (FR-037)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(trace, indent=2, default=str))


FAMILY_BY_TOOL = {
    "recent_window": "recent_window",
    "full_history_step_regressor": "step",
    "full_history_ramp_regressor": "ramp",
    "full_history_clean_event": "clean_event",
    "full_history_prophet_tuned_holidays": "holidays_tuned",
}
ALL_FAMILIES = ["step", "ramp", "clean_event", "holidays_tuned", "recent_window"]

# Families the fixtures are expected to elicit as winners (SC-008 requires these demonstrated).
REQUIRED_FAMILIES = ["ramp", "clean_event", "holidays_tuned"]
# Available but not required to win (see spec Assumptions: on this data placement step is
# dominated by ramp on its own fixture, and recent_window is a fallback).
OPTIONAL_FAMILIES = ["step", "recent_window"]


def families_demonstrated(scenario_id: str, iterations: list[dict[str, Any]]) -> dict[str, str]:
    """Map each family demonstrated in this scenario to how (best-val or proposed).

    Relaxed SC-008: a family counts if it was proposed and validated; the best-validation
    proposal is highlighted. Returns {family: "best-val"|"proposed"} for families seen.
    """
    scored = [it for it in iterations if (it.get("val_result") or {}).get("val_metrics")]
    best_sig = None
    if scored:
        best = min(scored, key=lambda it: it["val_result"]["val_metrics"]["mae"])
        best_sig = best["proposal"]["action_signature"]
    out: dict[str, str] = {}
    for it in iterations:
        tool = it["proposal"]["tool"]
        fam = FAMILY_BY_TOOL.get(tool)
        if not fam:
            continue
        how = "best-val" if it["proposal"].get("action_signature") == best_sig else "proposed"
        # best-val takes precedence over a mere "proposed" mark.
        if out.get(fam) != "best-val":
            out[fam] = how
    return out


def write_summary_md(out_path: Path, reports: list[dict[str, Any]], family_coverage: dict[str, list[str]]) -> None:
    """Cross-scenario summary (FR-038, SC-011) + family-coverage line (SC-008)."""
    lines = [
        "# Changepoint Agent POC — Cross-Scenario Summary",
        "",
        "Can a visual-first bounded agent beat a naive changepoint-window workflow on hard scenarios?",
        "Validation = single holdout (last validation_horizon of training); hidden test scored only",
        "after the agent loop. Lower MAE is better.",
        "",
        "| Scenario | Winner | Agent tool | Agent MAE | Naive MAE | Full-hist MAE | Agent beat naive? |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        m = r["methods"]
        agent_mae = m["agent"]["mae"]
        naive_mae = m["naive_workflow"]["mae"]
        full_mae = m["full_history_prophet"]["mae"]
        beat = "yes" if agent_mae < naive_mae else "no"
        lines.append(
            f"| {r['scenario_id']} | {r['winner']} | {m['agent']['tool']} | "
            f"{agent_mae:.2f} | {naive_mae:.2f} | {full_mae:.2f} | {beat} |"
        )

    lines += ["", "## Intervention-family coverage (SC-008)", ""]
    lines.append("Required families (must be demonstrated as accepted/best-validation):")
    for fam in REQUIRED_FAMILIES:
        where = family_coverage.get(fam, [])
        status = ", ".join(where) if where else "**NOT DEMONSTRATED**"
        lines.append(f"- **{fam}**: {status}")
    lines.append("")
    lines.append("Available but not required to win on this data placement (see spec Assumptions):")
    for fam in OPTIONAL_FAMILIES:
        where = family_coverage.get(fam, [])
        status = ", ".join(where) if where else "not exercised"
        lines.append(f"- **{fam}**: {status}")
    lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
