# Phase 1 Data Model: Streamlined Agent UI

These are the in-memory shapes the UI works with. They are **view-models and request-builders over existing core/pipeline types** — the UI introduces no persisted schema. Where a shape mirrors an existing backend type, that source is cited.

---

## 1. `UiRunConfig` (the control-pane selections)

The collected state of the left control pane, assembled by `config_builder.py`.

| Field | Type | Source / Rule |
|---|---|---|
| `dataset_mode` | `"scenario" \| "custom_csv"` | Mutually exclusive (FR-006). |
| `scenario_id` | `str \| None` | Required when mode=`scenario`; one of the ids in scenario metadata. |
| `custom_df` | `DataFrame \| None` | Required when mode=`custom_csv`; columns exactly `["ds","y"]` (validated, FR-010). |
| `train_ratio` | `float` | Custom-CSV only; default `0.8`. |
| `val_ratio` | `float` | Custom-CSV only; default `0.1`. |
| `test_ratio` | `float` | Custom-CSV only; default `0.1`. Rule: `abs(train+val+test - 1) <= 1e-6` (FR-009); each maps to ≥1 row. |
| `seasonal_period` | `int` | Custom-CSV advanced; default `365` (FR-011). |
| `n_changepoints_to_detect` | `int` | Custom-CSV advanced; default `3` (FR-011). |
| `visual_model_choice` | `ModelChoice` | One of the catalog entries (§5). |
| `reasoning_model_choice` | `ModelChoice` | One of the catalog entries (§5). |
| `visual_analysis_enabled` | `bool` | Toggle; when `False` the visual model choice is ignored (FR-015). |
| `diagnostics_enabled` | `dict[str,bool]` | Exactly the 13 `DiagnosticsBundle` keys (FR-013). |
| `tools_enabled` | `dict[str,bool]` | The 5 structural tools; the fallback `full_history_default` is forced `True` and not user-editable (FR-014). |
| `seed` | `int` | Default `1729`. |

**Derivation → backend**: `config_builder.to_override_dict(cfg)` returns the override dict for `ConfigOverride.from_dict` (see contract `run_invocation.md`). Custom-CSV split fractions and advanced params are passed to `run_scenario` as call args, **not** in the override (per research R5).

**Validation gates (pre-run, block Start on failure)**:
- mode=`custom_csv` → `custom_df` present, has `ds` & `y` columns, fractions sum to 1, enough rows for ≥1 per segment.
- mode=`scenario` → `scenario_id` set.
- always → `diagnostics_enabled` keys == the canonical 13; `tools_enabled` keys == the canonical 5 (fallback added automatically).

---

## 2. `EventViewModel` (one streamed event, rendered)

Produced by `event_view.from_event(event_dict)` from a `StageEvent.to_dict()` (`core/events/event.py`).

| Field | Type | Source |
|---|---|---|
| `seq` | `int` | `event["seq"]` (monotonic ordering key). |
| `stage` | `str` | `event["stage"]` (e.g. `"decision_iteration"`). |
| `status` | `str` | `event["status"]` ∈ `{start, complete, error}`. |
| `title` | `str` | Human label derived from stage+status (e.g. "Agent decision #2"). |
| `summary` | `str` | One-line gist (e.g. chosen tool, or "accepted / rejected: <reason>"). |
| `payload` | `dict` | `event["payload"]`, shown in an expandable box (FR-019). |
| `is_error` | `bool` | `status == "error"` (FR-020). |
| `payload_ref` | `str \| None` | If payload is an offloaded `{"$ref": "event_payloads/<seq>.json"}`, surface a reference note rather than breaking (FR-021). |
| `concurrency_group` | `str \| None` | e.g. `"visual_diagnostics"` — lets the view group concurrent stages. |

