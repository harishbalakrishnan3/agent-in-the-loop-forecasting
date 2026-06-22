# Contract: Custom CSV Input

The data contract for the custom-CSV dataset option and how the UI validates it before a run.

## Required shape (verified against the pipeline)

- The DataFrame MUST have **exactly two columns named `ds` and `y`** (in that order). This is hardcoded and validated in the data path (`changepoint/datasets.py:41`, `scenarios.py`), and the custom-CSV path coerces `ds`→datetime and `y`→float (`pipeline.py:119-120`). It is **not** configurable.
- `ds`: parseable as datetime; chronologically sorted; no duplicate timestamps.
- `y`: numeric (coercible to float); no missing values.
- Enough rows that each of train/val/test maps to ≥1 row after flooring.

The UI states this contract visibly (help icon / caption) next to the uploader (FR-008).

## Split fractions

- Three inputs: `train_ratio`, `val_ratio`, `test_ratio` (defaults `0.8 / 0.1 / 0.1`).
- Rule: `abs(train + val + test - 1.0) <= 1e-6` (FR-009). If violated, Start is blocked / inputs flagged with an explanatory message; **no run begins**.
- The fractions are passed to `run_scenario(series_df=…, train_ratio=…, val_ratio=…, test_ratio=…)` (see `run_invocation.md`), which routes them into the extended `_series_split_from_df` (research R5). `val` is taken from inside the training portion so the agent still sees only training data (preserves the existing leakage guard).

## Advanced detection settings (optional)

- `seasonal_period` (default `365`) and `n_changepoints_to_detect` (default `3`), shown only for custom CSV (FR-011), passed as the matching `run_scenario` args. Scenario runs derive these from metadata and don't show these inputs.

## UI validation order (pre-run, all must pass before Start enables)

1. A file is uploaded and parses to a DataFrame.
2. Columns are exactly `ds`, `y` → else block with "CSV must have columns `ds` (time) and `y` (value)."
3. `ds` parses to datetime, sorted, unique; `y` numeric, non-null → else block with the specific defect.
4. Fractions sum to 1 (tolerance `1e-6`) → else flag the fraction inputs.
5. Row count ≥ minimum for the chosen fractions (each segment ≥1) → else block with "Not enough rows for this split."

On any failure the UI shows a clear message and does not start a run (FR-010). A backend backstop still raises if something slips through; that surfaces as an error event/message (FR-020).

## Example (valid)

```
ds,y
2021-01-01,100.4
2021-01-02,101.1
...
```
with fractions `0.8 / 0.1 / 0.1` → runs identically to a scenario run from the user's perspective, ending in a verdict + interactive graph (FR-024).

## Out of scope

- Auto-detecting frequency, resampling, imputing missing values, or renaming arbitrary columns to `ds`/`y` (the user must conform the file).
- Row-count upper bounds / performance caps for very large uploads.
