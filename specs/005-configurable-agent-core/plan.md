# Implementation Plan: Configurable Agent Core (POC → Core Promotion)

**Branch**: `005-configurable-agent-core` | **Date**: 2026-06-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-configurable-agent-core/spec.md`

## Summary

Promote the working changepoint LangGraph POC (`pocs/changepoint/`) into the review-gated shared
core (`src/ailf/core/`) plus a thin changepoint pipeline (`src/ailf/pipelines/changepoint/`), made
configurable. The generic spine — the agent loop/engine, an MCP-relocatable tool registry, the
deterministic single-holdout gate, the split resolver, forecast metrics, the LLM provider wrapper, a
stage-event emitter, config resolution, and reporting — moves to core with a plain-serializable
boundary. The changepoint detector, the 13-field diagnostics bundle, the five bounded interventions,
the prompts, and the committed CSV fixtures stay in the pipeline and register into the core loop. A
run is a **single scenario**: load fixture → resolve config + split → detect changepoints → fit two
baselines → compute diagnostics → (visual ∥ diagnostics) → decision ↔ validation loop → final
hidden-test evaluation, with every step emitting a typed event to a default file sink. Behavior is
driven by a pipeline-owned `config.yaml` (model IDs, `visual_analysis_enabled`, per-diagnostic and
per-tool toggles, split knobs) plus an optional per-run override that is merged, validated, and
recorded. The deciding constraint is **POC parity** (SC-001): the deterministic baseline and
validation metrics must match the POC bit-for-bit for the committed fixtures and seed.

## Technical Context

**Language/Version**: Python 3.11 (`requires-python = ">=3.11"`, managed by `uv`).

**Primary Dependencies** (all already in `pyproject.toml` — **no new dependencies**): `prophet`
(forecasting + changepoint detection), `langgraph` + `langchain` + `langchain-aws` (graph engine +
Bedrock chat models, confined to two core modules), `boto3` (Bedrock transport), `pandas`/`numpy`
(data), `matplotlib` (training-only chart + comparison plot, pipeline-side), `pyyaml` (config.yaml),
`python-dotenv` (secrets from `.env`). One **version pin is added**: `prophet==1.1.6` (currently
unpinned) so the parity oracle is stable; the `uv.lock` is committed.

**Storage**: Filesystem only. Pipeline-owned defaults at
`src/ailf/pipelines/changepoint/config.yaml`. Committed fixtures at
`src/ailf/pipelines/changepoint/data/csv/*.csv` + `scenario_metadata.json`. Per-run outputs under
`reports/changepoint/<run_id>/` (gitignored bulk): `effective_config.json`, `metrics.json`,
`agent_trace.json`, `events.jsonl`, `report.md`, `agent_context.png` (when visual on),
`forecast_comparison.png`, and `event_payloads/<seq>.json` for oversized payloads.

**Testing**: `pytest` (test-first now BINDING — the POC exemption is gone). Two tiers split exactly
at "calls the model wrapper": Tier A (deterministic, failing-then-passing TDD) under `tests/core/**`
and `tests/pipelines/changepoint/**`; Tier B (LLM stages, golden-set + trace-invariant, no
exact-output asserts). A committed `poc_parity_reference.json` captured from the **un-promoted POC**
is the SC-001 oracle. Bedrock-dependent golden eval is opt-in behind `@pytest.mark.golden` + a
credential guard; it never gates the deterministic suite.

**Target Platform**: Local CLI / module run on macOS/Linux dev machines
(`uv run python -m ailf.pipelines.changepoint.pipeline --scenario <id>`); later driven by Sowmya's UI
over an event transport that is **out of scope here** (only the event interface + file sink land now).

**Project Type**: Single Python workspace — shared importable core + thin use-case pipeline (no
frontend/backend split in this feature).

**Performance Goals**: Not latency-sensitive. A single-scenario run (≤5 agent iterations × Prophet
fits + two baselines) completes in minutes; Prophet fit count dominates. Single-run-at-a-time; no
concurrency guarantees (clarification 7).

**Constraints**:
- **POC parity (SC-001)**: deterministic baseline + validation metrics identical to the POC for the
  committed fixtures and seed (`1729`), float tol `1e-6`, exact integer equality for structural fields.
- **Serializable boundary (Principle I, FR-003)**: `langgraph` imports confined to
  `core/agent/engine.py`; `langchain_aws` confined to `core/models/llm.py`; every serialized artifact
  is plain JSON via a strict serializer that **raises** on non-JSON types (no `default=str`).
- **No-leakage (FR-029/FR-033)**: agent + every pre-final event payload sourced only from
  training-derived, agent-facing views; `audit_only` ground truth never enters core (tests read it
  directly from metadata).
- **Bounded + gated (Principle IV, FR-023/FR-025)**: tools chosen by name + bounded params only; the
  single-holdout gate is the sole scoring authority; the agent never sees validation scores mid-loop.

**Scale/Scope**: 5 committed scenarios (1000 or 1730 rows, daily, `seasonal_period=365`); 3 methods
(full-history Prophet, naive-window workflow, agent); 5 structural tools + 1 always-on fallback; 13
diagnostics fields; 11 event stage ids.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

The POC exemption **no longer applies** — this code enters `src/ailf/core` and a promoted pipeline, so
all gates bind. The design satisfies them, with three deviations justified in writing below.

| Principle | Status | How this plan honors it |
|-----------|--------|--------------------------|
| **I. Importable Core (serializable boundary)** | **PASS** | All core public I/O is plain frozen dataclasses with `to_dict`/`from_dict` (mirroring `core/datasets/case.py`) or plain dicts. `langgraph` is confined to `core/agent/engine.py`; `langchain_aws` to `core/models/llm.py`; import-guard tests enforce both and assert importing `core.backtest`/`core.agent`/`core.events` does **not** transitively import the Darts-coupled `core.datasets`. A single `to_json` chokepoint raises on non-JSON types (numpy, `pd.Timestamp`, model handles), replacing the POC's lossy `default=str`. |
| **II. Test-First (NON-NEGOTIABLE)** | **PASS (w/ scoped-out metrics — see Deviation 1)** | Every deterministic unit (config resolver, split resolver, registry + bounds gate, metrics, event emitter + sink, detector, diagnostics, baselines, validation scoring) is built failing-then-passing. Diagnostic tools get KNOWN-injected-ground-truth precision/recall/FPR tests. |
| **III. Golden-set Evaluation** | **PASS** | The LLM visual/decision stages are excluded from exact-output unit tests; covered by trace-invariant + leakage-invariant tests (FakeModelWrapper) and an opt-in golden-set eval (tool-family vs `expected_intervention_family`). The two agent-affecting changes (new decision prompt version, generated menu) require a **documented before/after golden-set capture with sign-off** (see Deviation 3 handling). |
| **IV. Bounded Interventions, Backtest-Gated (NON-NEGOTIABLE)** | **PASS (single-holdout — see Deviation 2)** | Fixed five-tool menu + bounded grids declared once as `ToolSpec` allowed-values; the gate is the sole authority; acceptance requires strictly beating the naive baseline on a historical holdout; hidden test only at final evaluation; the agent proposes, the guardrail disposes. |
| **V. Reproducible & Honest Evaluation** | **PASS** | `uv` + committed lock; `prophet` pinned; seed `1729` applied as the first prelude step and recorded in `effective_config.json` + `SplitProvenance`; naive-window workflow is the honest comparator; `metrics.json` reports MAE/RMSE/WAPE/sMAPE for all three methods. |
| **VI. Transparent, Explainable Outputs** | **PASS (narrative report added)** | Beyond `agent_trace.json` + `metrics.json` + plots, a per-run `report.md` (core/reporting) covers dataset/horizon, baseline comparison, detected issues, the accepted/best-val intervention with **before/after metric deltas vs naive**, the final recommendation, and the agent's stated limitations. The agent's reasoning and every accept/reject decision are inspectable. |
| **VII. Shared Core, Independent Pipelines** | **PASS** | Generic spine in `core/`; changepoint leaf in `pipelines/changepoint/` importing only `core` + stdlib (import-cleanliness test). Core holds zero changepoint/Prophet/UI symbols (SC-002). The pipeline injects the diagnostics field-set and structural tool-name set into the core validator so core stays use-case-agnostic. |

**Per-change gates**: deterministic logic test-first ✅ · agent-affecting changes golden-gated (documented capture) ✅ · interventions bounds-checked + backtest-gated ✅ · run emits a complete explanation report ✅ · `uv` lock current + `prophet` pinned ✅ · core touched → extra review + core tests green ✅.

### Deviations justified in writing (Governance: deviations must be justified)

1. **MASE and prediction-interval coverage are scoped OUT of this feature.** Principle II enumerates
   MASE and PI-coverage among project metrics. This promotion is **behavior-preserving** — its SC-001
   is bit-parity with the POC, which computes only MAE (primary) / RMSE / WAPE / sMAPE — and no FR or
   SC of this feature references MASE or PI-coverage. Principle II governs *how* metrics are built
   (test-first) when built, not that every feature implements the full menu. `core/metrics/metrics.py`
   is structured so MASE and PI-coverage can be added later test-first (a `metrics()` extension point);
   adding them now would introduce un-asserted quantities and risk the parity oracle. **Resolution:
   defer, with the metrics module shaped to accept them.** (Recorded in Complexity Tracking.)

2. **The gate uses a single validation holdout, not a rolling-origin backtest.** Principles IV/V and
   the `core/backtest/__init__.py` stub say "rolling-origin." The promoted gate preserves the POC's
   single-holdout protocol (the last `validation_horizon` block of training), which the prior POC spec
   documented and the POC exemption permitted. To avoid a core symbol whose contract contradicts its
   behavior (SC-002 "verifiable by inspection"), the module is named and documented honestly as a
   **single validation-holdout gate**, and the `core/backtest/__init__.py` docstring is corrected to
   say rolling-origin is a future extension. **Resolution: honest naming + written justification;
   rolling-origin deferred to a later core feature** when drift/anomaly need it.

3. **Two agent-affecting changes ship (new versioned decision prompt + generated menu).** Principle
   III forbids unjustified agent regressions. The deterministic suite asserts the structural
   invariants (visual-first ordering when enabled, leakage, menu pruning on toggle) via FakeModelWrapper;
   the **semantic** no-regression bar is enforced by a documented golden-set capture before/after the
   change (tool-family vs `expected_intervention_family` across the five scenarios) recorded in the PR.
   This keeps Principle III met without making Bedrock credentials a hard CI dependency.

**Gate result: PASS.** No unjustified violations. Complexity Tracking records the scoped-out items.

## Project Structure

### Documentation (this feature)

```text
specs/005-configurable-agent-core/
├── plan.md              # This file (/speckit-plan output)
├── spec.md              # Feature spec (+ 10 clarifications)
├── research.md          # Phase 0 — consolidated design decisions (U-* + critique resolutions)
├── data-model.md        # Phase 1 — entities & serializable shapes
├── quickstart.md        # Phase 1 — validation/run guide
├── contracts/           # Phase 1 — interface contracts
│   ├── config_schema.md         # config.yaml layout, merge, validation, lockstep
│   ├── tool_registry.md         # ToolSpec / Proposal / ToolContext / ToolResult + gate
│   ├── event_contract.md        # StageEvent envelope + per-stage payload schemas (11 stages)
│   ├── graph_engine.md          # GraphSpec, RunContext, node contracts, visual on/off
│   └── split_resolver.md        # SplitSpec / ResolvedSplit / SplitProvenance + rounding rule
└── checklists/
    └── requirements.md  # Spec quality checklist (already present)
```

### Source Code (repository root)

```text
src/ailf/core/                         # SHARED, serializable, review-gated — zero changepoint/UI symbols
├── config/
│   ├── schema.py                      # EffectiveConfig, ConfigOverride, ModelConfig, SplitSpec (frozen dataclasses + to_dict/from_dict)
│   ├── loader.py                      # read a config.yaml defaults file (pyyaml)
│   └── resolve.py                     # deep-merge override → validate → record; assert_config_in_lockstep; ConfigError
├── agent/
│   ├── engine.py                      # GraphSpec + build_agent_graph(spec, ctx)  ← ONLY module importing langgraph
│   ├── state.py                       # AgentState TypedDict (plain; _take_right reducer) — POC shape, langgraph-clean
│   ├── nodes.py                       # generic node bodies taking (state, RunContext of injected callables)
│   ├── runtime.py                     # RunContext (non-serializable handles + per-run resolved config + emitter)
│   └── registry.py                    # ToolParamSchema, ToolSpec, ToolRegistry, Proposal, ToolBoundsError
├── backtest/
│   ├── gate.py                        # single validation-holdout gate (sole scoring authority) + strictly-beat-naive
│   └── split.py                       # SplitSpec→ResolvedSplit resolver, SplitProvenance, rounding rule, SplitError
├── metrics/
│   └── metrics.py                     # MAE/RMSE/WAPE/sMAPE (MASE/PI-coverage = documented extension point, deferred)
├── models/
│   └── llm.py                         # ModelWrapper (build_visual_model/build_decision_model), ModelUnavailableError  ← ONLY module importing langchain_aws
├── events/
│   ├── event.py                       # StageEvent (frozen dataclass + to_dict), StageStatus
│   ├── stages.py                      # StageId closed enum (11 stages, causal order)
│   ├── emitter.py                     # Emitter protocol, EventEmitter (seq counter + stage() ctx mgr + fail-fast), NullEmitter
│   ├── sink.py                        # EventSink protocol, FileEventSink (JSONL), ListSink (tests)
│   ├── payloads.py                    # per-stage payload builders (documented shapes)
│   └── leakage.py                     # assert_no_leakage(payload) + strict to_json serializer (raises on non-JSON)
├── prompts/
│   └── loader.py                      # load_prompt(dir, name, version) + {{placeholder}} fill (no use-case text)
└── reporting/
    ├── run_dir.py                     # create per-run dir; stamp effective_config.json + seed
    └── artifacts.py                   # write_metrics_json, write_agent_trace, write_report_md (narrative, Principle VI)

src/ailf/pipelines/changepoint/        # THIN, changepoint-specific — imports only core + stdlib
├── config.yaml                        # DEFAULTS: model ids, visual_analysis_enabled, diagnostics{13}, agent_tools{5+fallback}, split
├── scenarios.py                       # Scenario + pandas SeriesSplit adapter (built FROM ResolvedSplit); audit_only kept off agent path
├── datasets.py                        # golden_split_from_metadata(); committed-CSV fixture loading (NOT synthetic generation)
├── detector.py                        # deterministic Prophet changepoint detection (honors n_changepoints_to_detect)
├── diagnostics.py                     # DiagnosticsBundle (13 fields); to_agent_dict(enabled) filtered view
├── interventions.py                   # register_changepoint_registry(): 5 structural ToolSpecs + invokers + full_history_default fallback + holiday precondition
├── baselines.py                       # full-history Prophet + naive-window workflow + CandidateResult + Prophet fit/predict helper
├── schemas.py                         # VisualInspectionResult, InterventionChoice (pydantic — LLM I/O only)
├── viz.py                             # render_agent_context (training-only), render_forecast_comparison (human-only)
├── prompts/
│   ├── visual_inspection_v1.md        # promoted UNCHANGED (no menu)
│   ├── react_decision_v2.md           # NEW version: {{tool_menu}} placeholder (visual-on arm)
│   └── react_decision_diagnostics_only_v1.md  # NEW: {{tool_menu}} placeholder, no visual references (visual-off arm)
├── data/
│   ├── scenario_metadata.json         # 5 scenarios + audit_only (never shown to agent)
│   └── csv/<scenario_id>.csv          # ds,y fixtures (committed)
└── pipeline.py                        # single-scenario entrypoint: seed → prelude (emit) → build GraphSpec from config → invoke → write artifacts

tests/
├── core/
│   ├── config/                        # resolve/merge/lockstep/validation errors
│   ├── agent/                         # registry+bounds, engine wiring/routing (FakeModelWrapper), stub-swap (SC-011), import-guards
│   ├── backtest/                      # gate accept rule, split resolver + rounding + provenance + round-trip
│   ├── metrics/                       # closed-form metric values
│   ├── events/                        # emitter seq/order, file sink JSONL, per-stage payload schema, leakage, strict serializer
│   └── parity/                        # SC-001 oracle comparison harness
└── pipelines/changepoint/
    ├── test_detector.py               # KNOWN-injected-ground-truth precision/recall/FPR (±15 row window)
    ├── test_diagnostics.py            # field-level + compute-but-hide + golden byte-identity of filtered view
    ├── test_interventions.py          # each tool invoke() purity + bounds + holiday precondition + fallback
    ├── test_config_lockstep.py        # config keys == live DiagnosticsBundle fields & structural tool names
    └── test_pipeline_smoke.py         # end-to-end single scenario with FakeModelWrapper → full artifact set

pocs/changepoint/                      # UNCHANGED — remains for provenance + the SC-001 parity oracle
```

**Structure Decision**: Generic spine → `src/ailf/core/` (config, agent engine/registry, backtest
gate + split, metrics, models, events, prompts, reporting); changepoint leaf →
`src/ailf/pipelines/changepoint/` (detector, diagnostics, the five tools + fallback, baselines,
schemas, viz, prompts, fixtures, single-scenario wiring). The cut points that matter: `interventions.py`
splits at the registry contract (generic registry + gate → core; the 5 concrete forecast builders →
pipeline); `forecasting.py` splits with `metrics()` → core and `fit_predict_prophet` → pipeline;
`graph/*` becomes a declarative `GraphSpec` compiled by the one `langgraph`-importing core module while
node bodies take injected callables via `RunContext`. `core/datasets` (Case/corpus) is **not reused**
for scenario loading — the impedance mismatch (Darts `TimeSeries`, synthetic-label semantics, runtime
generation) outweighs reuse; only split *math* is shared. The POC is left intact as the parity oracle.

## Complexity Tracking

> Two deviations need justification; the rest are routine promotions.

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| MASE + PI-coverage deferred (Principle II names them) | This is a behavior-preserving promotion; SC-001 is bit-parity with a POC that uses only MAE/RMSE/WAPE/sMAPE, and no FR/SC here references MASE/PI-coverage. Adding them now risks the parity oracle with un-required, un-asserted quantities. | Implementing them now: rejected — out of this feature's scope, no fixture/requirement exercises them, and `metrics()` is shaped as an extension point so a future feature adds them test-first without rework. |
| Single-holdout gate under `core/backtest` (Principles IV/V say rolling-origin) | Preserves POC parity (SC-001) and the prior spec's documented holdout protocol; rolling-origin is unneeded until a pipeline requires it. | Implementing rolling-origin now: rejected — would break parity and add an unscoped harness; mitigated by honest naming/docstring so inspection isn't misled. |

> No new dependencies (only a `prophet==1.1.6` pin). No new top-level project. Adding `core/config`,
> `core/events` packages and splitting `interventions.py` are normal module organization, not
> architectural deviations.
