# Implementation Plan: Drift Dataset Generation & Procurement

**Branch**: `002-drift-dataset-generation` | **Date**: 2026-06-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-drift-dataset-generation/spec.md`

## Summary

Build the drift track's data layer: a seeded, parameterized synthetic generator that emits
univariate `TimeSeries` with machine-readable ground-truth drift labels across four
Prophet-component flavors (trend-slope, mean-level ramp, variance inflation,
seasonal-amplitude), plus a reproducible on-disk eval corpus, ~2 unlabeled real demo series
behind the same interface, and a rolling-mean/std visual-confirmation overlay.

Technical approach: drift-specific generation, the `DriftCase`/`DriftLabel` schema, flavor
injectors, real-series loaders, and the corpus builder live in `src/ailf/pipelines/drift/`.
Generic, domain-agnostic plumbing reused by all three tracks — the serializable case container,
corpus persistence/enumeration, and the rolling-stats overlay plot — lives in
`src/ailf/core/datasets/` (a review-gated shared-core touch). Everything is built test-first
against synthetic series with known injected ground truth.

## Technical Context

**Language/Version**: Python ≥3.11 (single `uv` workspace, lockfile committed)

**Primary Dependencies**: Darts 0.44.1 (`darts.utils.timeseries_generation` for base series +
`darts.datasets.AirPassengersDataset`), numpy, pandas, statsmodels 0.14.6
(`statsmodels.datasets.co2` for the Mauna Loa CO₂ demo series — Darts has no built-in CO₂ level
series), and **plotly** (interactive overlay; HTML export native) + **kaleido** (static PNG
export). Darts/numpy/pandas/statsmodels are already in `uv.lock`; **plotly + kaleido are NEW deps
to be added via `uv add` during implementation** (not yet in the lockfile).

**Storage**: On-disk eval corpus under `data/synthetic/drift/` (gitignored bulk dir). Each case
= a series file + a JSON label sidecar; corpus driven by a committed seed/knob config so it is
regenerable. In-memory typed objects available without touching disk. Visual-confirmation
overlays are written as paired `.png` + `.html` under `reports/` (gitignored) for manual
inspection.

**Testing**: pytest (in the `dev` optional-dependency group). Run with
`uv run --extra dev pytest tests/pipelines/drift`.

**Target Platform**: Local dev / CI (Linux + macOS); importable library, no runtime service.

**Project Type**: Importable Python library (shared core + thin per-use-case pipelines).

**Performance Goals**: Not latency-sensitive. The full ~110-case corpus must generate in
seconds (synthetic series of low-thousands of points). No throughput targets.

**Constraints**: Deterministic — identical seed + knobs ⇒ identical series and labels. Public
generator/loader API and label records MUST be plain serializable data (Principle I). Must not
import other pipelines (Principle VII).

**Scale/Scope**: ~100 single-flavor cases (≈25 × 4 flavors) + ≈10 combined-flavor cases; 2 real
demo series; series length on the order of a few hundred to a few thousand points each.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Importable Core (Serializable Boundary)** — PASS. The generator and loaders are pure
  library functions; `DriftCase`/`DriftLabel` serialize to plain dicts/JSON. No UI/front-end
  types. Series persisted as plain CSV/records, labels as JSON.
- **II. Test-First for Deterministic Logic (NON-NEGOTIABLE)** — APPLIES, PASS-by-plan. The
  generator is deterministic logic, so it is built test-first: failing tests assert injected
  ground truth (correct flavor/onset/transition-width/component), reproducibility (same
  seed ⇒ identical output), and knob-validation rejections, before implementation. Tests live in
  `tests/pipelines/drift/` and `tests/core/` (for the generic plumbing).
- **III. Agent Quality Through Golden-Set Evaluation** — INDIRECT. No LLM in this feature, but
  this is precisely the labeled substrate the drift golden set will rest on; labels are designed
  to be sufficient for precision/recall/FPR scoring.
- **IV. Bounded Interventions, Backtest-Gated (NON-NEGOTIABLE)** — N/A. No agent, no
  interventions, no backtest in this feature.
- **V. Reproducible & Honest Evaluation** — PASS. Seeds fixed and recorded in the committed
  corpus config; `uv` lockfile current; the exact corpus is regenerable from the repository.
- **VI. Transparent, Explainable Outputs** — PARTIAL/SUPPORTING. No agent report here, but the
  rolling-stats overlay (plotly, exported as PNG + interactive HTML) is the human-inspectable
  acceptance aid (reproduces proposal Figure 3).
- **VII. Shared Core, Independent Pipelines** — PASS-with-flag. Drift-specific logic stays in
  `pipelines/drift/`. Generic case container, corpus IO, and overlay go in `core/datasets/` —
  a deliberate, review-gated shared-core change that keeps core tests green and adds no
  pipeline-to-pipeline imports. See Complexity Tracking.

**Gate result: PASS.** No NON-NEGOTIABLE violations. One justified shared-core touch tracked below.

## Project Structure

### Documentation (this feature)

```text
specs/002-drift-dataset-generation/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── generator-api.md
│   └── corpus-format.md
├── checklists/
│   └── requirements.md  # from /speckit-specify
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/ailf/
├── core/
│   └── datasets/
│       ├── __init__.py        # (exists) shared dataset utilities — to be filled
│       ├── case.py            # NEW: generic serializable Case container (series + label record)
│       ├── corpus.py          # NEW: write/read/enumerate an on-disk case corpus (series + JSON sidecar)
│       └── viz.py             # NEW: plotly rolling-mean/std overlay → PNG + HTML (optional onset markers)
└── pipelines/
    └── drift/
        ├── __init__.py        # (exists)
        ├── datasets.py        # (exists, stub) drift flavors, DriftLabel/DriftFlavor, knobs,
        │                      #   single + combined generation, real-series loaders
        ├── corpus.py          # NEW: drift corpus build config + CLI entry (materialize ≈110 cases)
        ├── tools.py           # (exists, stub) NOT touched by this feature
        ├── pipeline.py        # (exists, stub) NOT touched by this feature
        └── prompts/           # NOT touched by this feature

tests/
├── core/
│   └── datasets/              # NEW: tests for case/corpus/viz generic plumbing
└── pipelines/
    └── drift/                 # NEW: tests for flavors, labels, reproducibility, validation, loaders

data/
└── synthetic/
    └── drift/                 # generated corpus output (gitignored bulk dir)
```

**Structure Decision**: Library layout from decision 0001 (shared core + independent pipelines).
Drift-owned code is confined to `src/ailf/pipelines/drift/` and `tests/pipelines/drift/`. The
generic, reusable trio (`case.py`, `corpus.py`, `viz.py`) goes in `src/ailf/core/datasets/`
because the changepoint and anomaly stubs explicitly defer generic Darts plumbing to core and
all three tracks need the same container/IO/overlay — duplicating it three times would violate
"no triplicated logic." This core touch is review-gated per Principle VII.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Touching shared `core/datasets/` on a drift feature branch | The case container, corpus persistence/enumeration, and rolling-stats overlay are domain-agnostic and needed identically by all three tracks; the existing changepoint/anomaly stubs explicitly say generic plumbing belongs in `core.datasets`. | Defining these in `pipelines/drift/` would force changepoint/anomaly to copy them (triplicated logic) or import the drift pipeline (forbidden cross-pipeline dependency, Principle VII). Keeping the *generic* parts in core with drift-specific label semantics in the pipeline is the minimal coherent split. |
