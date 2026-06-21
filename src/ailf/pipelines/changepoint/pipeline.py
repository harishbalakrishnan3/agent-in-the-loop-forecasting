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

from dotenv import load_dotenv

load_dotenv()

import numpy as np
import pandas as pd

from ailf.core.agent.engine import build_agent_graph
from ailf.core.agent.runtime import RunContext
from ailf.core.backtest.split import resolve_split
from ailf.core.config.loader import load_config_yaml
from ailf.core.config.resolve import resolve_config
from ailf.core.config.schema import ConfigOverride
from ailf.core.events import payloads as ev
from ailf.core.events.emitter import EventEmitter, NullEmitter
from ailf.core.events.sink import FileEventSink
from ailf.core.events.stages import StageId, StageStatus
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


def _render_param(p: dict) -> str:
    """One param's agent-facing description: its bounded set, or a kind-specific format hint.

    Enum/grid params carry an ``allowed`` set; ``block_list`` has none, so without a hint the menu
    rendered just the bare word ``blocks`` and the agent had no way to learn the accepted shape
    (it echoed candidate_event_blocks objects back and got bounds-rejected). Advertise both forms.
    """
    if p["allowed"]:
        return f"{p['name']} ∈ {p['allowed']}"
    if p["kind"] == "block_list":
        return (
            f'{p["name"]} ∈ "all_closed" | a list selecting candidate_event_blocks '
            "(each an integer index, or a {start_ds,end_ds} / {start,end} block dict)"
        )
    return f"{p['name']}"


def _render_menu(registry) -> str:
    """Render the enabled-tools menu for the decision prompt's {{tool_menu}} placeholder."""
    lines = []
    for i, spec in enumerate(registry.menu(), 1):
        params = "; ".join(_render_param(p) for p in spec["params"]) or "(no params)"
        lines.append(f"{i}. `{spec['name']}` — {spec['description']} params: {params}")
    return "\n".join(lines)


def _series_split_from_df(
    df: "pd.DataFrame",
    split_ratio: float = 0.8,
    val_ratio: float = 0.1,
) -> "SeriesSplit":
    """Build a SeriesSplit directly from an arbitrary DataFrame (no metadata required).

    Used for pocs/data/ CSVs that are not registered as golden scenarios (§14i).

    Split: ``train_ratio`` for fit+val, ``test_ratio = 1 - train_ratio - val_ratio``.
    ``val_ratio`` is taken from inside the train portion so the agent sees only training data.
    """
    from ailf.core.backtest.split import ResolvedSplit  # noqa: PLC0415
    from ailf.pipelines.changepoint.scenarios import SeriesSplit  # noqa: PLC0415

    n = len(df)
    test_ratio = 1.0 - split_ratio
    # Distribute the split_ratio between train (fit) and val
    actual_val_ratio = min(val_ratio, split_ratio - 0.05)  # guard: keep ≥5% for train fit
    actual_train_ratio = split_ratio - actual_val_ratio

    test_rows = max(1, int(test_ratio * n))
    val_rows  = max(1, int(actual_val_ratio * n))
    train_rows = n - test_rows - val_rows
    if train_rows < 1:
        raise ValueError(
            f"split_ratio={split_ratio} leaves no training rows for n={n} rows. "
            "Increase the split ratio."
        )
    resolved = ResolvedSplit.from_lengths(
        train_rows=train_rows,
        val_rows=val_rows,
        test_rows=test_rows,
        source="override",
        units="ratios",
        requested={"train_ratio": split_ratio, "val_ratio": actual_val_ratio, "test_ratio": test_ratio},
        rounding_rule="floor_test_val_train_absorbs",
        n_rows=n,
    )
    return SeriesSplit(
        ds=df["ds"].reset_index(drop=True),
        y=df["y"].astype(float).reset_index(drop=True),
        resolved=resolved,
    )


