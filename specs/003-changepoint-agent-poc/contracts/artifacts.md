# Contract: Output Artifacts

Per-scenario run dir: `pocs/changepoint/runs/<timestamp>/<scenario_id>/`. Cross-scenario summary
at `pocs/changepoint/runs/<timestamp>/summary.md`. All bulk output is gitignored.

## `agent_context.png`  (FR-034, SC-002) — agent input
- The EXACT training-only image shown to `visual_inspection_node`.
- Content: line plot of `ds,y` for `train_idx` only. Title = scenario_id. No future shading, no
  test points, no changepoint/boundary annotations, no audit info.
- Rendered by `viz.render_agent_context()` from `y[train_idx]` exclusively.

## `forecast_comparison.png`  (FR-035) — human-only, post-eval
- Produced only at/after `final_evaluation_node`; NEVER passed to any agent node.
- Series: train history; hidden-test actuals; full-history Prophet forecast; naive workflow
  forecast; agent final forecast. Legend names each. Vertical line at `forecast_origin`.

## `metrics.json`  (FR-036) — MetricsReport schema (see data-model.md)
- Test metrics for all three methods + `winner` (lowest test MAE). Human-readable, indented.

## `agent_trace.json`  (FR-037) — AgentTrace schema (see data-model.md)
- MUST contain: `visual`, `diagnostics`, `naive_summary`, `iterations[]` (each proposal +
  val_result + beat_naive), `rejected_signatures[]`, `accepted`, `final_candidate`,
  `final_case`, `model_ids{visual,react}`, `seed`. Ordering proves visual-before-decision
  (SC-003). Indented JSON.

## `summary.md`  (FR-038, SC-011) — cross-scenario
- One table row per scenario: winner, agent tool chosen, agent vs naive vs full-history test MAE,
  and whether the agent beat naive. Plus a short per-scenario narrative (visual hypothesis →
  chosen intervention → outcome). A coverage line confirming each intervention family appeared
  as an accepted/best choice at least once (SC-008).

## Developer-only (FR-039)
- Any diagnostics/debug plot is gated behind an explicit `--debug-plots` CLI flag, written to a
  `_debug/` subdir, and NEVER given to an agent node. Not produced by default.

## `.env.example` update (FR-022/023, research Decision 1)
Add documented keys (no real secrets): `VISUAL_MODEL_ID=`, `REACT_MODEL_ID=`,
`AWS_ACCESS_KEY_ID=`, `AWS_SECRET_ACCESS_KEY=`, `AWS_REGION=us-west-2`, with a comment naming the
intended defaults (Claude Opus 4.8 visual / Sonnet 4.6 react via Bedrock) without hardcoding
them in code.
