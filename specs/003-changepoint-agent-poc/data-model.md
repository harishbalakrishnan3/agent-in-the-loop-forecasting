# Phase 1 Data Model: Agent-in-the-Loop Changepoint Forecasting POC

All structures are plain, JSON-serializable Python (dataclasses / TypedDicts / Pydantic),
so the full agent trace can be dumped to `agent_trace.json`. Entities below map to the spec's
Key Entities. "Agent-visible" flags which fields may ever reach an LLM node.

## Scenario  (from `scenario_metadata.json`)

| Field | Type | Notes | Agent-visible |
|-------|------|-------|---------------|
| `scenario_id` | str | unique id | yes (id only) |
| `csv_path` | str | path to `ds,y` CSV | no |
| `date_column` / `target_column` / `frequency` | str | schema (`ds`,`y`,`D`) | no |
| `train_end` | int | row index; train = `[0, train_end)` | no |
| `test_horizon` | int | hidden-test length | no |
| `validation_horizon` | int | holdout length | no |
| `n_changepoints_to_detect` | int | detector target count | no |
| `seasonal_period` | int | 365 (daily yearly) | no |
| `audit_only` | object | `note`, `true_injected_boundaries`, `expected_intervention_family` | **NEVER** |

**Validation rules**: `train_end > validation_horizon > 0`; `train_end + test_horizon <=
row_count`; CSV row count matches `row_count`; `ds` strictly increasing at `frequency`.
`audit_only` is loaded into a separate audit struct that is *never* placed in graph state.

## SeriesSplit  (derived; `scenarios.py`)

| Field | Type | Definition | Agent-visible |
|-------|------|-----------|---------------|
| `ds` | list[date] | full timestamp index | train slice only |
| `y` | list[float] | full values | train slice only |
| `train_idx` | range | `[0, train_end)` | — |
| `fit_idx` | range | `[0, train_end - validation_horizon)` (for validation fits) | — |
| `val_idx` | range | `[train_end - validation_horizon, train_end)` | scores only, not values |
| `test_idx` | range | `[train_end, train_end + test_horizon)` | **NEVER** during loop |

`forecast_origin` = `ds[train_end - 1]`. The agent receives only `y[train_idx]` (and the
training-only image rendered from it).

## ChangepointSet  (`detector.py`)

| Field | Type | Notes |
|-------|------|-------|
| `changepoints` | list[{index:int, ds:date, trend_delta:float}] | top-N by |delta|, date-sorted |
| `latest` | {index, ds, trend_delta} | max-date member |
| `primary` | {index, ds, trend_delta} | max-|delta| member |

## DiagnosticsBundle  (`diagnostics.py`, training-only — FR-013/014)  — Agent-visible

| Field | Type | Meaning |
|-------|------|---------|
| `detected_changepoints` | ChangepointSet | shared detector output |
| `post_changepoint_history_len` | int | rows from latest changepoint to `train_end` |
| `post_changepoint_shorter_than_season` | bool | `post_len < seasonal_period` |
| `segment_stats` | list[{start,end,mean,std}] | per inter-changepoint segment |
| `candidate_event_blocks` | list[{start_ds,end_ds,score,closed_before_origin:bool}] | transient excursions |
| `recurring_event_summary` | {is_calendar_recurring:bool, period_days:int\|null, windows:[{start_ds,end_ds}], confidence:float} | drives holiday gating |
| `local_boundary_jumps` | list[{ds, jump}] | step magnitude at each changepoint |
| `candidate_drift_intervals` | list[{start_ds,end_ds,slope}] | gradual-ramp candidates |
| `transient_event_score` | float | how event-like vs regime-like the latest change is |
| `permanent_shift_magnitude` | float | size of the most recent persistent level change |

**Invariant**: every field is computed only from `y[train_idx]`; contains no test data and no
`audit_only` info. `recurring_event_summary.is_calendar_recurring=false` ⇒ holiday tool
disallowed (FR-031).

