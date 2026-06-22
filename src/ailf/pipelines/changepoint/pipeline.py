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
from ailf.core.config.resolve import (
    LLM_PROVIDER_UNCONFIGURED,
    NO_PROVIDER_MESSAGE,
    ConfigError,
    resolve_config,
)
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


_SPLIT_TOLERANCE = 1e-6


def _series_split_from_df(
    df: "pd.DataFrame",
    *,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
) -> "SeriesSplit":
    """Build a SeriesSplit directly from an arbitrary DataFrame (no metadata required).

    Used for custom-CSV runs (§14i) and the streamlined UI. Honors three explicit fractions that
    must sum to 1 (within tolerance); ``val`` is taken from inside the training portion so the agent
    still sees only training data. Rounding: floor test and val, train absorbs the remainder; each
    segment must end up with >= 1 row.
    """
    from ailf.core.backtest.split import ResolvedSplit  # noqa: PLC0415
    from ailf.pipelines.changepoint.scenarios import SeriesSplit  # noqa: PLC0415

    total = train_ratio + val_ratio + test_ratio
    if abs(total - 1.0) > _SPLIT_TOLERANCE:
        raise ValueError(
            f"train/val/test fractions must sum to 1.0 (got {total:.6f}: "
            f"train={train_ratio}, val={val_ratio}, test={test_ratio})."
        )

    n = len(df)
    test_rows = max(1, int(test_ratio * n))
    val_rows  = max(1, int(val_ratio * n))
    train_rows = n - test_rows - val_rows
    if train_rows < 1:
        raise ValueError(
            f"split train={train_ratio}/val={val_ratio}/test={test_ratio} leaves no training rows "
            f"for n={n} rows — each of train/val/test needs at least 1 row."
        )
    resolved = ResolvedSplit.from_lengths(
        train_rows=train_rows,
        val_rows=val_rows,
        test_rows=test_rows,
        source="override",
        units="ratios",
        requested={"train_ratio": train_ratio, "val_ratio": val_ratio, "test_ratio": test_ratio},
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
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seasonal_period: int = 365,
    n_changepoints_to_detect: int = 3,
    extra_sinks: "list | None" = None,
    anthropic_api_key: str | None = None,
) -> dict:
    """Execute one scenario end-to-end and write artifacts; returns the metrics report dict.

    When ``series_df`` is provided the registered metadata lookup is bypassed and the split is built
    directly from the DataFrame using the three ``train_ratio``/``val_ratio``/``test_ratio`` fractions
    (which must sum to 1). This enables custom-CSV runs and the streamlined UI without golden fixtures.

    ``train_ratio``/``val_ratio``/``test_ratio``, ``seasonal_period`` and ``n_changepoints_to_detect``
    are used only when ``series_df`` is set.

    ``anthropic_api_key``, when supplied, forces the Anthropic provider and is threaded explicitly to
    the model clients (a bring-your-own-key UI session) — no process-global env mutation, so it's
    safe under concurrent users on a shared host.
    """
    # 1. Resolve config (merge → validate → lockstep).
    defaults = load_config_yaml(_CONFIG_PATH)
    cfg = resolve_config(
        defaults,
        override,
        diagnostics_field_names=set(DiagnosticsBundle.field_names()),
        structural_tool_names=set(structural_tool_names()),
        anthropic_api_key=anthropic_api_key,
    )

    # 2. Seed FIRST (research Decision 17) — before any Prophet fit.
    random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    # 3. Resolve split and load the scenario.
    if series_df is not None:
        # §14i: arbitrary CSV path — bypass metadata, build split from DataFrame
        split = _series_split_from_df(
            series_df, train_ratio=train_ratio, val_ratio=val_ratio, test_ratio=test_ratio
        )
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
        sinks = [FileEventSink(run_dir / "events.jsonl")]
        if extra_sinks:
            sinks.extend(extra_sinks)  # e.g. the UI's QueueEventSink for live in-process streaming
        emitter = EventEmitter(run_id, sinks, payload_dir=run_dir / "event_payloads")
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
        # Real run: a provider MUST be configured. Fail fast with a clear message BEFORE any model
        # call (FR-029) — this is the one place that needs credentials, so the check lives here
        # rather than in config resolution (which runs credential-free in the test suite).
        if cfg.models.llm_provider == LLM_PROVIDER_UNCONFIGURED:
            raise ConfigError(NO_PROVIDER_MESSAGE)
        visual_model = ModelWrapper(
            build_visual_model(
                cfg.models.visual_model_id, cfg.models.aws_region,
                llm_provider=cfg.models.llm_provider, api_key=anthropic_api_key,
            ),
            cfg.models.visual_model_id,
        )
        decision_model = ModelWrapper(
            build_decision_model(
                cfg.models.decision_model_id, cfg.models.aws_region,
                llm_provider=cfg.models.llm_provider, api_key=anthropic_api_key,
            ),
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

    # 7. Invoke the core engine via .stream() so in-graph stages emit LIVE as each node completes
    # (FR-030). Emission stays on this single-threaded driver — the integer seq counter cannot race
    # (research R2). ``updates`` chunks drive per-node emission; the last ``values`` chunk is the
    # full final state (equivalent to the old .invoke() return). This REPLACES the prior
    # post-invoke reconstruction block — emitting both would double-emit (FR-031).
    app = build_agent_graph(ctx)
    menu_names = sorted(registry.allowed_names())
    final_state: dict = {}
    for mode, chunk in app.stream(
        {"scenario_id": scenario_id, "image_path": str(image_path) if image_path else "",
         "seasonal_period": scenario.seasonal_period, "iterations": [], "rejected_signatures": []},
        stream_mode=["updates", "values"],
        config={"recursion_limit": 50},
    ):
        if mode == "values":
            final_state = chunk  # accumulating full state; last one wins
            continue
        # mode == "updates": one node completed this super-step.
        for node, delta in chunk.items():
            if not isinstance(delta, dict):
                continue
            if node == "visual_inspection" and cfg.visual_analysis_enabled and delta.get("visual"):
                emitter.emit(
                    StageId.VISUAL_INSPECTION,
                    StageStatus.COMPLETE,
                    ev.visual_inspection(delta["visual"], image_ref="agent_context.png"),
                    concurrency_group="visual_diagnostics",
                )
            elif node == "decision" and delta.get("iterations"):
                emitter.emit(
                    StageId.DECISION_ITERATION,
                    StageStatus.COMPLETE,
                    ev.decision_iteration(delta["iterations"][-1], menu=menu_names),
                )
            elif node == "validation" and delta.get("iterations"):
                emitter.emit(
                    StageId.VALIDATION_OUTCOME,
                    StageStatus.COMPLETE,
                    ev.validation_outcome(delta["iterations"][-1]),
                )
            # "diagnostics" (emitted in the prelude) and "final_evaluation" (emitted in step 9 with
            # test metrics) produce no event here.

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
    # so the UI can render a continuous zoom-in/out/pan chart.
    # Columns: ds, y_actual, region ("train"|"val"|"test"), yhat_full_history, yhat_naive, yhat_agent
    #          (yhats are NaN in the train/val regions). The training region is split into "train"
    #          ([0, fit_end)) and "val" ([fit_end, train_end)) so the UI can shade all three regions
    #          distinctly (FR-025); the forecast/hidden-test region is labelled "test".
    csv_path = run_dir / "forecast_comparison.csv"
    csv_written = False
    try:
        train_hist = split.train_df.copy()
        test_hist  = split.test_df.copy()
        n_test     = len(test_hist)
        fit_end    = split.fit_end  # boundary between "train" and "val" inside the training region

        # Training region: actual values, NaN for forecast yhats. Rows [0, fit_end) = train,
        # rows [fit_end, train_end) = val.
        _nan = float("nan")
        train_rows: list[dict] = []
        for pos, (_, row) in enumerate(train_hist.iterrows()):
            train_rows.append({
                "ds":               row["ds"].strftime("%Y-%m-%d"),
                "y_actual":         round(float(row["y"]), 6),
                "region":           "train" if pos < fit_end else "val",
                "yhat_full_history": _nan,
                "yhat_naive":        _nan,
                "yhat_agent":        _nan,
            })

        # Forecast (hidden-test) region: actuals kept for comparison, plus each method's yhat.
        fh_yhat = [round(float(v), 6) for v in fe["full_history_prophet"]["yhat"][:n_test]]
        nw_yhat = [round(float(v), 6) for v in fe["naive_workflow"]["yhat"][:n_test]]
        ag_yhat = [round(float(v), 6) for v in fe["agent"]["yhat"][:n_test]]

        fc_rows: list[dict] = []
        for i, (_, row) in enumerate(test_hist.iterrows()):
            fc_rows.append({
                "ds":               row["ds"].strftime("%Y-%m-%d"),
                "y_actual":         round(float(row["y"]), 6),  # keep actuals for comparison
                "region":           "test",
                "yhat_full_history": fh_yhat[i] if i < len(fh_yhat) else _nan,
                "yhat_naive":        nw_yhat[i] if i < len(nw_yhat) else _nan,
                "yhat_agent":        ag_yhat[i] if i < len(ag_yhat) else _nan,
            })

        csv_df = pd.DataFrame(train_rows + fc_rows)
        csv_df.to_csv(csv_path, index=False)
        csv_written = True
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
    return {
        **metrics_report,
        "run_id": run_id,
        "final_eval": fe,
        "run_dir": str(run_dir),
        "csv_path": str(csv_path) if csv_written else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the changepoint agent for one scenario.")
    parser.add_argument("--scenario", required=True, help="Scenario id to run")
    parser.add_argument("--override", help="JSON config override (same shape as config.yaml)")
    args = parser.parse_args()
    override = ConfigOverride.from_dict(json.loads(args.override)) if args.override else None
    run_scenario(args.scenario, override=override)


if __name__ == "__main__":
    main()
