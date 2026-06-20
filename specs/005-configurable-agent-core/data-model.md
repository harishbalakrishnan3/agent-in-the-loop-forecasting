# Phase 1 Data Model: Configurable Agent Core

Entities and their serializable shapes. Idiom (Decision 16): plain **frozen dataclasses** with
`to_dict()`/`from_dict()` for the serializable boundary; **pydantic** only for LLM structured output.
All `*.to_dict()` output is JSON-native (passes the strict `to_json` serializer that raises on numpy /
`pd.Timestamp` / model handles). Field lists below are the contract; types are Python.

---

## Configuration domain (`core/config/schema.py`)

### `ModelConfig` (frozen dataclass)
| Field | Type | Notes |
|-------|------|-------|
| `visual_model_id` | `str` | non-empty; default Claude Opus 4.8 (from config.yaml) |
| `decision_model_id` | `str` | non-empty; default Claude Sonnet 4.6 |
| `aws_region` | `str` | default `us-west-2` |

### `SplitSpec` (frozen dataclass — the *requested* split; see `contracts/split_resolver.md`)
| Field | Type | Notes |
|-------|------|-------|
| `units` | `Literal["golden","ratios","absolute"]` | discriminator |
| `train_ratio`,`val_ratio`,`test_ratio` | `float \| None` | set iff `units=="ratios"`; must sum to exactly 1.0 |
| `train_rows`,`val_rows`,`test_rows` | `int \| None` | set iff `units=="absolute"` |

Validation: a ratio key **and** an absolute key both present → `SplitError("ambiguous split specification")`.

### `EffectiveConfig` (frozen dataclass — the resolved, recorded per-run config)
| Field | Type | Notes |
|-------|------|-------|
| `models` | `ModelConfig` | |
| `visual_analysis_enabled` | `bool` | default `True` |
| `diagnostics` | `dict[str, bool]` | exactly the 13 `DiagnosticsBundle` field names → enabled |
| `agent_tools` | `dict[str, bool]` | 5 structural tool names + `full_history_default` → enabled |
| `split` | `SplitSpec` | `units="golden"` unless overridden |
| `seed` | `int` | recorded resolved seed (default `1729`) |

`to_dict()` is what lands in `effective_config.json`. `from_dict()` re-ingests it for SC-007 round-trip.

### `ConfigOverride` (frozen dataclass — a possibly-partial per-run override)
Same optional fields as `EffectiveConfig` but every field `| None`; `diagnostics`/`agent_tools` are
partial maps (key-wise merge); `split` replaces as a unit. Merge + validation in `core/config/resolve.py`.

**Derived / enabled sets** (passed into `RunContext`, never serialized as objects):
`enabled_diagnostics: frozenset[str]` = keys of `diagnostics` that are `True`;
`enabled_tools: frozenset[str]` = keys of `agent_tools` that are `True` (always includes
`full_history_default`).

---

## Split domain (`core/backtest/split.py`)

### `ResolvedSplit` (frozen dataclass — segment LENGTHS + provenance)
| Field | Type | Invariant |
|-------|------|-----------|
| `train_rows` | `int` | ≥ 1 |
| `val_rows` | `int` | ≥ 1 |
| `test_rows` | `int` | ≥ 1 |
| `provenance` | `SplitProvenance` | |

Fixed nested-view derivation (mirrors POC `SeriesSplit`): `fit_end = train_rows`;
`train_end = train_rows + val_rows`; validation holdout `= [train_rows, train_rows+val_rows)`;
test `= [train_end, train_end + test_rows)`. `train_rows + val_rows + test_rows ≤ n_rows`.

### `SplitProvenance` (frozen dataclass — FR-021, recorded per run)
| Field | Type | Notes |
|-------|------|-------|
| `source` | `Literal["golden","override"]` | stable across SC-007 round-trip |
| `units` | `Literal["golden","ratios","absolute"]` | requested units |
| `requested` | `dict` | the raw `SplitSpec` values requested |
| `resolved` | `dict` | `{train_rows, val_rows, test_rows, n_rows}` (absolute) |
| `rounding_rule` | `str` | `"floor_test_val_train_absorbs"` (or `"none"` for golden/absolute) |
| `derived` | `dict` | `{train_end, fit_end, forecast_origin_index}` |

