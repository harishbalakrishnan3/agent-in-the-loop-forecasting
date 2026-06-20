# Phase 0 Research: Configurable Agent Core (POC → Core Promotion)

Consolidated design decisions resolving the plan's unknowns. Produced by fanning out seven
file-grounded deep-dives (package layout, config schema, tool registry, event contract, split
resolver, test strategy, visual-toggle/graph), reconciling cross-cutting conflicts, then running an
adversarial completeness critic against every FR/SC and constitution gate. Each decision below is the
**resolved** position — where the critic found a hole in the first-pass synthesis, the resolution here
supersedes it. Verified facts (read from the POC) are marked ✓.

## Verified ground truth (read from `pocs/changepoint/`)

- ✓ `DiagnosticsBundle` has **exactly 13 fields** (`detected_changepoints`, `latest_changepoint`,
  `primary_changepoint`, `post_changepoint_history_len`, `post_changepoint_shorter_than_season`,
  `seasonal_period`, `segment_stats`, `candidate_event_blocks`, `recurring_event_summary`,
  `local_boundary_jumps`, `candidate_drift_intervals`, `transient_event_score`,
  `permanent_shift_magnitude`).
- ✓ `interventions.py` `TOOL_NAMES` has **exactly 5** entries; there is **no** always-on fallback tool
  (the docstring's "six tools" is stale). Each tuning tool validates a **single proposed grid point**
  (`_validate_tuning_params`) — there is **no hidden in-tool grid sweep** over the holdout; the agent
  proposes concrete values. So promoting each `invoke()` as a pure single fit is behavior-preserving.
- ✓ The validation holdout is the **tail of training**: `fit_end = train_end - validation_horizon`, so
  golden metadata sums correctly because val is nested inside train (e.g. `train_end=880`,
  `test_horizon=120`, `row_count=1000`).
- ✓ The POC already keeps `AgentState` plain-serializable and stashes runtime handles on `RunContext`
  closures (`graph/nodes.py`); `llm.py` is already schema-generic (`TypeVar bound=BaseModel`).
- ✓ Seed is process-global (`SEED=1729` + `random.seed`/`np.random.seed` in `run_poc.main`), **not** in
  metadata.
- ✓ `pyproject.toml` already has `pyyaml`, `langgraph`, `langchain-aws`, `boto3`, `python-dotenv`;
  `prophet` is **unpinned**. `src/config/config.yml` is the **drift** dataset config (unrelated schema).
- ✓ `core/datasets/__init__.py` eagerly imports Darts-coupled `Case`/`corpus`/drift `viz`.

---

## Decision 1 — Core/pipeline module layout (U-LAYOUT)

**Decision**: Generic spine → `src/ailf/core/` (`config/`, `agent/`, `backtest/`, `metrics/`,
`models/`, `events/`, `prompts/`, `reporting/`); changepoint leaf → `src/ailf/pipelines/changepoint/`.
Two POC modules are cut across the boundary: `forecasting.py` → `metrics()` to core,
`fit_predict_prophet` to the pipeline; `interventions.py` → generic registry + gate to core, the five
concrete forecast builders to the pipeline. Full mapping in `plan.md` → Project Structure.

**Rationale**: Honors Constitution VII and FR-001/FR-002 near-verbatim; the existing core stub
docstrings already name `agent`, `models`, `backtest`, `metrics`, `reporting`, `prompts`, `eval`. No
new dependencies needed.

**Alternatives considered**: (a) Promote `fit_predict_prophet` into `core/models` as a uniform
forecaster now — rejected: out of scope, leaks a model choice into core, risks parity. (b) Keep the
whole graph package pipeline-side — rejected: FR-001/US1-AC2 place the loop and orchestration in core.

## Decision 2 — Prophet stays pipeline-private (U-PROPHET)

**Decision**: `fit_predict_prophet` stays in the pipeline (`baselines.py` / small pipeline helper). Do
**not** introduce the `core/models` uniform-forecaster interface in this feature; `core/models/llm.py`
is **only** the LLM provider wrapper. The `Tool.invoke` contract is shaped to admit a future core
forecaster without entangling it now.

**Rationale**: FR-001's "model-provider wrapper" is the LLM wrapper; Prophet is the changepoint
forecasting mechanism and must stay pipeline-side to keep core Prophet-free (SC-002) and protect parity
(FR-005). The `core/models/__init__.py` stub's uniform-forecaster language is noted as **deferred**.

**Alternatives considered**: Uniform forecaster now — rejected as unscoped (see Decision 1a).

## Decision 3 — MCP-ready tool registry (U-REGISTRY, U-FALLBACK, U-GATE)

**Decision**: `core/agent/registry.py` defines plain-data types: `ToolParamSchema` (name; kind ∈
{`enum`, `float_grid`, `int`, `str_choice`, `block_list`}; allowed-values; default; required),
`ToolSpec` (name, description, params, enabled, `structural: bool`), `ToolRegistry`
(`for_run(enabled_names)` projects a registry filtering **both** `menu()` and `allowed_names()`;
`validate_params` → `ToolBoundsError`), `Proposal` (tool + params + rationale + `action_signature` =
`tool|json.dumps(params, sort_keys=True)`, unchanged from POC), and the plain `ToolContext`/`ToolResult`
crossing types (Decision 4). `core/backtest/gate.py` is the **sole** caller of `registry.invoke()` and
the sole scoring authority. The pipeline's `register_changepoint_registry()` registers the five
structural tools (`CPS_GRID`/`SPS_GRID`/`HPS_GRID`/`MODE_GRID`/`RANGE_GRID` become allowed-values **data**
on `ToolSpec`s) each with an `invoke(ToolContext, params) → ToolResult` that reconstructs pandas/Prophet
server-side, plus the holiday tool's `precondition(context)` (the `is_calendar_recurring` guard) invoked
by the gate before `invoke()`. **Fallback (FR-016)**: `full_history_default` is registered as an
always-enabled `structural=False` tool that the config resolver may not disable; when all five
structural tools are disabled, `for_run()` yields a menu of just `{full_history_default}` and the trace
records the reduction.

**Rationale**: Implements FR-016/FR-022..025 and SC-011. Cutting at `ToolContext`/`ToolResult` (plain
records + ISO timestamps, no `SeriesSplit`/`DiagnosticsBundle`/Prophet handle crossing) is what makes a
swap to an out-of-process MCP stub require zero change to the agent loop, gate, or prompts. The POC has
no fallback tool, so an all-disabled menu would be empty — hence the always-on `full_history_default`.

**Alternatives considered**: Keep `Proposal`/bounds pipeline-side — rejected: bounds enforcement is the
generic guardrail (Principle IV) and must be the single core authority (FR-025). Let tools share a core
Prophet — rejected (Decision 2).

## Decision 4 — Plain-data tool boundary (cross-cutting note 4; resolves critic SC-011)

**Decision**: `ToolContext` = `{ training: list[{ds: ISO-8601 str, y: float}]` up to `fit_end`,
`future: list[ISO-8601 str]`, `diagnostics: dict` (the **full** `to_agent_dict()` bundle for tools — see
Decision 12) `}`. `ToolResult` = `{ yhat: list[float], resolved_params: dict }`. No `SeriesSplit`,
`DiagnosticsBundle` object, or live Prophet/model handle ever crosses this boundary.

**Rationale**: This single contract satisfies SC-011 (lift-and-shift) and Principle I; the heavy compute
(Prophet fit) stays server-side behind a plain request/response.

## Decision 5 — LangGraph engine + RunContext + serializable state (U-ENGINE)

**Decision**: `core/agent/engine.py` holds `GraphSpec` (plain stage names + edges + concurrency-group
labels) and `build_agent_graph(spec, ctx)` compiling it onto a LangGraph `StateGraph`; **`langgraph` is
imported only here** (+ its test). `core/agent/state.py` keeps the POC `AgentState` TypedDict verbatim
(plain dicts/lists, `_take_right` reducer) carrying only serializable values and the **filtered**
diagnostics view. `core/agent/runtime.py` holds the generic `RunContext` carrying all non-serializable
handles + per-run resolved config (`visual_model`, `decision_model`, model ids, full diagnostics bundle,
naive result, image path, the `for_run()` tool-registry projection, `visual_enabled: bool`,
`enabled_diagnostics: frozenset[str]`, and the **emitter**). `core/agent/nodes.py` holds node bodies
taking `(serializable state, RunContext)`. Toggles / registry / emitter **never** enter `AgentState`.

**Rationale**: FR-003/FR-005/FR-015/US1-AC3. The POC already isolates state from handles; generalizing
`RunContext` to injected callables is the minimal change letting the loop live in core while
detector/diagnostics/tools/prompts stay pipeline-side.

**Alternatives considered**: Re-implement the loop without LangGraph — rejected (rewrite risk vs FR-005).
Pipeline owns the `StateGraph` — rejected (FR-001 places orchestration in core).

## Decision 6 — Visual on/off is STRUCTURAL (U-ENGINE, U-PROMPTS; resolves critic FR-014/SC-005)

**Decision**: When `visual_analysis_enabled` is **false**, the pipeline builds a **linear** `GraphSpec`
(`START → diagnostics → decision`) that **omits the visual node entirely** — no `agent_context.png` is
produced or sent to any model. When **true**, the POC's concurrent fan-out (`visual ∥ diagnostics →
decision`) is built. The visual-first ordering invariant becomes a raised `StageError` (not a bare
`assert`, which `-O` strips) checked **only** when `ctx.visual_enabled`. The decision prompt is selected
by the flag: `react_decision_v2.md` (visual-on) vs `react_decision_diagnostics_only_v1.md` (visual-off).

**Rationale**: Structural omission gives a stronger "no image sent" guarantee (SC-006) than a
node-internal early-return.

## Decision 7 — Prompt versioning + generated menu (U-PROMPTS; resolves critic FR-014/SC-005 + Principle III)

**Decision**: Prompts live pipeline-side in `prompts/`. `visual_inspection_v1.md` is promoted
**unchanged** (it has no menu). The decision prompt is promoted as a **new version**
`react_decision_v2.md` whose body replaces the POC's hardcoded 5-tool prose menu with a `{{tool_menu}}`
placeholder filled at runtime from the `for_run()` registry's enabled `ToolSpec`s (name + description +
bounded schema). A new sibling `react_decision_diagnostics_only_v1.md` (visual-off arm) also uses
`{{tool_menu}}` and drops all visual-first language. `core/prompts/loader.py` provides a generic
`load_prompt(dir, name, version)` + placeholder fill (no use-case text).

**Rationale**: The critic correctly flagged that promoting `react_decision_v1.md` *unchanged* keeps a
hardcoded menu the model reads, so a disabled tool would still be **advertised** (violating FR-014/SC-005
"absent from the menu advertised to the agent"). Sourcing the menu from `for_run()` makes "removed from
menu" and "rejected by gate" the **same fact**. Per Constitution prompt-versioning, the released
`react_decision_v1.md` is **not** edited — a new `v2` is added; both prompt arms get a separately
evaluable identity for golden-set eval (Principle III). The two new prompts are agent-affecting, so a
**documented before/after golden-set capture** (tool-family vs `expected_intervention_family`) is
required in the PR (plan Deviation 3).

**Alternatives considered**: Keep the prose menu and downgrade SC-005 to "rejected by gate only" —
rejected: contradicts FR-014.

## Decision 8 — config.yaml: pipeline-owned, merge-then-validate-then-record (U-CONFIG)

**Decision**: `config.yaml` is **pipeline-owned** at `src/ailf/pipelines/changepoint/config.yaml` (not
repo root, not `src/config/`). Layout: `models: {visual_model_id, decision_model_id}`; `aws_region`;
`visual_analysis_enabled: true`; `diagnostics:` mapping of exactly the 13 bundle fields (each `true`);
`agent_tools:` mapping of the 5 structural tool names **plus** `full_history_default` (each `true`);
`split: {source: golden, ...optional override}`. Defaults: visual = Claude Opus 4.8, decision = Claude
Sonnet 4.6, region `us-west-2`. `core/config/resolve.py` does **merge → validate → record**: deep-merge =
scalars replace-if-present; `diagnostics`/`agent_tools` merge **key-wise** (partial overrides allowed, no
new keys); the `split` block is **replace-as-a-unit** (any split key in the override takes the whole
block, preventing golden+override hybrids). Validation raises `ConfigError` (reusing the POC name)
naming the offending field for unknown/missing diagnostic or tool keys, malformed values, empty/missing
model id, an attempt to disable `full_history_default`, and split errors (delegated to the resolver). The
**pipeline injects** the bundle field-set (`dataclasses.fields`) and the structural tool-name set into
the core validator, so core holds zero changepoint symbols.

**Rationale**: FR-007..012, SC-003/008, secrets clarification. The diagnostics/tool key lists are
changepoint-specific, so the defaults file belongs with the pipeline while the merge/validate logic is
generic core. `src/config/config.yml` is the drift config and must not be reused.

## Decision 9 — Config/bundle/registry lockstep (U-LOCKSTEP)

**Decision**: `core/config/resolve.py` exposes
`assert_config_in_lockstep(diagnostics_field_names, structural_tool_names, cfg_diagnostics, cfg_tools)`
raising `ConfigError` on any **symmetric** difference (unknown **and** missing). Driven two ways: at
config load (runtime guarantee) and a dedicated `test_config_lockstep.py` that reflects
`dataclasses.fields(DiagnosticsBundle)` and the live registry's structural tool names and asserts the
config key-sets equal them exactly. The lockstep check scopes `agent_tools` to **structural** tools
(`full_history_default` is always-on, present with `enabled: true`, excluded from the exact-match).

**Rationale**: FR-011/FR-012/SC-003 require a bidirectional automated check against a single source of
truth; reflecting live symbols (not literal lists) keeps the test from rotting.

## Decision 10 — Split resolver, partition model, rounding, provenance (U-SPLIT; resolves critic FR-020/SC-007/SC-009)

**Decision**: `core/backtest/split.py` owns: `ResolvedSplit` (frozen: `train_rows`, `val_rows`,
`test_rows` all ≥ 1, + provenance) with the **fixed nested-view derivation** `fit_end = train_rows`,
`train_end = train_rows + val_rows`, `test = [train_end, train_end + test_rows)`; `SplitSpec` (units
discriminator: `ratios` with `train/val/test_ratio` summing to **exactly 1.0**, OR `absolute` with
`train/val/test_rows`); `resolve_split(spec | None, *, n_rows, golden: ResolvedSplit) → ResolvedSplit`
(`None` → golden verbatim, `source='golden'`); `SplitProvenance` (source, units, requested, resolved
counts, `rounding_rule`, derived `{train_end, fit_end, forecast_origin_index}`); `SplitError`.
**Rounding rule** (`rounding_rule='floor_test_val_train_absorbs'`): `test_rows = floor(test_ratio·n)`,
`val_rows = floor(val_ratio·n)`, `train_rows = n − test_rows − val_rows`; reject ratios not summing to
1.0; re-validate each segment ≥ 1, sum ≤ n, positive/non-overlapping. Supplying both ratio and absolute
keys raises `SplitError('ambiguous split specification')`. The **pipeline** owns
`golden_split_from_metadata(meta) → ResolvedSplit` (`val_rows = validation_horizon`,
`train_rows = train_end − validation_horizon`, `test_rows = test_horizon`) and the pandas `SeriesSplit`
adapter built from `ResolvedSplit`. The golden adapter **rejects** metadata that would derive a
non-positive `train_rows`, and the override path raises `SplitError` (not `IndexError`) when
`test_rows` exceeds available rows.

**Rationale**: Resolves the partition-semantics conflict (the holdout is nested in training, but FR-019's
"reconstruct the series length" / FR-020's "non-overlapping" favor a strict-partition model). Adopting
strict-partition lengths with a fixed nested-view derivation gets both: clean validation **and** bit-exact
golden reproduction. ✓ For golden metadata the lengths 760/120/120 derive the POC's `train_end=880`/
`fit_end=760` exactly; verified to also hold for the 1730-row scenarios. A **golden-reproduction test**
asserts derived indices equal the POC's `SeriesSplit` for all five scenarios before any other split work
proceeds.

**Alternatives considered**: Largest-remainder (Hamilton) rounding — rejected: over-engineered for three
segments; the spec only requires determinism + documentation. Allowing ratios to sum < 1.0 — rejected:
adds "unallocated rows" complexity (see Open Question 2).

## Decision 11 — Stage-event contract, emitter, file sink (U-EVENTS; resolves critic FR-027/FR-028/FR-031)

**Decision**: New `core/events/` package. `StageEvent` = frozen dataclass `(run_id, seq: int monotonic,
ts: ISO-8601 UTC, stage: StageId, status: StageStatus ∈ {start, complete, error}, concurrency_group:
str | None, payload: dict, error: dict | None)` with `to_dict()`. **In real code**, `seq` is a
per-`EventEmitter` integer counter incremented on each emit and `ts` is stamped via
`datetime.now(timezone.utc).isoformat()` at emit time (these are forbidden in the *research workflow*
sandbox but are the production mechanism). `StageId` closed enum in **causal order**: `config_resolved`,
`split_built`, `changepoint_detection`, `baseline_full_history_prophet`, `baseline_naive_workflow`,
`diagnostics_computed`, `visual_inspection` (only when enabled), `decision_iteration`,
`validation_outcome`, `final_evaluation`, `run_complete`. `EventEmitter` owns `run_id`, the seq counter,
the active `concurrency_group`, and `list[EventSink]`; exposes `emit(...)` + a `stage()` context manager
that emits `start` on enter and `complete` on exit **or** a terminal `error` event + re-raise on
exception (fail-fast, FR-032). `EventSink` protocol + `FileEventSink` (JSONL, append, flush per record)
to `<run_dir>/events.jsonl` + in-memory `ListSink` for tests. The emitter lives on `RunContext`.
**Per-stage payload schemas are fully specified** in `contracts/event_contract.md` and backed by a
per-stage schema test. **Concurrency** (resolves critic FR-028): the deterministic prelude
(`config_resolved` … `diagnostics_computed`) is emitted **sequentially by the single-threaded driver
before** graph invocation; inside the graph, the only concurrency is the `visual ∥ diagnostics`
fan-out, and **their start/complete are emitted from the single-threaded driver** (not inside node
bodies), so the integer seq counter cannot race — both carry `concurrency_group='visual_diagnostics'`.
When visual is off, the graph is linear and no concurrency group is set. **Oversized payloads**
(FR-031): a fixed `MAX_INLINE_PAYLOAD_BYTES = 32_768`; any payload exceeding it (or any binary artifact
like an image) is written to `<run_dir>/event_payloads/<seq>.json` and referenced by a relative-path
`$ref`; a test asserts no pre-final event payload inlines a forecast array.

**Rationale**: FR-026..032, SC-010, US5/US6. JSONL is append-safe under fail-fast. Emitting the
concurrent pair from the driver eliminates the seq-race the critic flagged without serializing the
compute.

## Decision 12 — Compute-but-hide diagnostics (U-HIDE; cross-cutting note 5)

**Decision**: Change `DiagnosticsBundle.to_agent_dict()` to `to_agent_dict(enabled: set[str])` returning
only enabled fields. The **full** bundle is always computed (preserving intra-bundle dependencies, e.g.
`candidate_drift_intervals` depends on `local_boundary_jumps`) and recorded full in the trace; only the
**filtered** view enters `AgentState['diagnostics']`, the decision prompt, and the
`diagnostics_computed` event payload. The gate/tools receive the **full** bundle via `ToolContext`
(Decision 4), so a disabled-but-depended-on diagnostic never breaks a tool. The enabled set comes from
`RunContext.enabled_diagnostics`. **Parity guard**: with the golden config (all 13 enabled) the filtered
view MUST be byte-identical to the current `asdict` output — a test asserts this against the POC
(guards SC-001).

**Rationale**: FR-013/SC-004 + the "disabling a depended-on diagnostic" edge case. Two views
(agent-facing filtered, gate/tool-facing full) are load-bearing and must not be confused.

## Decision 13 — LLM wrapper + structured-output schemas (U-MODELS)

**Decision**: Promote `pocs/changepoint/llm.py` to `core/models/llm.py`: a thin `ModelWrapper` exposing
`invoke_structured_text(prompt, schema)` and `invoke_structured_with_image(prompt, image_path, schema)`
returning a pydantic `BaseModel` (generic `TypeVar`), plus `ModelUnavailableError` and the explicit
no-silent-fallback wrapping (FR-036). Rename `build_react_model → build_decision_model`; keep
`build_visual_model`. **Only** this module imports `langchain_aws`/`ChatBedrockConverse`. Model IDs come
from `EffectiveConfig`, not env. The changepoint pydantic schemas `VisualInspectionResult` and
`InterventionChoice` move **pipeline-side** to `schemas.py`. Tests inject a `FakeModelWrapper`
implementing the protocol: returns canned objects, records the `(prompt, image_path)` it saw (leakage
assertions), and can raise `ModelUnavailableError`.

**Rationale**: FR-001/FR-008/FR-036 + the constitution's single swappable/mockable wrapper. The POC
wrapper is already schema-generic and injected via `RunContext`, so the `FakeModelWrapper` seam needs no
production refactor. Keeping the two output schemas pipeline-side preserves SC-002.

## Decision 14 — Reporting artifacts + run directory + narrative report (U-REPORTING; resolves critic Principle VI + SC-007)

**Decision**: `core/reporting/artifacts.py` keeps generic plain-data writers (`write_metrics_json`,
`write_agent_trace`) **and adds `write_report_md`** — a per-run narrative explanation report
(Principle VI): dataset/horizon, baseline comparison, detected issues, the accepted/best-val intervention
with **before/after metric deltas vs the naive baseline**, the final recommendation, and the agent's
stated limitations/uncertainties (sourced from the visual result + trace). `core/reporting/run_dir.py`
creates the per-run timestamped directory and stamps `effective_config.json`
(`EffectiveConfig.to_dict` + split provenance + model ids + **recorded seed**). The cross-scenario
summary (`write_summary_md`, `families_demonstrated`, family constants) is **dropped** (clarification 5).
The two matplotlib plots stay pipeline-side in `viz.py`; neither is ever passed to an agent stage. The
agent trace additionally records `visual_analysis_enabled`, `hidden_diagnostics` (sorted),
`removed_tools` (sorted), split provenance, the decision-prompt id+version actually loaded, the visual
prompt id+version (when on), and `{visual_model_id, decision_model_id}`.

**SC-007 round-trip** (resolves critic): `SplitProvenance` records the **resolved absolute rows** and the
`source` marker. On re-ingest, a recorded `source='golden'` config re-derives golden verbatim and keeps
provenance `'golden'` (it does **not** emit a split override that would flip provenance to `'override'`);
a recorded `source='override'` re-resolves from the recorded absolute rows (no re-rounding). A test
asserts provenance is **stable across the round-trip** for both cases.

**Rationale**: FR-021/FR-035/SC-007/SC-012/US6 + Principle VI. The `core/reporting` stub already promises
the narrative report; treating `agent_trace.json` as sufficient would silently regress Principle VI.

## Decision 15 — Scenario loading does NOT reuse core/datasets (U-DATASETS; resolves critic SC-002)

**Decision**: Keep a changepoint-specific loader in `scenarios.py` (promoted `Scenario`, the pandas
`SeriesSplit` adapter built from `ResolvedSplit`, `load_scenario`, `audit_only` kept strictly off the
agent path). `datasets.py` holds `golden_split_from_metadata` + committed-CSV fixture loading (**not**
synthetic generation). Only split **math** is promoted to core. **Import-cleanliness** (resolves critic):
a test asserts importing `ailf.core.backtest` / `ailf.core.agent` / `ailf.core.events` does **not**
transitively import `ailf.core.datasets` (whose `__init__` eagerly pulls Darts/drift code), and that the
changepoint pipeline never imports `ailf.core.datasets`.

**Rationale**: ✓ `core/datasets` enforces Darts `TimeSeries` + synthetic-label semantics + runtime
generation; changepoint scenarios are committed CSV fixtures with a golden absolute split + `audit_only`
+ a no-runtime-generation rule. The impedance mismatch outweighs reuse; the genuinely shared piece (split
resolution) is promoted alone.

## Decision 16 — Serialization idiom (U-SERIALIZATION; resolves critic Principle I)

**Decision**: One idiom across the serializable boundary: plain **frozen dataclasses with
`to_dict()`/`from_dict()`** (mirroring `core/datasets/case.py`) for `EffectiveConfig`, `ConfigOverride`,
`ModelConfig`, `SplitSpec`, `ResolvedSplit`, `SplitProvenance`, and `StageEvent`. Pydantic `BaseModel` is
used **only** for LLM structured-output schemas (`schemas.py`). Recorded artifacts are JSON
(`effective_config.json`, `agent_trace.json`, `metrics.json`, `events.jsonl`); `config.yaml` is the only
YAML. **Strict serializer** (resolves critic Principle I): a single `to_json(obj)` chokepoint in
`core/events/leakage.py` does `json.dumps(..., default=_strict)` where `_strict` **raises `TypeError`**
on any non-JSON-native type (numpy array, `pd.Timestamp`, Prophet handle) — replacing the POC's lossy
`default=str` in `write_agent_trace`, so a boundary leak fails loudly rather than being str-coerced.

**Rationale**: Keeps the serialized boundary obviously plain (Principle I/FR-003), confines pydantic to
the one place the SDK demands it, and avoids YAML float/ordering ambiguity in reproducibility artifacts.

## Decision 17 — Determinism chain (resolves critic FR-005/SC-001; cross-cutting note 9)

**Decision**: The core single-scenario entrypoint (`pipeline.py`) calls `random.seed(1729)` +
`np.random.seed(1729)` **as the first prelude step, before** the detector fit, both baseline fits, and
diagnostics — preserving the POC's ordering relative to Prophet's MAP estimation. `prophet` is **pinned**
(`prophet==1.1.6`) in `pyproject.toml` and `uv.lock` is committed. The resolved seed is recorded in
`effective_config.json` and `SplitProvenance`. Adding `emit()` calls is a pure side-effect (counter +
file write) that must not perturb RNG state or Prophet fits.

**Rationale**: The critic correctly flagged that moving the prelude out of `run_poc.main` risks silently
reordering seeding relative to the fits. Pinning the seed application as the first prelude step + pinning
Prophet makes parity reproducible.

## Decision 18 — Test strategy + parity oracle provenance (U-TESTS; resolves critic SC-001)

**Decision**: Two tiers split at "calls the model wrapper": **Tier A** (Principle II, failing-then-passing)
= config resolver, split resolver, registry + bounds + gate, metrics, event emitter + sink, graph
wiring/routing (FakeModelWrapper), diagnostics, detector, baselines, validation scoring; **Tier B**
(Principle III, golden-set, no exact-output asserts) = visual + decision nodes. **Parity oracle
provenance** (resolves the critic's contradiction): `poc_parity_reference.json` is captured **from the
un-promoted POC FIRST** (the trustworthy oracle), committed, then the **promoted core path** is asserted
to match it. Per scenario it records: detected changepoint indices + trend deltas, full-history-Prophet
val metrics, every naive candidate's val metrics + `selected_window_start`, and the two non-agent
baselines' **test** metrics. Compare floats/`trend_delta` with `rel_tol = abs_tol = 1e-6`; structural
fields (changepoint index, window_start, counts) with **exact integer equality**. Detector/diagnostics
get KNOWN-injected-ground-truth precision/recall/FPR tests using
`audit_only.true_injected_boundaries` (test-side only) with a **±15-row tolerance window** (matches the
diagnostics `_local_boundary_jumps` width of 14); event-pair scenarios map each injected **start** index
to the nearest expected detected changepoint. The SC-011 stub-swap conformance test lives in
`tests/core/agent/`. The golden-set agent-quality eval is opt-in behind `@pytest.mark.golden` + a
credential guard; it never gates the deterministic suite.

**Rationale**: FR-006 + Constitution II/III. The agent's chosen tool is non-deterministic, so parity
anchors only on deterministic quantities. Capturing the oracle from the POC *before* refactor is what
makes every behavior-preserving move (split derivation, registry cut) actually guarded.

---

## Open questions for the spec owner (non-blocking; sensible defaults chosen)

These are decided with a default so implementation can proceed; flag if you disagree.

1. **Per-segment partial split override** — Decided: **whole-split-only** for v1 (a run cannot override
   only `test_rows` while inheriting train/val from golden). Keeps the ambiguity rule (FR-018) and the
   partition-sum invariant clean. If per-segment is wanted later, the units discriminator + ambiguity
   rule need redesign.
2. **Ratio sum** — Decided: ratios must sum to **exactly 1.0** (reject `< 1.0`). The spec mandates only
   determinism; this avoids the "unallocated rows" complication. Revisit if you want trailing-unused-row
   semantics.
3. **MASE / PI-coverage** — Decided: **deferred** (plan Deviation 1) with the metrics module shaped as an
   extension point.
4. **Detector recall tolerance** — Decided: **±15 rows**, with `audit_only.true_injected_boundaries` as
   the precision/recall ground truth and event-pair starts mapped to nearest detected changepoints.
5. **Golden-set eval in CI** — Decided: **opt-in marker + credential guard** (not a hard CI gate);
   agent-affecting prompt/menu changes additionally require a documented before/after capture in the PR.

## Risks

- **Parity drift** if the prelude reorders seeding or Prophet is unpinned → mitigated by Decision 17 +
  the POC-first oracle (Decision 18).
- **Hidden Darts coupling** if a core module transitively imports `core.datasets` → mitigated by the
  import-cleanliness test (Decision 15).
- **Silent boundary leaks** via `default=str` → mitigated by the strict serializer (Decision 16).
- **Menu/gate divergence** if the prompt menu and gate bounds drift → mitigated by the single
  `ToolSpec` allowed-values source feeding both (Decisions 3, 7; cross-cutting note 8).