## VisualInspectionResult  (`visual_inspection_node`, FR-016)  — LLM output

```json
{ "observations": [str], "pattern_summary": str, "hypotheses": [str], "uncertainties": [str] }
```
No intervention field (the visual node must not decide). Derived solely from `agent_context.png`.

## InterventionProposal  (`react_decision_node`, FR-018)  — LLM output

```json
{ "tool": "<one of 5 menu names>", "params": { ... bounded ... },
  "visual_first_rationale": str, "expected_effect": str }
```
- `tool` ∈ the fixed menu (see `contracts/intervention_menu.md`).
- `params` validated against that tool's bounded grid; out-of-bounds ⇒ rejected pre-validation.
- `action_signature` = canonical `f"{tool}:{sorted(params)}"` — used to dedupe rejections (FR-020).
- `visual_first_rationale` MUST reference visual observations before numeric diagnostics (SC-003).

## CandidateResult  (validation + final)

| Field | Type | Notes |
|-------|------|-------|
| `label` | str | `full_history` \| `naive_window@<cp>` \| `agent:<action_signature>` |
| `val_mae` | float | MAE on the single holdout (`val_idx`) |
| `val_metrics` | {mae,rmse,wape,smape} | full holdout metrics |
| `test_metrics` | {mae,rmse,wape,smape} \| null | filled ONLY in final evaluation |
| `forecast` | list[float] | predictions over the relevant horizon |

## NaiveWorkflowResult  (`baselines.py`, FR-011)

| Field | Type | Notes |
|-------|------|-------|
| `candidates` | list[CandidateResult] | full history + one per detected changepoint window |
| `selected` | CandidateResult | min `val_mae` |
| `selected_window_start` | date | chosen window origin |

## AgentTrace  (→ `agent_trace.json`, FR-037)  — top-level run record

| Field | Type | Notes |
|-------|------|-------|
| `scenario_id` | str | |
| `seed` | int | recorded RNG seed (SC-007) |
| `model_ids` | {visual, react} | resolved Bedrock model IDs used |
| `visual` | VisualInspectionResult | recorded BEFORE any decision (SC-003) |
| `diagnostics` | DiagnosticsBundle | |
| `naive_summary` | NaiveWorkflowResult (val only) | the comparator |
| `iterations` | list[{i, proposal, val_result, beat_naive:bool}] | each hypothesis |
| `rejected_signatures` | list[str] | exact action signatures not re-proposed |
| `accepted` | {proposal, val_result} \| null | first to beat naive on val |
| `final_candidate` | CandidateResult | accepted, else best-val proposal (per clarification) |
| `final_case` | "accepted_beat_naive" \| "best_proposal_no_beat" | which path (FR-021); the agent always yields at least one valid proposal, so there is always a final candidate |

## MetricsReport  (→ `metrics.json`, FR-036)

```json
{ "scenario_id": str, "horizon": int,
  "methods": { "full_history_prophet": {mae,rmse,wape,smape},
               "naive_workflow": {mae,rmse,wape,smape, "selected_window": str},
               "agent": {mae,rmse,wape,smape, "tool": str, "final_case": str} },
  "winner": "<method with lowest test mae among the three; all three always have a forecast>" }
```

## State lifecycle (LangGraph)

```
START ──┬─▶ visual_inspection_node ─┐
        └─▶ diagnostics_node ───────┴─▶ react_decision_node ─▶ validation_node
                                            ▲                        │
                                            │   reject (record sig)  │ beat naive?
                                            └────────────────────────┤ no & i<5
                                                                     │ yes OR i==5
                                                                     ▼
                                                          final_evaluation_node ─▶ END
```
State is a single serializable TypedDict accumulating: split refs, diagnostics, visual result,
naive summary, iteration list, rejected signatures, accepted/final candidate. Test values enter
state only inside `final_evaluation_node`.
