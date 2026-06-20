# Contract: split resolver — golden default + ratio/absolute override

Owner: `core/backtest/split.py` (generic resolver) + `pipelines/changepoint/datasets.py` (golden
adapter + pandas accessor). Covers FR-017..021, SC-009, SC-012.

## Partition model (resolves the nested-vs-strict conflict)

The POC validation holdout is the **tail of training** (`fit_end = train_end - validation_horizon`).
We adopt a **strict-partition** core model carrying segment **lengths**, with a **fixed nested-view
derivation** back to the POC indices so golden reproduction is bit-exact.

`ResolvedSplit(train_rows, val_rows, test_rows, provenance)`, all lengths ≥ 1,
`train_rows + val_rows + test_rows ≤ n_rows`. Derivation:

```
fit_end                = train_rows
train_end              = train_rows + val_rows        # POC's train_end
validation_holdout     = [train_rows, train_rows + val_rows)
test                   = [train_end, train_end + test_rows)
forecast_origin_index  = train_end - 1
```

## Golden default (FR-017)

Pipeline `golden_split_from_metadata(meta) -> ResolvedSplit`:
`val_rows = validation_horizon`, `train_rows = train_end − validation_horizon`,
`test_rows = test_horizon`, `source="golden"`, `rounding_rule="none"`. The adapter **rejects** metadata
that would derive a non-positive `train_rows`. ✓ For golden metadata this yields 760/120/120 (1000-row
scenarios) and 1370/120/120-style splits (1730-row scenarios), deriving the POC `train_end`/`fit_end`
exactly. A **golden-reproduction test** asserts derived indices equal the POC `SeriesSplit` for all five
scenarios before any other split work proceeds.

When no override is supplied, `resolve_split(None, n_rows, golden)` returns `golden` verbatim.

## Override (FR-018) — ratios OR absolute, never both

`SplitSpec.units ∈ {ratios, absolute}`. Supplying a ratio key **and** an absolute key for the same run
→ `SplitError("ambiguous split specification")`.

- **absolute**: `train_rows/val_rows/test_rows` used directly (`rounding_rule="none"`).
- **ratios**: `train_ratio + val_ratio + test_ratio` must equal **exactly 1.0** (else `SplitError`).

## Ratio→row rounding (FR-019, SC-009) — deterministic, documented

`rounding_rule = "floor_test_val_train_absorbs"`:

```
test_rows  = floor(test_ratio  * n_rows)
val_rows   = floor(val_ratio   * n_rows)
train_rows = n_rows - test_rows - val_rows     # train absorbs the remainder
```

This guarantees the three lengths sum to exactly `n_rows`, is a pure function of `(ratios, n_rows)`, and
makes a ratio override and its **equivalent** absolute override resolve identically (asserted on both
fixture lengths 1000 and 1730 — SC-009).

## Validation (FR-020) — all `SplitError`, field-naming

After resolution: every segment ≥ 1 (catches a ratio < 1/n flooring to 0), sum ≤ `n_rows`,
non-overlapping (structural by construction), and an override `test_rows` exceeding available rows →
`SplitError` (not a bare `IndexError`).

## Provenance (FR-021, SC-012) — recorded per run

`SplitProvenance(source, units, requested, resolved{train_rows,val_rows,test_rows,n_rows},
rounding_rule, derived{train_end,fit_end,forecast_origin_index})`. Recorded in
`effective_config.json` and emitted in the `split_built` event.

## SC-007 round-trip (provenance stability)

- A recorded `source="golden"` run re-resolves to golden verbatim on re-ingest and **stays**
  `source="golden"` (it does not serialize back into a split override that would flip provenance).
- A recorded `source="override"` run re-resolves from the **recorded absolute rows** (no re-rounding),
  staying `source="override"`.
- A test asserts provenance is stable across the round-trip for both cases.

## Boundary

`core/backtest/split.py` knows only `(n_rows, SplitSpec | None, golden: ResolvedSplit)` — **no** config
file, CSV, or metadata knowledge. The pipeline owns metadata loading, the golden adapter, and the pandas
`SeriesSplit` accessor (`train_df`/`fit_df`/`val_df`/`test_df`/`forecast_origin`) **built from**
`ResolvedSplit`, so `baselines.py`/`interventions.py` arithmetic is untouched.

## Note on the load-bearing forecast origin

The prior POC's SC-008 depends on the golden forecast-origin placement; the golden path preserves it
exactly. A ratio/absolute override legitimately **moves** the origin — that is the intended
experimentation knob, and such a run no longer reproduces the golden result (by design).
