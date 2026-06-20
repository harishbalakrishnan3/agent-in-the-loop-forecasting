# Implementation Plan: Agent-in-the-Loop Changepoint Forecasting POC

**Branch**: `003-changepoint-agent-poc` | **Date**: 2026-06-14 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-changepoint-agent-poc/spec.md`

## Summary

A self-contained POC under `pocs/changepoint/` that tests whether a visual-first LangGraph
agent can beat a naive changepoint-window workflow on five hard forecasting scenarios. For
each scenario the POC trains three methods on the same train/validation/hidden-test split:
(1) full-history default Prophet, (2) a naive workflow that picks the best changepoint window
by validation MAE, and (3) a LangGraph agent that inspects a training-only chart (vision
model), receives deterministic diagnostics, then iterates up to 5 times choosing bounded
interventions validated on a single historical holdout before the hidden test is ever
touched. Outputs per scenario: `agent_context.png`, `forecast_comparison.png`,
`metrics.json`, `agent_trace.json`, plus a cross-scenario `summary.md`. Models are read from
`VISUAL_MODEL_ID` / `REACT_MODEL_ID` (intended: Claude Opus 4.8 + Sonnet 4.6 via Bedrock),
failing clearly if unavailable.

## Technical Context

**Language/Version**: Python 3.11 (repo `requires-python = ">=3.11"`, managed by `uv`).

**Primary Dependencies**: `prophet` (forecasting), `langgraph` 1.x + `langchain` 1.x +
`langchain-aws` (ReAct/graph + Bedrock chat models), `boto3`/`botocore` (Bedrock transport),
`pandas`/`numpy` (data), `matplotlib` (training-only chart + comparison plot), `python-dotenv`
(load `.env`). LangSmith tracing via env vars (no explicit dep needed — langchain reads
`LANGSMITH_*`). Changepoint detection: Prophet's own fitted changepoints ranked by trend-delta
magnitude (no new dependency; `ruptures` rejected to avoid an extra dep — see research.md).

**Storage**: Filesystem only. Input CSVs at `pocs/changepoint/data/csv/*.csv` + companion
`pocs/changepoint/data/scenario_metadata.json` (already present). Outputs written under a
per-run directory `pocs/changepoint/runs/<timestamp>/<scenario_id>/` (gitignored bulk;
`reports/` and `data/` are already gitignored per CLAUDE.md).

**Testing**: POC area is exempt from the test-first gate (constitution POC exemption). Light
smoke checks only; no formal `tests/` suite required for this feature. Deterministic
components (split, detector, naive selection, metrics) are written to be re-runnable and
seeded so results reproduce.

**Target Platform**: Local CLI / module run on macOS/Linux dev machines via
`uv run python -m ...` or `uv run python pocs/changepoint/run_poc.py`.

**Project Type**: Single-project POC (throwaway exploration), not a promoted pipeline.

**Performance Goals**: Not latency-sensitive. Whole-suite run (5 scenarios × up to 5 agent
iterations × Prophet fits) should complete in minutes; Prophet fit count is the dominant cost.
Acceptable to run scenarios sequentially.

**Constraints**:
- Strict no-leakage: agent sees only `ds,y` rows `[0:train_end)` and a training-only image.
  Hidden-test values, audit-only fields, and ground-truth boundaries never reach any LLM node.
- Bounded interventions only — fixed menu, bounded parameter grids; no free-form Prophet config.
- Validation = single holdout (last `validation_horizon` block of training), same protocol for
  naive selection and agent acceptance (per clarification).
- Model IDs read from env; fail clearly (no silent fallback) if the configured Bedrock model is
  unavailable.

**Scale/Scope**: 5 scenarios, 900–1610 rows each, daily frequency, seasonal_period=365. 3
methods per scenario. 6 intervention tools. Single contributor POC.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution grants a **POC exemption**: "throwaway exploration lives in a dedicated POC
area and is exempt from the test and quality gates below." This feature lives entirely in
`pocs/changepoint/` and imports nothing from `src/ailf/core` (the core modules are empty
stubs). Therefore the NON-NEGOTIABLE Principle II (test-first) and the per-change gates do not
block this POC. The remaining principles are still honored *in spirit* because the POC's whole
thesis is the safety story:

| Principle | Applies to POC? | How this plan honors it |
|-----------|-----------------|--------------------------|
| I. Importable Core (serializable boundary) | Relaxed (POC) | All node I/O is plain JSON-serializable dicts/dataclasses so the trace can be dumped; no UI types. Eases later promotion. |
| II. Test-First (NON-NEGOTIABLE) | **Exempt** (POC) | No failing-test-first requirement. Deterministic pieces kept small + seeded; optional smoke check in quickstart. |
| III. Golden-set eval | Relaxed (POC) | The 5 scenarios with `audit_only.expected_intervention_family` *are* a mini golden set; SC-008 checks family coverage. Not auto-graded by an LLM judge here. |
| IV. Bounded, backtest-gated (NON-NEGOTIABLE) | Honored | Fixed intervention menu + bounded grids (FR-026..029); every proposal validated on a historical holdout before acceptance; hidden test only after the loop (FR-019, FR-020, FR-009). This is the POC's core. |
| V. Reproducible & honest eval | Honored | `uv` + committed lock; seeds fixed/logged; naive baseline is the honest comparator; metrics.json reports MAE/RMSE/etc. for all methods, not cherry-picked. |
| VI. Transparent, explainable | Honored | `agent_trace.json` + `summary.md` make every visual obs, diagnostic, proposal, rejection, and accept/reject decision inspectable (FR-037, FR-038). |
| VII. Shared core, independent pipelines | Honored | Work stays inside `pocs/changepoint/`; touches no other pipeline and no `core/`. |

**Gate result: PASS** (POC exemption + safety principles honored in spirit). No Complexity
Tracking entries required — adding `langchain-aws`/`boto3` is a normal dependency addition, not
an architectural deviation. Note: the spec's single-holdout validation deliberately diverges
from Principle V's default rolling-origin backtest; this is documented in the spec Assumptions
and permitted under the POC exemption.

## Project Structure

### Documentation (this feature)

```text
specs/003-changepoint-agent-poc/
├── plan.md              # This file (/speckit-plan output)
├── spec.md              # Feature spec (+ Clarifications)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (intervention menu + node I/O + trace schema)
│   ├── intervention_menu.md
│   ├── graph_nodes.md
│   └── artifacts.md
└── checklists/
    └── requirements.md  # Spec quality checklist (already present)
```

### Source Code (repository root)

```text
pocs/changepoint/
├── data/                          # ALREADY PRESENT (fixtures committed)
│   ├── scenario_metadata.json     # 5 scenarios + audit_only (never shown to agent)
│   └── csv/<scenario_id>.csv      # ds,y series
├── config.py                      # env loading: model IDs, AWS region, LangSmith; fail-fast checks
├── scenarios.py                   # load metadata + CSV → Scenario / SeriesSplit (train/val/test)
├── detector.py                    # deterministic changepoint detection (Prophet trend-delta), honors n_changepoints_to_detect
├── diagnostics.py                 # all FR-014 diagnostics from training history only
├── forecasting.py                 # Prophet fit/predict helpers; regressor & holiday construction; metrics (MAE/RMSE/...)
├── baselines.py                   # full-history Prophet + naive changepoint-window workflow
├── interventions.py               # the 5 bounded tools + bounded param grids + action signatures
├── viz.py                         # agent_context.png (training-only) + forecast_comparison.png (post-eval, human-only)
├── llm.py                         # Bedrock chat model factory (visual + react) from config; structured-output parsing
├── graph/
│   ├── state.py                   # LangGraph state TypedDict (serializable)
│   ├── nodes.py                   # visual_inspection, diagnostics, react_decision, validation, final_evaluation
│   └── build.py                   # graph wiring: visual ∥ diagnostics → decision ↔ validation loop → final
├── prompts/
│   ├── visual_inspection_v1.md
│   └── react_decision_v1.md
├── run_poc.py                     # CLI entrypoint: run all (or one) scenario(s), write artifacts + summary.md
├── export_scenario_csvs.py        # OPTIONAL fixture generator (runtime must NOT depend on it) — may already exist
└── runs/<timestamp>/<scenario_id>/  # OUTPUT (gitignored): agent_context.png, forecast_comparison.png, metrics.json, agent_trace.json
    └── summary.md                   # cross-scenario (written at runs/<timestamp>/summary.md)
```

**Structure Decision**: Single self-contained POC package under `pocs/changepoint/`. It does
**not** import `src/ailf/core` (those modules are empty stubs) — keeping the POC fail-fast and
independently runnable, consistent with the POC README and constitution Principle VII. Modules
are split so the deterministic substrate (detector, diagnostics, baselines, interventions,
metrics) is plain Python testable in isolation, the LLM boundary is confined to `llm.py` +
`graph/nodes.py`, and the LangGraph wiring expresses the spec's stage graph (visual ∥
diagnostics → decision ↔ validation → final). If the POC proves out, these modules map cleanly
onto a future `src/ailf/pipelines/changepoint/` promotion.

## Complexity Tracking

> No constitution violations requiring justification. POC exemption applies; dependency
> additions (`langchain-aws`, `boto3`) are routine. Table intentionally empty.
