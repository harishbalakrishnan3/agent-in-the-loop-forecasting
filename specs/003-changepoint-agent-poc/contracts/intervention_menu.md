# Contract: Bounded Intervention Menu

The ReAct node MAY ONLY return `tool` ∈ this set, with `params` inside the stated bounds
(FR-026..029, SC-009). The validation node enforces bounds; an out-of-bounds proposal is
rejected before validation and the node is re-prompted (edge case). Tuning tools may sweep
their grid in the validation node and keep the best-on-holdout combination.

## Common inputs
- `split: SeriesSplit`, `diagnostics: DiagnosticsBundle`, `seasonal_period: int`.
- All fits are `prophet.Prophet`. Validation fit uses `fit_idx`; scored on `val_idx`. Final fit
  uses `train_idx`; scored on `test_idx`.

## 1. `recent_window`
Retrain default `Prophet()` from a recent changepoint to `train_end`.
- `params`: `{ "window_start": "latest" | "primary" }` → start index from `detected_changepoints`.
- Bounds: only those two anchors. No other config.
- Maps to failure mode: clean recent regime change with enough post-change history.

## 2. `full_history_step_regressor`  (permanent level shift)
Keep full history; add binary step regressor(s) = 1 after each chosen changepoint, extended flat
across the forecast horizon.
- `params`: `{ "changepoints": "primary" | "all_detected", "min_jump": float>=0 }`.
- Bounds: changepoints from `detected_changepoints` only; `min_jump` filters by
  `local_boundary_jumps`. Default Prophet otherwise.

## 3. `full_history_ramp_regressor`  (gradual transition)
Keep full history; add clipped linear ramp regressor(s) over candidate drift interval(s),
held at the end-value beyond the interval.
- `params`: `{ "intervals": "primary" | "all_candidate", }` from `candidate_drift_intervals`.
- Bounds: intervals must come from diagnostics; ramp clipped to `[0,1]` then scaled by fit.

## 4. `full_history_clean_event`  (irregular temporary events)
Keep full history; linearly interpolate `y` across selected `candidate_event_blocks`, then fit
default Prophet on the cleaned series.
- `params`: `{ "blocks": "all_closed" | [block_index...] }`.
- Bounds (FR-026a): only blocks with `closed_before_origin == true` are eligible; selecting any
  block touching/after the forecast origin is rejected.

## 5. `full_history_prophet_tuned_holidays`  (recurring calendar-like event)
Keep full history; encode recurring windows from `recurring_event_summary.windows` as Prophet
holidays; tune bounded hyperparameters incl. holiday prior.
- `params` grid:
  - `changepoint_prior_scale ∈ {0.01, 0.05, 0.1, 0.5}`
  - `seasonality_prior_scale ∈ {1.0, 10.0}`
  - `holidays_prior_scale ∈ {1.0, 10.0}`
  - `seasonality_mode ∈ {"additive", "multiplicative"}`
  - `changepoint_range ∈ {0.8, 0.9}`
- **Gate (FR-031)**: DISALLOWED when `recurring_event_summary.is_calendar_recurring == false`.
  A proposal of this tool under that condition is rejected before validation.

## Action signature & rejection (FR-020)
`action_signature = tool + "|" + json.dumps(params, sort_keys=True)`. A signature in
`rejected_signatures` MUST NOT be proposed again; the node is re-prompted with the rejection
list each iteration. Loop runs ≤ 5 iterations.

## Acceptance (FR-020, clarification)
A candidate is **accepted** iff `candidate.val_mae < naive_selected.val_mae` (strictly; ties do
not accept). On acceptance the loop stops. If the budget exhausts with no acceptance, the
agent's **best-val proposal** (lowest `val_mae` among generated proposals) becomes
`final_candidate` (`final_case = "best_proposal_no_beat"`). The bounded menu plus re-prompting
on rejection guarantees at least one valid proposal, so a final candidate always exists.

## Family-coverage expectation (SC-008)
Across the 5 scenarios each of the four structural families must be *demonstrated* ≥1× — either
the accepted winner OR the agent's best-validation proposal in some scenario. Metadata
`expected_intervention_family` per scenario indicates the intended winner (audit-only; not shown
to the agent): `level_shift→step`, `gradual_drift→ramp`, `temporary_event→clean`,
`many_temporary_events→clean`, `prophet_prior_tuning→holidays`. Each family has a dedicated
fixture, so coverage is achievable honestly. Verified at run time, not assumed.
