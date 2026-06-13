# Phase 1 Data Model: Drift Dataset Generation & Procurement

Entities derived from the spec's Key Entities + Functional Requirements. The public boundary is
plain serializable data (Principle I): every entity round-trips to a JSON-compatible dict.

## DriftFlavor (enum)

The four supported injected drift types, each bound to a Prophet component.

| Value | Affected component | Meaning |
|-------|--------------------|---------|
| `trend_slope` | `g(t)` (trend) | Gradual change in trend slope. |
| `mean_level` | `g(t)` (trend) | Gradual shift in level (ramp). |
| `variance_inflation` | `ε` (noise) | Gradual growth in noise spread. |
| `seasonal_amplitude` | `s(t)` (seasonality) | Seasonal swings grow/shrink (additive→multiplicative). |

`affected_component` is derivable from flavor but stored explicitly on the label for direct
scoring/breakdowns (FR-005).

## GeneratorConfig (knobs)

The reproducible parameter set that determines a single synthetic case (FR-003). All have
defaults.

| Field | Type | Default (advisory) | Notes |
|-------|------|--------------------|-------|
| `length` | int | 365 | Number of points in the series. |
| `start` | timestamp | `2015-01-01` | Index start; daily frequency by default. |
| `freq` | str | `D` | Pandas offset alias. |
| `onset` | int (index) | `length // 2` | Where drift begins (FR-003). |
| `magnitude` | float | flavor-specific | Drift strength; sign allowed (grow/shrink). |
| `transition_width` | int (steps) | `length // 5` | Δt — gradual vs changepoint-like (FR-008). |
| `duration` | int (steps) | to end of series | How long the drifted regime persists after Δt. |
| `base_noise` | float | 1.0 | Std of base Gaussian noise (ε); MUST be > 0 for `variance_inflation`. |
| `seasonality_period` | int \| None | 30 | Period of `s(t)`; required for `seasonal_amplitude`. |
| `seasonality_amplitude` | float | 5.0 | Base amplitude of `s(t)`. |
| `seed` | int | `42` | Drives an isolated `np.random.default_rng`; identical seed ⇒ identical output. |

**Validation rules** (FR-009; map to spec Edge Cases):
- `0 < onset < length`, with enough points before (`onset ≥ min_reference`) and after
  (`length - onset ≥ min_drift`) — else reject (no reference / no room for drift).
- `transition_width ≥ 1` and `onset + transition_width ≤ length` (reject or clamp; if clamped,
  label records the realized width).
- `magnitude != 0` (a zero-magnitude case would contradict a drift label).
- `variance_inflation` ⇒ `base_noise > 0`.
- `seasonal_amplitude` ⇒ `seasonality_period` is set and `seasonality_amplitude > 0`.

## DriftLabel

One injected drift's ground truth. A case holds a list of these (FR-005, FR-007).

| Field | Type | Notes |
|-------|------|-------|
| `flavor` | DriftFlavor | Which drift was injected. |
| `affected_component` | str | `trend` \| `seasonality` \| `noise`. |
| `onset_index` | int | Integer position where drift begins. |
| `onset_time` | timestamp | Same onset expressed on the series index. |
| `transition_width` | int | Realized Δt in steps (the labeled interval = `[onset, onset+width]`). |
| `magnitude` | float | Realized drift strength. |

A detection scored as a true positive if it falls within `[onset_index, onset_index +
transition_width]` (scoring lives downstream, not in this feature).

## Case (generic, core)

Domain-agnostic container in `core/datasets` reused by all three tracks. Holds one univariate
series + an opaque-to-core label record + provenance.

| Field | Type | Notes |
|-------|------|-------|
| `case_id` | str | Stable id (e.g. `drift-trend_slope-0007`). |
| `series` | `darts.TimeSeries` | Univariate. |
| `labels` | list[dict] | Serialized label records (drift uses `DriftLabel`); empty for unlabeled. |
| `is_synthetic` | bool | False for real demo series. |
| `labeled` | bool | False ⇒ excluded from precision/recall (FR-015). |
| `config` | dict \| None | The `GeneratorConfig` that produced it (None for real series). |
| `metadata` | dict | Free-form (e.g. source, qualitative drift description for real series, FR-016). |

**Serialization**: `to_dict()` / `from_dict()` produce plain JSON-compatible data; `series` ↔
timestamp/value records or a CSV path reference in the on-disk form (see corpus contract).

## DriftCase (pipeline view)

Not a separate class — the drift pipeline produces/consumes `Case` with `labels` populated by
`DriftLabel.to_dict()`. Helper accessors in `pipelines/drift` reconstruct typed `DriftLabel`s
from `case.labels`.

## EvalCorpus

The named, versioned, on-disk collection (FR-010–FR-012). Not a rich object — a directory plus a
manifest.

| Concept | Representation |
|---------|----------------|
| Corpus root | `data/synthetic/drift/` (gitignored bulk dir). |
| One case | `<case_id>/series.csv` + `<case_id>/labels.json`. |
| Manifest | `corpus.json` at root: list of `{case_id, flavor(s), labeled, config_ref}`. |
| Build config | Committed seed + knob-sweep spec in `pipelines/drift/corpus.py` (source, not bulk). |

**Composition** (FR-010, SC-003): ≈25 single-flavor cases per flavor (≈100) varying
onset/magnitude/Δt across the set + ≈10 combined-flavor cases. Regenerable to an identical state
(FR-011).

## RealDemoSeries

A curated real univariate series (FR-014–FR-016) surfaced as a `Case` with `is_synthetic=False`,
`labeled=False`, `labels=[]`, and `metadata.qualitative_drift` describing the behavior. Two
loaders: Air Passengers (growing seasonal amplitude) and Mauna Loa CO₂ (rising level +
seasonality, resampled to regular monthly frequency).

## Relationships

```
GeneratorConfig ──(generate)──▶ Case(labeled, is_synthetic=True, labels=[DriftLabel,...])
RealDemoSeries loader ─────────▶ Case(labeled=False, is_synthetic=False, labels=[])
Case ──(persist)──▶ EvalCorpus entry (series.csv + labels.json + manifest row)
Case ──(plot)─────▶ plotly overlay Figure (onset marker iff labeled) ──▶ paired .png + .html under reports/
```
