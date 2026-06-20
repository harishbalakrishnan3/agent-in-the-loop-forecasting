"""Changepoint agent POC entrypoint (T016 + T029).

Per scenario: build the split, detect changepoints, compute diagnostics, fit the two baselines,
render the training-only agent image, run the LangGraph agent (visual ∥ diagnostics → decision ↔
validation → final), then write metrics.json, forecast_comparison.png, agent_trace.json. After all
scenarios, write a cross-scenario summary.md.

Usage:
    uv run python -m pocs.changepoint.run_poc            # all scenarios
    uv run python -m pocs.changepoint.run_poc --scenario level_shift_loses_seasonality
    uv run python -m pocs.changepoint.run_poc --debug-plots
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from pocs.changepoint.baselines import full_history_prophet, naive_workflow
from pocs.changepoint.config import RUNS_DIR, load_config
from pocs.changepoint.detector import detect_changepoints
from pocs.changepoint.diagnostics import compute_diagnostics
from pocs.changepoint.graph.build import build_agent_graph
from pocs.changepoint.graph.nodes import RunContext
from pocs.changepoint.llm import build_react_model, build_visual_model
from pocs.changepoint.reporting import (
    families_demonstrated,
    write_agent_trace,
    write_metrics_json,
    write_summary_md,
)
from pocs.changepoint.scenarios import Scenario, load_all_scenarios, load_scenario
from pocs.changepoint.viz import render_agent_context, render_forecast_comparison


def _run_scenario(scenario: Scenario, run_dir: Path, config, *, debug_plots: bool) -> dict:
    sdir = run_dir / scenario.scenario_id
    sdir.mkdir(parents=True, exist_ok=True)
    split = scenario.split

    changepoints = detect_changepoints(split.train_df, n_changepoints_to_detect=scenario.n_changepoints_to_detect)
    diagnostics = compute_diagnostics(split.train_df, changepoints=changepoints, seasonal_period=scenario.seasonal_period)
    naive = naive_workflow(split, changepoints)
    _full = full_history_prophet(split)  # validation comparability (test computed at final stage)

    image_path = render_agent_context(split, "training history", sdir / "agent_context.png")

    ctx = RunContext(
        config=config,
        scenario=scenario,
        diagnostics=diagnostics,
        naive=naive,
        visual_model=build_visual_model(config),
        react_model=build_react_model(config),
        image_path=image_path,
    )
    app = build_agent_graph(ctx)
    final_state = app.invoke(
        {
            "scenario_id": scenario.scenario_id,
            "image_path": str(image_path),
            "seasonal_period": scenario.seasonal_period,
            "iterations": [],
            "rejected_signatures": [],
        },
        config={
            "run_name": f"changepoint-poc-{scenario.scenario_id}",
            "tags": ["changepoint-poc", scenario.scenario_id],
            "recursion_limit": 50,
        },
    )

    fe = final_state["_final_eval"]
    metrics_by_method = {
        "full_history_prophet": fe["full_history_prophet"]["test_metrics"],
        "naive_workflow": fe["naive_workflow"]["test_metrics"],
        "agent": fe["agent"]["test_metrics"],
    }

    report = write_metrics_json(
        sdir / "metrics.json",
        scenario_id=scenario.scenario_id,
        horizon=split.test_horizon,
        full_history=fe["full_history_prophet"]["test_metrics"],
        naive=fe["naive_workflow"]["test_metrics"],
        naive_selected_window=fe["naive_workflow"]["selected_window"],
        agent=fe["agent"]["test_metrics"],
        agent_tool=fe["agent"]["tool"],
        final_case=final_state["final_case"],
    )

    render_forecast_comparison(
        split,
        title=f"Forecast comparison — {scenario.title}",
        full_history_yhat=np.array(fe["full_history_prophet"]["yhat"]),
        naive_yhat=np.array(fe["naive_workflow"]["yhat"]),
        agent_yhat=np.array(fe["agent"]["yhat"]),
        agent_label=fe["agent"]["tool"],
        metrics_by_method=metrics_by_method,
        out_path=sdir / "forecast_comparison.png",
    )

    trace = {
        "scenario_id": scenario.scenario_id,
        "seed": config.seed,
        "model_ids": {"visual": config.visual_model_id, "react": config.react_model_id},
        "visual": final_state.get("visual", {}),
        "diagnostics": diagnostics.to_agent_dict(),
        "naive_summary": naive.summary_dict(),
        "iterations": final_state.get("iterations", []),
        "rejected_signatures": final_state.get("rejected_signatures", []),
        "accepted": final_state.get("accepted"),
        "final_candidate": final_state.get("final_candidate"),
        "final_case": final_state.get("final_case"),
    }
    write_agent_trace(sdir / "agent_trace.json", trace)

    if debug_plots:
        _write_debug_plot(scenario, changepoints, sdir / "_debug")

    print(f"  {scenario.scenario_id}: winner={report['winner']} agent_tool={fe['agent']['tool']} "
          f"agent_mae={metrics_by_method['agent']['mae']:.2f} naive_mae={metrics_by_method['naive_workflow']['mae']:.2f}")
    return report, final_state.get("iterations", [])


def _write_debug_plot(scenario: Scenario, changepoints, debug_dir: Path) -> None:
    """Developer-only diagnostics plot — never shown to any agent node (FR-039)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    debug_dir.mkdir(parents=True, exist_ok=True)
    split = scenario.split
    train = split.train_df
    fig, ax = plt.subplots(figsize=(13, 5))
    ax.plot(train["ds"], train["y"], color="#1f77b4", linewidth=1.0, label="train")
    for c in changepoints.changepoints:
        ax.axvline(train["ds"].iloc[c.index], color="#d62728", linestyle="--", alpha=0.6)
    ax.set_title(f"[debug] {scenario.scenario_id} detected changepoints")
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(debug_dir / f"{scenario.scenario_id}_diagnostics.png", dpi=120)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the changepoint agent POC.")
    parser.add_argument("--scenario", help="Run a single scenario by id (default: all five)")
    parser.add_argument("--debug-plots", action="store_true", help="Write developer-only diagnostics plots")
    args = parser.parse_args()

    config = load_config()
    random.seed(config.seed)
    np.random.seed(config.seed)

    scenarios = [load_scenario(args.scenario)] if args.scenario else load_all_scenarios()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS_DIR / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Run dir: {run_dir}")

    reports = []
    family_coverage: dict[str, list[str]] = {}
    for scenario in scenarios:
        report, iterations = _run_scenario(scenario, run_dir, config, debug_plots=args.debug_plots)
        reports.append(report)
        # Relaxed SC-008: credit each family demonstrated (best-val or merely proposed).
        for fam, how in families_demonstrated(scenario.scenario_id, iterations).items():
            family_coverage.setdefault(fam, []).append(f"{scenario.scenario_id} ({how})")

    write_summary_md(run_dir / "summary.md", reports, family_coverage)
    print(f"Summary: {run_dir / 'summary.md'}")


if __name__ == "__main__":
    main()
