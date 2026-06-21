"""Run artifact writers: metrics.json, agent_trace.json, report.md (FR-036/FR-037, Principle VI).

All JSON goes through the strict ``to_json`` serializer (raises on non-JSON — Principle I), replacing
the POC's lossy ``default=str``. ``write_report_md`` is the per-run narrative explanation report
(Principle VI): baseline comparison, detected issues, accepted/best-val intervention with before/after
deltas vs naive, final recommendation, and the agent's stated limitations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ailf.core.events.leakage import to_json


def _round(m: dict[str, float] | None) -> dict[str, float] | None:
    return None if m is None else {k: round(float(v), 4) for k, v in m.items()}


def write_metrics_json(run_dir: Path, *, scenario_id: str, horizon: int, final_eval: dict[str, Any]) -> dict[str, Any]:
    """Write the human-readable metrics report for all three methods (FR-036)."""
    methods = {
        "full_history_prophet": _round(final_eval["full_history_prophet"]["test_metrics"]),
        "naive_workflow": {
            **_round(final_eval["naive_workflow"]["test_metrics"]),
            "selected_window": final_eval["naive_workflow"]["selected_window"],
        },
        "agent": {**_round(final_eval["agent"]["test_metrics"]), "tool": final_eval["agent"]["tool"]},
    }
    winner = min(
        ("full_history_prophet", "naive_workflow", "agent"), key=lambda n: methods[n]["mae"]
    )
    report = {"scenario_id": scenario_id, "horizon": horizon, "methods": methods, "winner": winner}
    (run_dir / "metrics.json").write_text(to_json(report, indent=2))
    return report


def write_agent_trace(run_dir: Path, trace: dict[str, Any]) -> None:
    """Write the full structured agent trace (FR-037) via the strict serializer."""
    (run_dir / "agent_trace.json").write_text(to_json(trace, indent=2))


def write_report_md(run_dir: Path, *, scenario_id: str, trace: dict[str, Any], metrics: dict[str, Any]) -> Path:
    """Write the per-run narrative explanation report (Constitution Principle VI)."""
    m = metrics["methods"]
    agent_mae = m["agent"]["mae"]
    naive_mae = m["naive_workflow"]["mae"]
    full_mae = m["full_history_prophet"]["mae"]
    delta_vs_naive = naive_mae - agent_mae
    visual = trace.get("visual") or {}
    final_case = trace.get("final_case", "?")
    chosen = trace.get("final_candidate", {})
    lines = [
        f"# Changepoint Agent Report — {scenario_id}",
        "",
        f"**Horizon:** {metrics['horizon']} steps · **Winner:** {metrics['winner']}",
        "",
        "## Baseline comparison (hidden-test MAE, lower is better)",
        "",
        "| Method | MAE | RMSE | WAPE | sMAPE |",
        "|---|---|---|---|---|",
        f"| full-history Prophet | {full_mae} | {m['full_history_prophet']['rmse']} | {m['full_history_prophet']['wape']} | {m['full_history_prophet']['smape']} |",
        f"| naive changepoint-window | {naive_mae} | {m['naive_workflow']['rmse']} | {m['naive_workflow']['wape']} | {m['naive_workflow']['smape']} |",
        f"| **agent** ({m['agent']['tool']}) | {agent_mae} | {m['agent']['rmse']} | {m['agent']['wape']} | {m['agent']['smape']} |",
        "",
        "## Detected issues (agent-visible diagnostics)",
        "",
        f"- Visual analysis enabled: {trace.get('visual_analysis_enabled')}",
        f"- Hidden diagnostics: {trace.get('hidden_diagnostics') or 'none'}",
        f"- Removed tools: {trace.get('removed_tools') or 'none'}",
    ]
    if visual.get("pattern_summary"):
        lines.append(f"- Visual pattern: {visual['pattern_summary']}")
    lines += [
        "",
        "## Recommended intervention",
        "",
        f"- **Tool:** `{chosen.get('tool')}` · params: `{chosen.get('params')}`",
        f"- **Acceptance:** {final_case} "
        + (
            f"(beat naive by {delta_vs_naive:.3f} MAE)"
            if final_case == "accepted_beat_naive"
            else f"(did NOT beat naive; carried best-validation proposal; agent−naive ΔMAE={agent_mae - naive_mae:+.3f})"
        ),
        "",
        "## Stated limitations / uncertainties",
        "",
    ]
    uncertainties = visual.get("uncertainties") or []
    if uncertainties:
        lines += [f"- {u}" for u in uncertainties]
    else:
        lines.append("- The agent reasoned from numeric diagnostics only (no visual uncertainties recorded).")
    lines += [
        "",
        "_Validation uses a single historical holdout; the hidden test was scored only after the "
        "agent loop completed. Metric deltas vs. naive are the decision criterion._",
        "",
    ]
    path = run_dir / "report.md"
    path.write_text("\n".join(lines))
    return path
