# Quickstart & Validation Guide

How to run the POC and verify it satisfies the spec's success criteria. See `data-model.md`
and `contracts/` for structure details — not duplicated here.

## Prerequisites

1. **Dependencies** (two are missing from the current venv):
   ```bash
   uv add langchain-aws boto3        # adds Bedrock access; commits uv.lock
   uv sync
   ```
   Already present: `langgraph`, `langchain`, `prophet`, `darts`, `matplotlib`, `pandas`, `numpy`.

2. **Environment** — copy and fill `.env` (gitignored). Required keys:
   ```
   VISUAL_MODEL_ID=<Bedrock model id for the visual node, e.g. Claude Opus 4.8>
   REACT_MODEL_ID=<Bedrock model id for the ReAct node, e.g. Claude Sonnet 4.6>
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   AWS_REGION=us-west-2
   LANGSMITH_TRACING=true            # optional; enables tracing if API key present
   LANGSMITH_API_KEY=...             # optional
   LANGSMITH_PROJECT=agent-in-the-loop-forecasting
   ```
   (The repo `.env` already has AWS + LangSmith values; add the two `*_MODEL_ID` keys.)

3. **Fixtures** — already committed: `pocs/changepoint/data/csv/*.csv` +
   `pocs/changepoint/data/scenario_metadata.json`. No generation needed (FR-001/004).

## Run

```bash
# All five scenarios → pocs/changepoint/runs/<timestamp>/
uv run python pocs/changepoint/run_poc.py

# A single scenario
uv run python pocs/changepoint/run_poc.py --scenario level_shift_loses_seasonality

# Optional developer diagnostics plots (never shown to the agent)
uv run python pocs/changepoint/run_poc.py --scenario gradual_drift_loses_seasonality --debug-plots
```

## Validation scenarios (maps to Success Criteria)

| # | Check | How to verify | SC |
|---|-------|---------------|----|
| 1 | All 5 scenarios run end-to-end | run dir has 5 scenario subdirs, each with the 4 artifacts + a top-level `summary.md` | SC-001 |
| 2 | Agent image is training-only | open each `agent_context.png`; x-axis ends at `forecast_origin`; no test points/annotations | SC-002 |
| 3 | Visual-before-decision | in `agent_trace.json`, `visual` is populated and `iterations[0]` references it; `visual_first_rationale` cites visual obs before numbers | SC-003 |
| 4 | Naive trains full + every CP window | `agent_trace.json → naive_summary.candidates` includes `full_history` + one per detected changepoint; `selected` = min val_mae | SC-004 |
| 5 | Loop validates on history only | each `iterations[].val_result` has val metrics; no `test_metrics` populated until final | SC-005 |
| 6 | Test scored only after loop | `final_candidate.test_metrics` non-null; no iteration has test metrics | SC-006 |
| 7 | Deterministic baselines reproduce | run a scenario twice; full-history & naive `val_mae`/test metrics identical (seed logged in trace) | SC-007 |
| 8 | Each family demonstrated | across the 5 traces, accepted/best `tool` covers step, ramp, clean-event, holidays-tuned ≥ 1× (also summarized in `summary.md`) | SC-008 |
| 9 | Proposals within bounds | every `iterations[].proposal.params` ∈ the grids in `contracts/intervention_menu.md`; no out-of-bounds value | SC-009 |
| 10 | Fail-fast on bad model id | set `VISUAL_MODEL_ID=does-not-exist` and run one scenario → explicit error naming the model id; no silent fallback | SC-010 |
| 11 | Summary is self-explanatory | `summary.md` table states per-scenario winner + relative MAEs without needing the JSON | SC-011 |

## Smoke check (no Bedrock calls)

The deterministic substrate can be exercised without any LLM, to validate splits, detector,
diagnostics, baselines, and intervention fits in isolation:
```bash
uv run python -c "from pocs.changepoint import scenarios, baselines; \
s = scenarios.load('level_shift_loses_seasonality'); \
print('split ok', s.train_end, len(s.ds)); \
print('naive', baselines.naive_workflow(s).selected.label)"
```
Expected: prints the split sizes and the naive-selected window label, with no network/Bedrock
access. (This is a convenience check, not a formal test — POC is gate-exempt.)

## Leakage audit (manual, high-value)

- Grep the written `agent_trace.json` for any `true_injected_boundaries` or `audit_only`
  content — there should be NONE (those live only in metadata, never in state).
- Confirm `forecast_comparison.png` (which DOES show test actuals) is written only by the final
  step and is never referenced by `visual_inspection_node`.