**Notable stages and their payload essence** (for `summary`/expander), from `core/events/payloads.py`:
- `config_resolved` → `{effective_config, hidden_diagnostics, removed_tools, visual_analysis_enabled}`
- `split_built` → `{provenance}`
- `changepoint_detection` → `{n_detected, detected:[{index,ds,trend_delta}]}`
- `baseline_full_history_prophet` / `baseline_naive_workflow` → validation summaries (no test metrics)
- `diagnostics_computed` → `{diagnostics (filtered), hidden}`
- `visual_inspection` → `{observations, pattern_summary, hypotheses, uncertainties, image_ref}`
- `decision_iteration` → `{i, proposal:{tool,params,action_signature,rationale,expected_effect}, menu}`
- `validation_outcome` → `{i, action_signature, beat_naive, rejected_reason}` (no val_metrics — agent never sees the score)
- `final_evaluation` → `{final_case, chosen:{tool,params}, test_metrics_by_method}`
- `run_complete` → `{winner, artifacts, run_dir}`

---

## 3. `ChartFrame` (final interactive graph input)

Built by `chart.py` from `forecast_comparison.csv` + the `changepoint_detection` payload + split boundaries.

| Column / item | Type | Source |
|---|---|---|
| `ds` | datetime | csv `ds` |
| `y_actual` | float | csv `y_actual` (present in all regions) |
| `region` | `"train"\|"val"\|"test"` | **relabeled** from csv `region` using `split.fit_end`/`train_end` (research R6); was `train`/`forecast` |
| `yhat_full_history` | float | csv (NaN in training region) |
| `yhat_naive` | float | csv |
| `yhat_agent` | float | csv |
| `changepoints` | `list[{index, ds, trend_delta}]` | `changepoint_detection` event payload |
| `region_bounds` | `{train_end_ds, val_start_ds, test_start_ds}` | derived from split boundaries for shading |
| `view_window` | `(start_ds, end_ds)` | recent training tail + full forecast region (FR-024; Assumptions) |

**Figure requirements** (FR-024/025/026): three forecast traces + actuals; train/val/test shaded distinctly; changepoint vlines; zoom/pan/hover; legend naming every series and region.

---

## 4. `Verdict`

Built by `verdict.py` from the run's `final_eval` (or `metrics.json`).

| Field | Type | Rule |
|---|---|---|
| `winner` | `"agent"\|"full_history_prophet"\|"naive_workflow"` | argmin test MAE (mirrors `reporting/artifacts.py:31-33`). |
| `agent_mae` / `naive_mae` / `full_history_mae` | float | from each method's `test_metrics.mae`. |
| `margin_vs_naive` | float | `naive_mae - agent_mae` (positive = agent better). |
| `headline` | str | e.g. "Agent wins — 12.4% lower MAE than the naive baseline." |

---

## 5. `ModelChoice` catalog (`ui/models.py`)

A fixed, small catalog of valid choices. The UI shows friendly labels; the value is a **Bedrock-form model id** (the backend translates to native when provider=anthropic — research R4).

| Friendly label | `model_id` (Bedrock-form) | Valid role |
|---|---|---|
| Claude Opus 4.8 | `us.anthropic.claude-opus-4-8` | visual, reasoning |
| Claude Sonnet 4.6 | `us.anthropic.claude-sonnet-4-6` | visual, reasoning |

> Defaults match `config.yaml`: visual = Opus 4.8, reasoning = Sonnet 4.6. The catalog is the single place to add more choices later; ids must exist in the translation table or follow its `us.anthropic.*` heuristic.

---

## 6. Relationships

```
UiRunConfig --to_override_dict--> ConfigOverride.from_dict ──┐
UiRunConfig (split fractions, advanced) ────────────────────►├─► run_scenario(scenario_id|series_df, override, extra_sinks=[QueueEventSink(q)])
                                                             │        │
QueueEventSink ──put(event.to_dict())──► queue ──drain──► EventViewModel*  (live, FR-017/018)
                                                             │        │
run_scenario return {final_eval, winner, csv_path} ──────────┘        ▼
   ├─► Verdict (winner + margin)                                  rendered stream
   └─► forecast_comparison.csv ─► ChartFrame ─► Plotly figure (FR-023/024/025/026)
```