---

## Tool registry domain (`core/agent/registry.py`)

### `ToolParamSchema` (frozen dataclass — the single source of bounds)
| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | param name |
| `kind` | `Literal["enum","float_grid","int","str_choice","block_list"]` | |
| `allowed` | `list \| None` | allowed values (the POC grids become this data) |
| `default` | `Any` | |
| `required` | `bool` | |

### `ToolSpec` (frozen dataclass — one registered intervention)
| Field | Type | Notes |
|-------|------|-------|
| `name` | `str` | stable id (e.g. `full_history_ramp_regressor`) |
| `description` | `str` | human/agent-facing |
| `params` | `list[ToolParamSchema]` | bounded schema |
| `enabled` | `bool` | per-run projection |
| `structural` | `bool` | `False` only for `full_history_default` |
| *invoker* | `Callable` | **not serialized**; held registry-side; `(ToolContext, params) → ToolResult` |
| *precondition* | `Callable \| None` | **not serialized**; `(ToolContext) → None \| reason` (holiday guard) |

`to_dict()` emits `{name, description, params[], enabled, structural}` — the agent menu view; the
callables never cross the boundary.

### `Proposal` (frozen dataclass — the agent's single choice; POC-identical signature)
| Field | Type | Notes |
|-------|------|-------|
| `tool` | `str` | must be in `registry.allowed_names()` for the run |
| `params` | `dict` | validated against `ToolSpec.params` |
| `rationale` | `str` | visual-first (visual on) or diagnostics-first (visual off) |
| `action_signature` (property) | `str` | `f"{tool}|{json.dumps(params, sort_keys=True)}"` |

### `ToolContext` (plain dict crossing the MCP-relocatable boundary — Decision 4)
`{ training: list[{ds: ISO8601, y: float}]` up to `fit_end`, `future: list[ISO8601]`,
`diagnostics: dict` (the **full** bundle) `}`. No `SeriesSplit`/`DiagnosticsBundle`/Prophet handle.

### `ToolResult` (plain dict)
`{ yhat: list[float], resolved_params: dict }`.

**Errors**: `ToolBoundsError` (param out of bounds / unknown tool / disabled tool) — a **normal**
rejection (re-prompt), not a stage failure.

---

## Agent state & runtime (`core/agent/state.py`, `core/agent/runtime.py`)

### `AgentState` (TypedDict, total=False — POC shape, plain-serializable)
Keys: `scenario_id`, `image_path`, `seasonal_period`, `visual` (dict), `diagnostics` (**filtered**
dict), `naive_summary`, `iterations` (list of proposal/val-outcome dicts), `rejected_signatures`
(list[str]), `accepted` (dict|None), `final_candidate`, `final_case`, `_final_eval`. No toggles, no
registry, no emitter, no model handles, no full bundle.

### `RunContext` (NOT serialized — holds all handles + per-run resolved config)
`visual_model`, `decision_model`, `model_ids`, `full_diagnostics` (the unfiltered bundle for
tools/gate), `naive_result`, `image_path`, `tool_registry` (the `for_run()` projection),
`visual_enabled: bool`, `enabled_diagnostics: frozenset[str]`, `emitter: EventEmitter`,
`split: ResolvedSplit`, `prompt_ids: dict`.

---

## Diagnostics (`pipelines/changepoint/diagnostics.py`)

### `DiagnosticsBundle` (dataclass — 13 fields, unchanged from POC)
`detected_changepoints`, `latest_changepoint`, `primary_changepoint`,
`post_changepoint_history_len`, `post_changepoint_shorter_than_season`, `seasonal_period`,
`segment_stats`, `candidate_event_blocks`, `recurring_event_summary`, `local_boundary_jumps`,
`candidate_drift_intervals`, `transient_event_score`, `permanent_shift_magnitude`.

**Change**: `to_agent_dict(enabled: set[str]) -> dict` returns only enabled fields (Decision 12). The
full bundle is always computed and recorded; the filtered view feeds the agent + the
`diagnostics_computed` event. Golden config (all 13) → filtered view byte-identical to POC `asdict`.

