# Phase 0 Research: Agent-in-the-Loop Changepoint Forecasting POC

All NEEDS CLARIFICATION items from Technical Context resolved below. Environment facts were
verified against the live repo (`uv.lock`, installed venv, `.env`, existing fixtures).

## Verified environment facts

- **Installed**: `langgraph 1.2.4`, `langchain 1.3.8`, `langchain-core 1.4.6`, `prophet 1.3.0`,
  `darts 0.44.1`, `matplotlib 3.11.0`, `pandas`, `numpy`.
- **Missing (must add)**: `langchain-aws`, `boto3`, `botocore` (Bedrock access). `ruptures` is
  also missing — and intentionally **not** added (see Decision 2).
- **Fixtures present**: `pocs/changepoint/data/csv/{5 scenarios}.csv` +
  `pocs/changepoint/data/scenario_metadata.json` with `train_end`, `test_horizon`,
  `validation_horizon`, `n_changepoints_to_detect`, `seasonal_period=365`, and `audit_only`
  fields (true boundaries + `expected_intervention_family`).
- **`.env` present** with `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION=us-west-2`,
  `ANTHROPIC_API_KEY`, `LANGSMITH_*`. `.env.example` lacks the AWS/model-ID keys → update it.

## Decision 1 — Bedrock access via `langchain-aws.ChatBedrockConverse`

**Decision**: Add `langchain-aws` + `boto3`. Use `ChatBedrockConverse(model=<model_id>,
region_name=AWS_REGION)` for both the visual and ReAct nodes, instantiated by a factory in
`llm.py` from `VISUAL_MODEL_ID` / `REACT_MODEL_ID`. Use the Converse API (multimodal: supports
image content blocks for the visual node) rather than the legacy `ChatBedrock`/`invoke_model`.

**Rationale**: langchain 1.x is already installed; `ChatBedrockConverse` is the current
first-class Bedrock chat integration, supports image inputs (needed for `agent_context.png`),
tool/structured output (needed for the bounded intervention choice), and reads AWS creds from
the standard boto3 chain (env vars already set). LangSmith tracing auto-activates from
`LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` with no code change.

**Alternatives considered**:
- `anthropic` SDK direct Bedrock client — would bypass langchain/langgraph message plumbing and
  LangSmith tracing; rejected since the spec mandates LangGraph orchestration.
- `ChatBedrock` (legacy) — Converse API is the supported path for multimodal + tool use.

**Fail-fast (FR-024)**: `config.py` requires `VISUAL_MODEL_ID` and `REACT_MODEL_ID` to be set
(no hardcoded default IDs). On first model call, a Bedrock `ValidationException` /
`AccessDeniedException` / `ResourceNotFoundException` for the configured model surfaces as an
explicit error naming the missing model ID — never a silent switch to another model. Intended
defaults documented in `.env.example` comments (Opus 4.8 visual, Sonnet 4.6 react) but the code
does not bake them in.

## Decision 2 — Changepoint detector: Prophet trend-delta magnitude

**Decision**: A single deterministic detector used by BOTH the naive baseline and the
diagnostics. Fit a default `Prophet()` on training history, read its fitted piecewise-linear
trend deltas at the candidate changepoints, rank by absolute delta magnitude, and return the
top `n_changepoints_to_detect` (from metadata) as the detected changepoints, sorted by date.
"Latest changepoint" = max date among them; "primary changepoint" = largest-magnitude one.

**Rationale**: Per the /speckit-clarify outcome, the detection method is an implementation
detail; the only spec requirements are determinism and honoring `n_changepoints_to_detect`.
Prophet is already the forecasting engine, so using its own changepoints keeps the baseline
self-consistent and adds no dependency. Prophet fitting is deterministic for a fixed dataset
(MAP estimation, no MCMC), satisfying FR-040/SC-007. The same detected set seeds both the naive
candidate windows and the agent's diagnostics, so agent and baseline reason about identical
changepoints (spec Assumption).

**Alternatives considered**:
- `ruptures` PELT/BinSeg on the level signal — cleaner segment boundaries but adds a dependency
  and a second notion of "changepoint" diverging from Prophet's; rejected to keep one source of
  truth and avoid an extra dep.
- Hand-rolled CUSUM / rolling-mean break detector — more code, no clear benefit over Prophet's
  trend deltas for this POC.

## Decision 3 — Validation protocol: single holdout (per clarification)

**Decision**: Validation MAE is computed on a single holdout = the last `validation_horizon`
rows of the *training* region (rows `[train_end - validation_horizon, train_end)`). A candidate
is fit on rows `[0, train_end - validation_horizon)` and scored by MAE on that holdout. The
identical protocol scores naive candidate windows and agent proposals, so they are directly
comparable. Hidden test = rows `[train_end, train_end + test_horizon)`, untouched until
`final_evaluation_node`.

