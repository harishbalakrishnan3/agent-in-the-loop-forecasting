# Quickstart & Validation: Drift Dataset Generation & Procurement

Runnable scenarios that prove the feature works end-to-end. These mirror the spec's acceptance
scenarios and Success Criteria. Implementation lives behind the API in
[contracts/generator-api.md](./contracts/generator-api.md); corpus layout in
[contracts/corpus-format.md](./contracts/corpus-format.md); entities in
[data-model.md](./data-model.md).

## Prerequisites

```bash
uv sync                       # shared venv from uv.lock
uv add plotly kaleido         # NEW deps for the visual overlay (run once during implementation)
```

## 1. Run the test suite (Principle II — built test-first)

```bash
uv run --extra dev pytest tests/pipelines/drift tests/core/datasets
```

**Expected**: green. Covers — per-flavor injection correctness, label correctness,
reproducibility (seed `42` ⇒ identical output), knob-validation rejections, combined-flavor
labeling, real-series loader shape/flag, `Case` serialization round-trip, corpus write/read/
enumerate identity, and overlay structure.

## 2. Generate a single labeled case (US1, SC-001/SC-002)

```python
from ailf.pipelines.drift.datasets import generate_case, DriftFlavor

case = generate_case(DriftFlavor.mean_level, seed=42)   # seed defaults to 42
assert case.labeled and case.is_synthetic
assert case.labels[0]["flavor"] == "mean_level"
assert case.labels[0]["affected_component"] == "trend"
# reproducibility:
again = generate_case(DriftFlavor.mean_level, seed=42)
assert again.series == case.series and again.labels == case.labels
```

**Expected**: a univariate `Case` with one `DriftLabel`; regeneration is identical.

## 3. Generate an ambiguous (mid-Δt) case (US3, SC-004)

```python
from ailf.pipelines.drift.datasets import generate_case, DriftFlavor, GeneratorConfig

narrow = generate_case(DriftFlavor.mean_level, seed=42, config=GeneratorConfig(transition_width=3))
wide   = generate_case(DriftFlavor.mean_level, seed=42, config=GeneratorConfig(transition_width=120))
# narrow concentrates the change in a few steps; wide spreads it across many.
```

**Expected**: both succeed; labels record the respective `transition_width`.

## 4. Build the reproducible eval corpus (US2, SC-003/SC-007)

```bash
uv run python -m ailf.pipelines.drift.corpus          # writes to data/synthetic/drift/
```

**Expected**: ≈100 single-flavor cases (≈25 × 4) + ≈10 combined cases, each as
`series.csv` + `labels.json`, plus `corpus.json`. Re-running reproduces an identical corpus.

```python
from ailf.pipelines.drift.corpus import load_corpus
cases = list(load_corpus("data/synthetic/drift"))
assert len(cases) >= 110
assert all(c.labels for c in cases if c.labeled)
```

## 5. Load real demo series (US4, SC-005)

```python
from ailf.pipelines.drift.datasets import load_air_passengers, load_mauna_loa_co2

ap = load_air_passengers()
co2 = load_mauna_loa_co2()
assert not ap.labeled and not co2.labeled        # excluded from precision/recall
assert ap.metadata["qualitative_drift"]          # documented behavior
```

**Expected**: both load through the same `Case` interface, flagged unlabeled.

## 6. Visually confirm drift (US5, SC-006)

```python
from ailf.core.datasets.viz import save_drift_overlay

png, html = save_drift_overlay(case, "reports/")           # synthetic → onset marker present
save_drift_overlay(load_air_passengers(), "reports/")      # real → no onset marker
```

**Expected**: paired `.png` + `.html` written under `reports/` for manual inspection; the
synthetic overlay shows observations + rolling mean + rolling-std band with a vertical onset
marker; the real overlay shows the same overlay without a marker.

## Success-criteria traceability

| Scenario | Validates |
|----------|-----------|
| 1 (tests) | SC-001, SC-002, and the deterministic-logic gate (Principle II) |
| 2 | SC-001, SC-002 (US1) |
| 3 | SC-004 (US3) |
| 4 | SC-003, SC-007 (US2) |
| 5 | SC-005 (US4) |
| 6 | SC-006 (US5) |
