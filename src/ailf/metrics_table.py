"""Publication results table (LaTeX, booktabs) from run artifacts — not the live UI.

Aggregates per-scenario ``metrics.json`` files into a two-column-friendly ``booktabs`` table:
each scenario's hidden-test MAE for the agent, full-history Prophet, and naive baseline, the agent's
chosen tool, the winner (bolded), and the agent's % improvement over the naive baseline.

Reproducible from committed artifacts — no agent re-run, no API calls.

CLI:
    uv run python -m ailf.metrics_table reports/changepoint --out tables/results.tex
    uv run python -m ailf.metrics_table reports/changepoint --metric rmse --out tables/results_rmse.tex
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

_METHODS = ("agent", "full_history_prophet", "naive_workflow")
_METHOD_HEADERS = {
    "agent": "Agent",
    "full_history_prophet": "Full-hist.\\ Prophet",
    "naive_workflow": "Naive",
}
# Short, human-readable scenario labels (LaTeX-escaped) keyed by scenario_id; unknown ids fall back
# to a prettified form of the id.
_SCENARIO_LABELS = {
    "level_shift_loses_seasonality": "Level shift",
    "gradual_drift_loses_seasonality": "Gradual drift",
    "temporary_event_not_regime_change": "Temporary event",
    "many_temporary_events_long_history": "Many events",
    "prophet_prior_tuning_recurring_event": "Recurring event",
    "sustained_anomaly_block": "Sustained anomaly",
}
# Compact tool names for the table.
_TOOL_LABELS = {
    "recent_window": "recent window",
    "full_history_step_regressor": "step reg.",
    "full_history_ramp_regressor": "ramp reg.",
    "full_history_clean_event": "clean event",
    "full_history_prophet_tuned_holidays": "tuned holidays",
    "full_history_default": "default",
}


def _esc(text: str) -> str:
    """Escape the LaTeX-special characters that appear in our labels/ids."""
    return (
        text.replace("\\", r"\textbackslash{}")
        .replace("_", r"\_")
        .replace("%", r"\%")
        .replace("&", r"\&")
        .replace("#", r"\#")
    )


def _scenario_label(scenario_id: str) -> str:
    return _SCENARIO_LABELS.get(scenario_id) or _esc(scenario_id.replace("_", " ").title())


def collect_metrics(reports_dir: str | Path) -> list[dict]:
    """Load every ``<run>/metrics.json`` under ``reports_dir``, sorted by scenario id."""
    reports_dir = Path(reports_dir)
    rows: list[dict] = []
    for mp in sorted(reports_dir.glob("*/metrics.json")):
        rows.append(json.loads(mp.read_text()))
    if not rows:
        raise FileNotFoundError(f"no */metrics.json found under {reports_dir}")
    rows.sort(key=lambda m: m.get("scenario_id", ""))
    return rows


def _fmt(value: float | None, bold: bool) -> str:
    if value is None:
        return "--"
    s = f"{value:.2f}"
    return f"\\textbf{{{s}}}" if bold else s


def build_latex_table(
    runs: list[dict],
    *,
    metric: str = "mae",
    caption: str = (
        "Hidden-test forecast error by scenario (lower is better). "
        "Best per row in \\textbf{bold}; "
        "$\\Delta$ is the agent's improvement over the naive baseline."
    ),
    label: str = "tab:results",
) -> str:
    """Render a booktabs LaTeX table. ``metric`` is one of mae/rmse/wape/smape."""
    metric_u = metric.upper()
    lines: list[str] = []
    lines.append("% Requires \\usepackage{booktabs} in the preamble.")
    lines.append("\\begin{table}[t]")
    lines.append("  \\centering")
    lines.append(f"  \\caption{{{caption}}}")
    lines.append(f"  \\label{{{label}}}")
    lines.append("  \\small")
    lines.append("  \\begin{tabular}{l r r r l r}")
    lines.append("    \\toprule")
    lines.append(
        f"    Scenario & {_METHOD_HEADERS['agent']} ({metric_u}) & "
        f"{_METHOD_HEADERS['full_history_prophet']} & {_METHOD_HEADERS['naive_workflow']} & "
        "Agent tool & $\\Delta$ vs naive \\\\"
    )
    lines.append("    \\midrule")

    agent_wins = 0
    for m in runs:
        methods = m.get("methods", {})
        vals = {k: methods.get(k, {}).get(metric) for k in _METHODS}
        present = {k: v for k, v in vals.items() if isinstance(v, (int, float))}
        best_key = min(present, key=present.get) if present else None
        if best_key == "agent":
            agent_wins += 1

        agent_v = vals["agent"]
        naive_v = vals["naive_workflow"]
        if isinstance(agent_v, (int, float)) and isinstance(naive_v, (int, float)) and naive_v:
            delta_pct = (naive_v - agent_v) / naive_v * 100.0
            delta_str = f"{delta_pct:+.1f}\\%"
        else:
            delta_str = "--"

        tool = methods.get("agent", {}).get("tool", "")
        tool_label = _esc(_TOOL_LABELS.get(tool, tool))

        lines.append(
            f"    {_scenario_label(m.get('scenario_id', ''))} & "
            f"{_fmt(vals['agent'], best_key == 'agent')} & "
            f"{_fmt(vals['full_history_prophet'], best_key == 'full_history_prophet')} & "
            f"{_fmt(vals['naive_workflow'], best_key == 'naive_workflow')} & "
            f"{tool_label} & {delta_str} \\\\"
        )

    lines.append("    \\bottomrule")
    lines.append("  \\end{tabular}")
    lines.append(
        f"  % Agent wins {agent_wins}/{len(runs)} scenarios on hidden-test {metric_u}."
    )
    lines.append("\\end{table}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a booktabs LaTeX results table from run artifacts.")
    parser.add_argument("reports_dir", help="Directory holding <run>/metrics.json (e.g. reports/changepoint)")
    parser.add_argument("--metric", default="mae", choices=["mae", "rmse", "wape", "smape"])
    parser.add_argument("--out", default=None, help="Output .tex path (default: stdout)")
    args = parser.parse_args()

    runs = collect_metrics(args.reports_dir)
    tex = build_latex_table(runs, metric=args.metric)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(tex)
        print(f"wrote {out} ({len(runs)} scenarios)")
    else:
        print(tex)


if __name__ == "__main__":
    main()