**Rationale**: Locked by /speckit-clarify (Option A). Simple, fully deterministic, and keeps the
naive-vs-agent comparison on one identical yardstick. The split math is verified against
metadata: e.g. `level_shift` has `train_end=760`, `validation_horizon=60`, `test_horizon=120`,
`row_count=900` → val `[700,760)`, test `[760,880)`, all within 900 rows. ✓

**Edge guard (spec edge case)**: if `validation_horizon + test_horizon > available rows` or
`train_end - validation_horizon <= 0`, fail clearly with a config error.

## Decision 4 — Bounded intervention parameter grids

**Decision**: Each tool exposes a small discrete grid; the ReAct node picks one combination, and
the validation node may sweep the grid for tuning tools and keep the best-on-holdout. Grids
(initial, bounded — full enumerations live in `contracts/intervention_menu.md`):
- `recent_window`: window start ∈ {latest changepoint, primary changepoint}.
- `full_history_step_regressor`: step at each detected changepoint ≥ some magnitude; count ∈
  {largest 1, all detected}.
- `full_history_ramp_regressor`: clipped ramp over a candidate drift interval from diagnostics;
  count ∈ {1, all candidate intervals}.
- `full_history_clean_event`: clean the diagnostics' candidate event blocks (only blocks ending
  strictly before forecast origin, per FR-026a) by linear interpolation.
- `full_history_prophet_tuned_holidays`: `changepoint_prior_scale ∈ {0.01,0.05,0.1,0.5}`,
  `seasonality_prior_scale ∈ {1.0,10.0}`, `holidays_prior_scale ∈ {1.0,10.0}`,
  `seasonality_mode ∈ {additive,multiplicative}`, `changepoint_range ∈ {0.8,0.9}`, holidays
  inferred from the recurring-event diagnostic windows.

(Note: an earlier draft also included a holiday-free `full_history_prophet_tuned` generic-tuning
tool; it was removed because it acted as an escape hatch that won scenarios without a structural
diagnosis and had no dedicated fixture. The menu is five tools.)

**Rationale**: FR-027..029 require bounded grids, not free-form config. Small grids keep Prophet
fit counts (and runtime) manageable while still letting tuning tools find a real improvement.
The agent chooses the *tool* and high-level params; the deterministic validation node enforces
bounds and resolves any grid sweep, so the agent can never emit an out-of-bounds value (SC-009).

**Alternatives considered**: letting the agent emit arbitrary floats — rejected, violates FR-029
and SC-009. Larger grids — rejected for runtime; can widen later if a scenario needs it.

## Decision 5 — Visual node multimodal contract + structured output

**Decision**: `visual_inspection_node` sends a single human message with two content blocks:
the rendered `agent_context.png` (base64 image block) and a short instruction. It returns a
strict JSON object: `{observations[], pattern_summary, hypotheses[], uncertainties[]}` parsed
via langchain structured output (Pydantic schema). The node has NO access to diagnostics or test
data and does NOT choose an intervention (FR-016). `react_decision_node` likewise returns
structured JSON: `{tool, params, visual_first_rationale, expected_effect}` constrained to the
menu; an invalid/out-of-bounds choice is rejected pre-validation and the node is re-prompted
with the rejection (FR-018, FR-020, edge case).

**Rationale**: Structured output makes the trace machine-checkable (SC-003 ordering,
visual-first rationale present) and lets the validation node mechanically bounds-check the
proposal. Keeping the two LLM nodes' schemas separate enforces the "visual must not decide"
boundary.

## Decision 6 — Run orchestration & reproducibility

**Decision**: `run_poc.py` iterates scenarios sequentially (CLI flag to run one). Per scenario
it: builds the split, fits the two baselines, renders `agent_context.png`, invokes the compiled
LangGraph, then `final_evaluation_node` scores all three methods on hidden test and writes
`metrics.json` + `agent_trace.json` + `forecast_comparison.png`. A global `numpy`/`random` seed
is set and recorded in each trace. After all scenarios, write `runs/<ts>/summary.md`. Visual ∥
diagnostics concurrency (FR-015) is expressed via two LangGraph edges from START fanning into
the decision node; LangGraph runs independent branches concurrently.

**Rationale**: Sequential scenarios keep Prophet/Bedrock load predictable and logs readable;
determinism of the non-LLM parts satisfies SC-007 (the LLM path is traced, not asserted
bit-exact). Per-timestamp run dir prevents overwrites (spec Assumption).

## Resolved unknowns summary

| Unknown | Resolution |
|---------|-----------|
| Bedrock client lib | `langchain-aws.ChatBedrockConverse` + `boto3` (add deps) |
| Changepoint method | Prophet trend-delta magnitude, top-N from metadata (no `ruptures`) |
| Validation protocol | Single holdout = last `validation_horizon` of training (clarified) |
| Param grids | Small bounded discrete grids per tool (Decision 4) |
| Visual/ReAct I/O | Structured JSON via langchain structured output (Pydantic) |
| Model fail-fast | Required env IDs; Bedrock error surfaced explicitly, no fallback |
| Concurrency | START → {visual, diagnostics} fan-out → decision (LangGraph parallel branches) |