---

## LLM structured-output schemas (`pipelines/changepoint/schemas.py`) — pydantic

- **`VisualInspectionResult`**: `observations: list[str]`, `pattern_summary: str`,
  `hypotheses: list[str]`, `uncertainties: list[str]` (no intervention field).
- **`InterventionChoice`**: `tool: str`, `params: dict`, `visual_first_rationale: str` (visual-on) /
  diagnostics rationale (visual-off), `expected_effect: str`.

---

## Events (`core/events/`)

### `StageEvent` (frozen dataclass — envelope; see `contracts/event_contract.md` for per-stage payloads)
| Field | Type | Notes |
|-------|------|-------|
| `run_id` | `str` | per-run id |
| `seq` | `int` | monotonic per-emitter; strict total order |
| `ts` | `str` | ISO-8601 UTC, stamped at emit |
| `stage` | `StageId` (enum) | 11 ids, causal order (Decision 11) |
| `status` | `StageStatus` | `start` \| `complete` \| `error` |
| `concurrency_group` | `str \| None` | `"visual_diagnostics"` for the fan-out pair, else `None` |
| `payload` | `dict` | stage-specific (documented); or a `{"$ref": "event_payloads/<seq>.json"}` if > 32 KB |
| `error` | `dict \| None` | `{type, message}` on `status=error` (fail-fast terminal) |

---

## Baselines (`pipelines/changepoint/baselines.py`)

### `CandidateResult` (dataclass — unchanged from POC; pipeline-side)
`label`, `val_metrics: dict`, `forecast: np.ndarray | None`, `test_metrics: dict | None`,
`extra: dict`; `val_mae` property; `summary_dict()` (test_metrics stripped pre-final).

### `NaiveWorkflowResult` (dataclass)
`candidates: list[CandidateResult]`, `selected: CandidateResult`, `selected_window_start: int`;
`summary_dict()`.

---

## Run artifacts (per-run directory `reports/changepoint/<run_id>/`)

| Artifact | Writer | Notes |
|----------|--------|-------|
| `effective_config.json` | `core/reporting/run_dir.py` | `EffectiveConfig.to_dict` + split provenance + model ids + seed (SC-007/SC-012) |
| `metrics.json` | `core/reporting/artifacts.py` | 3 methods × {mae,rmse,wape,smape} + winner (FR-036) |
| `agent_trace.json` | `core/reporting/artifacts.py` | visual, full diagnostics, naive summary, iterations, rejected sigs, accepted, final case, `visual_analysis_enabled`, `hidden_diagnostics`, `removed_tools`, prompt ids+versions, model ids (FR-037) |
| `report.md` | `core/reporting/artifacts.py` | narrative explanation w/ before/after deltas vs naive + limitations (Principle VI) |
| `events.jsonl` | `core/events/sink.py` | one `StageEvent.to_dict()` per line (FR-030) |
| `event_payloads/<seq>.json` | sink | oversized payloads referenced by `$ref` (FR-031) |
| `agent_context.png` | `pipelines/.../viz.py` | training-only image (visual on only); never re-fed to an agent |
| `forecast_comparison.png` | `pipelines/.../viz.py` | human-only, post-final (FR-035) |

---

## Exceptions (core-owned, fail-fast, field-naming)

| Exception | Base | Raised for |
|-----------|------|-----------|
| `ConfigError` | `RuntimeError` | unknown/missing diagnostic or tool key, malformed value, empty model id, attempt to disable `full_history_default`, lockstep mismatch (FR-010/SC-008) |
| `SplitError` | `RuntimeError` | ambiguous split, ratios ≠ 1.0, non-positive/overlapping segment, test horizon > rows (FR-020) |
| `ToolBoundsError` | `ValueError` | param out of bounds / unknown / disabled tool (normal rejection, not a stage failure) |
| `ModelUnavailableError` | `RuntimeError` | configured model id unusable — no silent fallback (FR-036) |
| `StageError` | `RuntimeError` | a genuine stage failure (e.g. visual-first invariant violated when visual on, Prophet crash) → terminal error event, fail-fast (FR-032) |
