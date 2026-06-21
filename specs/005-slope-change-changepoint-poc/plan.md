# Implementation Plan: Slope-Change Changepoint POC & Prophet Baseline Evaluation

**Branch**: `005-slope-change-changepoint-poc` | **Date**: 2026-06-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-slope-change-changepoint-poc/spec.md`

## Summary

A self-contained POC under `pocs/changepoint/slope_change/` that (1) generates a fixed catalog
of 10 synthetic time series whose changepoints are **changes in trend slope** (continuous
piecewise-linear trend, no level jumps) with seeded ground-truth metadata, and (2) evaluates
whether a **naive (default-configuration) Prophet** model can both locate those slope changes
(via Prophet's own automatic changepoints) and forecast a held-out future horizon. The POC
mirrors the file layout of the sibling `pocs/changepoint/level_shift/` POC but shares no code
with it. Deliverables: the generated datasets + metadata, one PNG per dataset under `plots/`, a
passing test suite, and a `slope_change_poc.md` summary report containing a per-dataset Prophet
results table plus a dedicated section calling out the complex datasets where naive Prophet
fails (high held-out forecast error and/or missed slope changes).

## Technical Context

**Language/Version**: Python 3.11 (repo `requires-python = ">=3.11"`, managed by `uv`).

**Primary Dependencies**: All already present in `pyproject.toml` — `darts` (TimeSeries
construction + generation helpers), `prophet` (the baseline under test), `pandas`/`numpy`
(data + piecewise-linear trend synthesis), `plotly` (interactive visualization), `kaleido`
(static PNG export), `pytest` (tests). No new dependencies required.

**Storage**: Filesystem only. Datasets are generated in-memory on demand (seeded, reproducible);
static plots written to `pocs/changepoint/slope_change/plots/*.png` (a small committed sample is
acceptable per CLAUDE.md; bulk artifacts under `data/`/`reports/` stay gitignored). The summary
report `slope_change_poc.md` lives in the POC directory.

**Testing**: `pytest`, run via `uv run pytest pocs/changepoint/slope_change/`. POC area is exempt
from the constitution's test-first NON-NEGOTIABLE gate, but this POC still ships tests (per
FR-018) covering generator ground-truth, reproducibility, control flatness, metadata schema, and
an end-to-end Prophet evaluation smoke on a simple and a complex dataset.

**Target Platform**: Local CLI / module run on macOS/Linux dev machines via `uv run python -m
pocs.changepoint.slope_change.<module>`.

**Project Type**: Single-project POC (throwaway exploration), not a promoted pipeline. Mirrors
`pocs/changepoint/level_shift/`.

**Performance Goals**: Not latency-sensitive. Full catalog (10 datasets × one Prophet fit +
forecast each) should complete in a couple of minutes; Prophet fit is the dominant cost. Datasets
run sequentially.

**Constraints**:
- **Slope-change semantics**: the trend MUST stay continuous at each changepoint (only its slope
  changes); generation MUST NOT introduce a level discontinuity (distinguishes this POC from
  level_shift).
- **Naive Prophet only**: default Prophet configuration, fit on the training portion only — no
  changepoint hints, custom priors, or tuning (per spec Assumptions).
- **Self-containment**: no imports from `pocs/changepoint/level_shift/` or from `src/ailf/*`; any
  shared helper is reimplemented locally (FR-017).
- **Seeded**: every dataset generated from a recorded seed; identical config+seed → identical
  series (FR-005).

**Scale/Scope**: 10 datasets, lengths ~400–2000 points, daily frequency. One contributor POC.
1 generator module, 1 Prophet-evaluation module, 1 interactive viz, 1 static export, 1 test
module, 1 spec, 1 summary report.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The constitution grants a **POC exemption**: "throwaway exploration lives in a dedicated POC area
and is exempt from the test and quality gates below." This feature lives entirely in
`pocs/changepoint/slope_change/` and imports nothing from `src/ailf/*`. Therefore the
NON-NEGOTIABLE Principle II (test-first) and the per-change merge gates do not block it. Remaining
principles are honored in spirit:

| Principle | Applies to POC? | How this plan honors it |
|-----------|-----------------|--------------------------|
| I. Importable Core (serializable boundary) | Relaxed (POC) | Generator returns a Darts `TimeSeries` + a plain JSON-serializable metadata dict; the evaluator returns a plain dataclass/dict. No UI types. Eases later promotion into `src/ailf/pipelines/changepoint/`. |
| II. Test-First (NON-NEGOTIABLE) | **Exempt** (POC) | No failing-test-first requirement, but tests ship anyway (FR-018) against planted ground truth. |
| III. Golden-set eval | Relaxed (POC) | The 10 labeled datasets with known slope-change ground truth *are* a mini golden set for detection scoring; no LLM judge involved. |
| IV. Bounded, backtest-gated (NON-NEGOTIABLE) | N/A | No agent and no interventions in this POC — it only generates data and measures a baseline. Nothing mutates a forecast. |
| V. Reproducible & honest eval | Honored | `uv` + committed lock; all seeds fixed/recorded; the evaluation reports standard forecast error on a held-out horizon for a naive baseline — exactly the "honest baseline" Principle V mandates. |
| VI. Transparent, explainable | Honored | `slope_change_poc.md` reports per-dataset detection + forecast metrics and an explicit failure section; plots make ground-truth vs. Prophet behavior inspectable. |
| VII. Shared core, independent pipelines | Honored | Work stays inside `pocs/changepoint/slope_change/`; self-contained, touches no other pipeline and no `core/`. |

**Gate result: PASS** (POC exemption + relevant principles honored in spirit). No Complexity
Tracking entries required — no new dependencies, no architectural deviation. Note: per spec
Assumptions, forecast evaluation uses a single held-out future horizon rather than Principle V's
default rolling-origin backtest; this is a deliberate, documented simplification permitted under
the POC exemption (the POC's purpose is to characterize a baseline's failure mode, not to gate an
intervention).

## Project Structure

### Documentation (this feature)

```text
specs/005-slope-change-changepoint-poc/
├── plan.md              # This file (/speckit-plan output)
├── spec.md              # Feature spec (+ Clarifications)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── datasets.md      # generator function + catalog contract
│   └── prophet_eval.md  # evaluation function + result schema contract
└── checklists/
    └── requirements.md  # Spec quality checklist (already present)
```

### Source Code (repository root)

```text
pocs/changepoint/slope_change/
├── spec.md                  # POC-local spec (mirrors level_shift/spec.md)
├── __init__.py              # package marker
├── datasets.py              # Darts-based slope-change generator + DATASET_CONFIGS (S1–S10) + generate_all_datasets()
├── prophet_eval.py          # naive Prophet fit/forecast + changepoint matching + per-dataset metrics + summary table
├── test_slope_change.py     # pytest: generator ground-truth, reproducibility, control, schema, Prophet eval smoke
├── visualize.py             # interactive Plotly dashboard (dropdown over S1–S10): series, GT slope changes, Prophet CPs, forecast-vs-actual
├── export_plots.py          # static PNG export, one per dataset → plots/
├── slope_change_poc.md      # summary report (Prophet results table + complex-dataset failure section)
└── plots/                   # exported PNGs (one per dataset)
```

**Structure Decision**: Single-project POC mirroring the existing `pocs/changepoint/level_shift/`
layout file-for-file, with the one rename that reflects the changed thesis: `level_shift`'s
`detector.py` (PELT detection) becomes `prophet_eval.py` (naive-Prophet detection *and*
forecasting evaluation), because the slope-change POC's question is "can a naive forecaster handle
this?" rather than "can a changepoint detector locate this?". All other filenames match the
sibling POC. The package is self-contained: it reimplements any small helper it needs (e.g.
segment/slope computation) rather than importing from `level_shift/` or `src/ailf/*`.

## Complexity Tracking

> No constitution violations. No new dependencies, no cross-pipeline coupling, no agent or
> intervention surface. Table intentionally empty.