def run_scenario(
    scenario_id: str,
    *,
    override: ConfigOverride | None = None,
    model_wrappers: tuple | None = None,
    reports_root: Path | None = None,
    emit_events: bool = True,
    series_df: "pd.DataFrame | None" = None,
    split_ratio: float = 0.8,
    seasonal_period: int = 365,
    n_changepoints_to_detect: int = 3,
) -> dict:
    """Execute one scenario end-to-end and write artifacts; returns the metrics report dict.

    When ``series_df`` is provided the registered metadata lookup is bypassed and the split
    is built directly from the DataFrame using ``split_ratio`` (§14i).  This enables pocs/data/
    CSVs (e.g. sec9_*, sec10_*) to be used without golden scenario fixtures.

    ``seasonal_period`` and ``n_changepoints_to_detect`` are used only when ``series_df`` is set.
    """
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

    # 3. Resolve split and load the scenario.
    if series_df is not None:
        # §14i: arbitrary CSV path — bypass metadata, build split from DataFrame
        split = _series_split_from_df(series_df, split_ratio=split_ratio)
        # Build a minimal Scenario-like object; title uses scenario_id
        from ailf.pipelines.changepoint.scenarios import Scenario  # noqa: PLC0415
        scenario = Scenario(
            scenario_id=scenario_id,
            title=scenario_id,
            split=split,
            n_changepoints_to_detect=n_changepoints_to_detect,
            seasonal_period=seasonal_period,
        )
    else:
        meta = next(m for m in load_metadata()["scenarios"] if m["scenario_id"] == scenario_id)
        scenario_probe = load_scenario(scenario_id)
        n_rows = len(scenario_probe.split.ds)
        golden = golden_split_from_metadata(meta, n_rows)
        resolved = resolve_split(cfg.split, n_rows=n_rows, golden=golden)
        scenario = load_scenario(scenario_id, resolved=resolved)
    split = scenario.split

    run_id = f"{scenario_id}-{cfg.seed}"
    run_dir = create_run_dir(run_id, root=reports_root)

    hidden = sorted(set(DiagnosticsBundle.field_names()) - set(cfg.enabled_diagnostics))
    removed = sorted(set(structural_tool_names()) - set(cfg.enabled_tools))

    # Emitter: every run step emits a typed event to the file sink (FR-026..032). The deterministic
    # prelude is emitted SEQUENTIALLY by this single-threaded driver before graph invocation; the
    # in-graph stages are reconstructed from final_state after invoke (no seq-race — FR-028).
    if emit_events:
        emitter = EventEmitter(run_id, [FileEventSink(run_dir / "events.jsonl")], payload_dir=run_dir / "event_payloads")
    else:
        emitter = NullEmitter()

    emitter.emit(
        StageId.CONFIG_RESOLVED,
        StageStatus.COMPLETE,
        ev.config_resolved(cfg.to_dict(), hidden_diagnostics=hidden, removed_tools=removed, visual_enabled=cfg.visual_analysis_enabled),
    )
    emitter.emit(StageId.SPLIT_BUILT, StageStatus.COMPLETE, ev.split_built(split.resolved.provenance.to_dict()))

    # 4. Deterministic prelude: detect → baselines → diagnostics (each emits).
    with emitter.stage(StageId.CHANGEPOINT_DETECTION) as p:
        cps = detect_changepoints(split.train_df, n_changepoints_to_detect=scenario.n_changepoints_to_detect)
        detected = [{"index": c.index, "ds": str(c.ds.date()), "trend_delta": float(c.trend_delta)} for c in cps.changepoints]
        p.update(ev.changepoint_detection(detected))
    with emitter.stage(StageId.BASELINE_FULL_HISTORY_PROPHET) as p:
        full = full_history_prophet(split)
        p.update(ev.baseline_full_history_prophet(full.val_metrics))
    with emitter.stage(StageId.BASELINE_NAIVE_WORKFLOW) as p:
        naive = naive_workflow(split, cps)
        p.update(ev.baseline_naive_workflow(naive.summary_dict()))
    with emitter.stage(StageId.DIAGNOSTICS_COMPUTED) as p:
        diagnostics = compute_diagnostics(split.train_df, changepoints=cps, seasonal_period=scenario.seasonal_period)
        p.update(ev.diagnostics_computed(diagnostics.to_agent_dict(cfg.enabled_diagnostics), hidden=hidden))

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
            build_visual_model(cfg.models.visual_model_id, cfg.models.aws_region, llm_provider=cfg.models.llm_provider),
            cfg.models.visual_model_id,
        )
        decision_model = ModelWrapper(
            build_decision_model(cfg.models.decision_model_id, cfg.models.aws_region, llm_provider=cfg.models.llm_provider),
            cfg.models.decision_model_id,
        )

    ctx = RunContext(
        run_id=run_id, scenario_id=scenario_id,
        visual_model=visual_model, decision_model=decision_model,
        visual_model_id=cfg.models.visual_model_id, decision_model_id=cfg.models.decision_model_id,
        split=split, full_diagnostics=diagnostics, naive=naive, tool_registry=registry,
        visual_enabled=cfg.visual_analysis_enabled,
        enabled_diagnostics=frozenset(cfg.enabled_diagnostics),
        image_path=image_path, emitter=emitter,
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

    # 7b. Emit the in-graph stages, reconstructed from final_state (single-threaded, post-invoke).
    menu_names = sorted(registry.allowed_names())
    if cfg.visual_analysis_enabled and final_state.get("visual"):
        emitter.emit(
            StageId.VISUAL_INSPECTION,
            StageStatus.COMPLETE,
            ev.visual_inspection(final_state["visual"], image_ref="agent_context.png"),
            concurrency_group="visual_diagnostics",
        )
    for iteration in final_state.get("iterations", []):
        emitter.emit(StageId.DECISION_ITERATION, StageStatus.COMPLETE, ev.decision_iteration(iteration, menu=menu_names))
        emitter.emit(StageId.VALIDATION_OUTCOME, StageStatus.COMPLETE, ev.validation_outcome(iteration))

    # 8. Write artifacts.
    fe = final_state["_final_eval"]
    stamp_effective_config(
        run_dir,
        effective_config=cfg.to_dict(),
        split_provenance=split.resolved.provenance.to_dict(),
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
        "split_provenance": split.resolved.provenance.to_dict(),
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

    # §Forecasting 4/5: save forecast CSV — training region + forecast region in one file
    # so Streamlit can render a continuous zoom-in/out/pan chart.
    # Columns: ds, y_actual (NaN in forecast region), region ("train"|"forecast"),
    #          yhat_full_history, yhat_naive, yhat_agent (NaN in training region).
    try:
        train_hist = split.train_df.copy()
        test_hist  = split.test_df.copy()
        n_test     = len(test_hist)

        # Training region: actual values, NaN for forecast yhats
        _nan = float("nan")
        train_rows: list[dict] = []
        for _, row in train_hist.iterrows():
            train_rows.append({
                "ds":               row["ds"].strftime("%Y-%m-%d"),
                "y_actual":         round(float(row["y"]), 6),
                "region":           "train",
                "yhat_full_history": _nan,
                "yhat_naive":        _nan,
                "yhat_agent":        _nan,
            })

        # Forecast region: NaN for y_actual, actual yhat values
        fh_yhat = [round(float(v), 6) for v in fe["full_history_prophet"]["yhat"][:n_test]]
        nw_yhat = [round(float(v), 6) for v in fe["naive_workflow"]["yhat"][:n_test]]
        ag_yhat = [round(float(v), 6) for v in fe["agent"]["yhat"][:n_test]]

        fc_rows: list[dict] = []
        for i, (_, row) in enumerate(test_hist.iterrows()):
            fc_rows.append({
                "ds":               row["ds"].strftime("%Y-%m-%d"),
                "y_actual":         round(float(row["y"]), 6),  # keep actuals for comparison
                "region":           "forecast",
                "yhat_full_history": fh_yhat[i] if i < len(fh_yhat) else _nan,
                "yhat_naive":        nw_yhat[i] if i < len(nw_yhat) else _nan,
                "yhat_agent":        ag_yhat[i] if i < len(ag_yhat) else _nan,
            })

        csv_df = pd.DataFrame(train_rows + fc_rows)
        csv_path = run_dir / "forecast_comparison.csv"
        csv_df.to_csv(csv_path, index=False)
    except Exception as _csv_exc:
        # Non-fatal: PNG already written; log and continue.
        print(f"  [warn] forecast_comparison.csv not written: {_csv_exc}")

    # 9. Final-evaluation + run-complete events (test metrics first appear here — FR-029).
    emitter.emit(
        StageId.FINAL_EVALUATION,
        StageStatus.COMPLETE,
        ev.final_evaluation(
            final_state.get("final_case", ""),
            final_state.get("final_candidate", {}),
            {
                "full_history_prophet": fe["full_history_prophet"]["test_metrics"],
                "naive_workflow": fe["naive_workflow"]["test_metrics"],
                "agent": fe["agent"]["test_metrics"],
            },
        ),
    )
    artifacts = [p.name for p in sorted(run_dir.glob("*")) if p.is_file()]
    emitter.emit(
        StageId.RUN_COMPLETE,
        StageStatus.COMPLETE,
        ev.run_complete(winner=metrics_report["winner"], artifacts=artifacts, run_dir=str(run_dir)),
    )

    print(f"  {scenario_id}: winner={metrics_report['winner']} agent_tool={fe['agent']['tool']} "
          f"run_dir={run_dir}")
    return {**metrics_report, "run_id": run_id, "final_eval": fe}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the changepoint agent for one scenario.")
    parser.add_argument("--scenario", required=True, help="Scenario id to run")
    parser.add_argument("--override", help="JSON config override (same shape as config.yaml)")
    args = parser.parse_args()
    override = ConfigOverride.from_dict(json.loads(args.override)) if args.override else None
    run_scenario(args.scenario, override=override)


if __name__ == "__main__":
    main()
