"""Changepoint pipeline entry point — single-scenario run (FR-001..005, research Decision 17).

Wires the changepoint detector/diagnostics/tools/prompts into the shared core agent loop.
Per-scenario flow: seed FIRST → deterministic prelude (detect → baselines → diagnostics) → build the
config-shaped GraphSpec + RunContext → invoke the core engine → write artifacts.

Run with:
    uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality
    uv run python -m ailf.pipelines.changepoint.pipeline --scenario <id> --override '{"visual_analysis_enabled": false}'
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np

from ailf.core.agent.engine import build_agent_graph
from ailf.core.agent.runtime import RunContext
from ailf.core.backtest.split import resolve_split
from ailf.core.config.loader import load_config_yaml
from ailf.core.config.resolve import resolve_config
from ailf.core.config.schema import ConfigOverride
from ailf.core.models.llm import ModelWrapper, build_decision_model, build_visual_model
from ailf.core.prompts.loader import load_prompt
from ailf.core.reporting.artifacts import write_agent_trace, write_metrics_json, write_report_md
from ailf.core.reporting.run_dir import create_run_dir, stamp_effective_config
from ailf.pipelines.changepoint.baselines import full_history_prophet, naive_workflow
from ailf.pipelines.changepoint.datasets import golden_split_from_metadata, load_metadata
from ailf.pipelines.changepoint.detector import detect_changepoints
from ailf.pipelines.changepoint.diagnostics import DiagnosticsBundle, compute_diagnostics
from ailf.pipelines.changepoint.interventions import register_changepoint_registry, structural_tool_names
from ailf.pipelines.changepoint.scenarios import load_scenario
from ailf.pipelines.changepoint.schemas import InterventionChoice, VisualInspectionResult
from ailf.pipelines.changepoint.viz import render_agent_context, render_forecast_comparison

_CONFIG_PATH = Path(__file__).resolve().parent / "config.yaml"
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def _render_menu(registry) -> str:
    """Render the enabled-tools menu for the decision prompt's {{tool_menu}} placeholder."""
    lines = []
    for i, spec in enumerate(registry.menu(), 1):
        params = "; ".join(
            f"{p['name']} ∈ {p['allowed']}" if p["allowed"] else f"{p['name']}"
            for p in spec["params"]
        ) or "(no params)"
        lines.append(f"{i}. `{spec['name']}` — {spec['description']} params: {params}")
    return "\n".join(lines)


