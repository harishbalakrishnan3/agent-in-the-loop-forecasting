# Contract: Generator & Loader API

The library surface this feature exposes. Signatures are illustrative (Python type intent), not
final code. The contract is: behavior, inputs, outputs, errors, and serializability — all public
returns are plain serializable data or the project's `darts.TimeSeries` house type.

## Synthetic generation (`ailf.pipelines.drift.datasets`)

### `generate_case(flavor, *, seed, config=None) -> Case`

Generate one single-flavor labeled drift case.

- **Inputs**: `flavor: DriftFlavor`; `seed: int` (required, drives an isolated RNG);
  `config: GeneratorConfig | None` (defaults applied when omitted).
- **Output**: a `Case` with `is_synthetic=True`, `labeled=True`, `labels=[DriftLabel]` (length 1),
  `config` populated.
- **Guarantees**:
  - Same `(flavor, seed, config)` ⇒ identical `series` values and identical `labels` (FR-004).
  - The realized series actually exhibits the injected drift over `[onset, onset+Δt]` (the data
    matches its own label).
  - `affected_component` on the label matches the flavor's Prophet component (FR-002).
- **Errors** (raise a validation error, do not emit a mislabeled case — FR-009):
  - onset too close to either boundary (no reference regime / no room for drift);
  - `transition_width < 1` or `onset + transition_width` past end (reject — no silent clamp);
  - `magnitude == 0`;
  - `variance_inflation` with `base_noise <= 0`;
  - `seasonal_amplitude` without seasonality configured.

### `generate_combined_case(flavors, *, seed, configs=None) -> Case`

Generate one case with multiple injected flavors (FR-007).

- **Inputs**: `flavors: list[DriftFlavor]` (length ≥ 2); `seed`; optional per-flavor configs.
- **Output**: a `Case` with `labels` containing one `DriftLabel` per injected flavor; every
  injected flavor represented (FR-007).
- **Guarantees**: reproducible; each flavor's effect present and individually labeled. Overlapping
  onsets/components still yield a coherent, fully-labeled case (Edge Case: combined conflicts).

### Ambiguous cases

No separate function — produced via `generate_case` with `transition_width` in the ambiguous
band (FR-008). Contract: a small Δt concentrates the change in a narrow window; a large Δt spreads
it across many points (US3 acceptance scenario 2).

## Real demo series (`ailf.pipelines.drift.datasets`)

### `load_air_passengers() -> Case` / `load_mauna_loa_co2() -> Case`

- **Output**: a `Case` with `is_synthetic=False`, `labeled=False`, `labels=[]`,
  `metadata.qualitative_drift` set (FR-016), univariate series via the **same** `Case` interface
  as synthetic (FR-014).
- **Guarantees**: CO₂ series resampled to a regular monthly frequency (no gaps surprise
  consumers — Edge Case). Marked unlabeled ⇒ excluded from precision/recall (FR-015).

### `list_real_series() -> list[str]`

Enumerate available real demo series (≈2) for discovery (US4 scenario 3).

## Corpus build (`ailf.pipelines.drift.corpus`)

### `build_corpus(root, *, base_seed, overwrite=False) -> CorpusManifest`

Materialize the canonical eval corpus to disk (FR-010, FR-011).

- **Inputs**: `root: Path` (default `data/synthetic/drift/`); `base_seed: int` (committed in the
  build config); `overwrite`.
- **Output**: writes ≈25 single-flavor cases/flavor (≈100) + ≈10 combined cases, each as
  `series.csv` + `labels.json`, plus a `corpus.json` manifest; returns the manifest.
- **Guarantees**: re-running with the same `base_seed` + build config reproduces an identical
  corpus (FR-011, SC-003). Per-case seeds derived deterministically from `base_seed` + index.
- **CLI**: `uv run python -m ailf.pipelines.drift.corpus` builds with committed defaults.

### Corpus consumption

See `corpus-format.md`. `load_corpus(root) -> Iterable[Case]` enumerates every case with its
labels without per-case bespoke parsing (FR-012).

## Visualization (`ailf.core.datasets.viz`)

### `plot_drift_overlay(case, *, window=None) -> plotly.graph_objects.Figure`

- **Output**: a plotly figure showing observations + rolling mean + rolling-std band; a vertical
  onset marker iff `case.labeled` (FR-017, FR-018).
- **Guarantees**: returns the figure (no forced display) so it is testable headlessly (assert on
  traces/shapes); renders for both synthetic (with marker) and real (no marker) cases.

### `save_drift_overlay(case, out_dir, *, window=None) -> (png_path, html_path)`

- **Output**: writes the overlay as paired artifacts for manual inspection — a static `.png`
  (`fig.write_image`, via `kaleido`) and an interactive `.html` (`fig.write_html`) — under
  `out_dir` (default `reports/`, gitignored). Returns both paths.
- **Guarantees**: both files produced for any case; filenames derive from `case.case_id`.

## Generic core (`ailf.core.datasets`)

### `Case.to_dict()` / `Case.from_dict(d)` / `Case` round-trip

Plain serializable boundary (Principle I). `series` represented as timestamp/value records (or a
CSV path reference in on-disk form). Round-trip MUST preserve series values and labels exactly.