def run_scenario(
    scenario_id: str,
    *,
    override: ConfigOverride | None = None,
    model_wrappers: tuple | None = None,
    reports_root: Path | None = None,
) -> dict:
    """Execute one scenario end-to-end and write artifacts; returns the metrics report dict."""
    # 1. Resolve config (merge → validate → lockstep).
    defaults = load_config_yaml(_CONFIG_PATH)
    cfg = resolve_config(
        defaults,
        override,
        diagnostics_field_names=set(DiagnosticsBundle.field_names()),
        structural_tool_names=set(structural_tool_names()),
    )

    # 2. Seed FIRST (research Decision 17) — before any Prophet fit.
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    # 3. Resolve split (golden default or override) and load the scenario on it.
    meta = next(m for m in load_metadata()["scenarios"] if m["scenario_id"] == scenario_id)
    scenario_probe = load_scenario(scenario_id)
    n_rows = len(scenario_probe.split.ds)
    golden = golden_split_from_metadata(meta, n_rows)
    resolved = resolve_split(cfg.split, n_rows=n_rows, golden=golden)
    scenario = load_scenario(scenario_id, resolved=resolved)
    split = scenario.split

    run_id = f"{scenario_id}-{cfg.seed}"
    run_dir = create_run_dir(run_id, root=reports_root)

    # 4. Deterministic prelude: detect → baselines → diagnostics.
    cps = detect_changepoints(split.train_df, n_changepoints_to_detect=scenario.n_changepoints_to_detect)
    naive = naive_workflow(split, cps)
    _ = full_history_prophet(split)  # comparability (test computed at final stage)
    diagnostics = compute_diagnostics(split.train_df, changepoints=cps, seasonal_period=scenario.seasonal_period)

    # 5. Registry projection + prompts shaped by config.
    registry = register_changepoint_registry().for_run(set(cfg.enabled_tools))
    menu = _render_menu(registry)
    if cfg.visual_analysis_enabled:
        decision_prompt = load_prompt(_PROMPT_DIR, "react_decision", 2, fill={"tool_menu": menu})
        decision_prompt_id = "react_decision_v2"
        visual_prompt = load_prompt(_PROMPT_DIR, "visual_inspection", 1)
        image_path = render_agent_context(split, "training history", run_dir / "agent_context.png")
    else:
        decision_prompt = load_prompt(_PROMPT_DIR, "react_decision_diagnostics_only", 1, fill={"tool_menu": menu})
        decision_prompt_id = "react_decision_diagnostics_only_v1"
        visual_prompt = None
        image_path = None

    # 6. Models (real wrappers unless injected for tests).
    if model_wrappers is not None:
        visual_model, decision_model = model_wrappers
    else:
        visual_model = ModelWrapper(
            build_visual_model(cfg.models.visual_model_id, cfg.models.aws_region), cfg.models.visual_model_id
        )
        decision_model = ModelWrapper(
            build_decision_model(cfg.models.decision_model_id, cfg.models.aws_region), cfg.models.decision_model_id
        )

    hidden = sorted(set(DiagnosticsBundle.field_names()) - set(cfg.enabled_diagnostics))
    removed = sorted(set(structural_tool_names()) - set(cfg.enabled_tools))

    ctx = RunContext(
        run_id=run_id, scenario_id=scenario_id,
        visual_model=visual_model, decision_model=decision_model,
        visual_model_id=cfg.models.visual_model_id, decision_model_id=cfg.models.decision_model_id,
        split=split, full_diagnostics=diagnostics, naive=naive, tool_registry=registry,
        visual_enabled=cfg.visual_analysis_enabled,
        enabled_diagnostics=frozenset(cfg.enabled_diagnostics),
        image_path=image_path, emitter=None,
        decision_prompt=decision_prompt, visual_prompt=visual_prompt,
        visual_schema=VisualInspectionResult, decision_schema=InterventionChoice,
        prompt_ids={"decision": decision_prompt_id, "visual": "visual_inspection_v1" if visual_prompt else None},
    )

    # 7. Invoke the core engine.
    app = build_agent_graph(ctx)
    final_state = app.invoke(
        {"scenario_id": scenario_id, "image_path": str(image_path) if image_path else "",
         "seasonal_period": scenario.seasonal_period, "iterations": [], "rejected_signatures": []},
        config={"recursion_limit": 50},
    )

    # 8. Write artifacts.
    fe = final_state["_final_eval"]
    stamp_effective_config(
        run_dir,
        effective_config=cfg.to_dict(),
        split_provenance=resolved.provenance.to_dict(),
        seed=cfg.seed,
    )
    metrics_report = write_metrics_json(
        run_dir, scenario_id=scenario_id, horizon=split.test_horizon, final_eval=fe
    )
    trace = {
        "scenario_id": scenario_id,
        "seed": cfg.seed,
        "visual_analysis_enabled": cfg.visual_analysis_enabled,
        "hidden_diagnostics": hidden,
        "removed_tools": removed,
        "split_provenance": resolved.provenance.to_dict(),
        "prompt_ids": ctx.prompt_ids,
        "model_ids": {"visual": cfg.models.visual_model_id, "decision": cfg.models.decision_model_id},
        "visual": final_state.get("visual", {}),
        "diagnostics": diagnostics.to_agent_dict(),
        "naive_summary": naive.summary_dict(),
        "iterations": final_state.get("iterations", []),
        "rejected_signatures": final_state.get("rejected_signatures", []),
        "accepted": final_state.get("accepted"),
        "final_candidate": final_state.get("final_candidate"),
        "final_case": final_state.get("final_case"),
    }
    write_agent_trace(run_dir, trace)
    write_report_md(run_dir, scenario_id=scenario_id, trace=trace, metrics=metrics_report)
    render_forecast_comparison(
        split,
        title=f"Forecast comparison — {scenario.title}",
        full_history_yhat=np.array(fe["full_history_prophet"]["yhat"]),
        naive_yhat=np.array(fe["naive_workflow"]["yhat"]),
        agent_yhat=np.array(fe["agent"]["yhat"]),
        agent_label=fe["agent"]["tool"],
        metrics_by_method={
            "full_history_prophet": fe["full_history_prophet"]["test_metrics"],
            "naive_workflow": fe["naive_workflow"]["test_metrics"],
            "agent": fe["agent"]["test_metrics"],
        },
        out_path=run_dir / "forecast_comparison.png",
    )
    print(f"  {scenario_id}: winner={metrics_report['winner']} agent_tool={fe['agent']['tool']} "
          f"run_dir={run_dir}")
    return metrics_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the changepoint agent for one scenario.")
    parser.add_argument("--scenario", required=True, help="Scenario id to run")
    parser.add_argument("--override", help="JSON config override (same shape as config.yaml)")
    args = parser.parse_args()
    override = ConfigOverride.from_dict(json.loads(args.override)) if args.override else None
    run_scenario(args.scenario, override=override)


if __name__ == "__main__":
    main()
