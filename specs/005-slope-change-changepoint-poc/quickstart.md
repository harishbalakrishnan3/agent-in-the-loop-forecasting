# Quickstart: Slope-Change Changepoint POC

**Feature**: 005-slope-change-changepoint-poc

A validation/run guide proving the POC works end-to-end. Implementation details live in the
contracts and in `tasks.md` (generated next by `/speckit-tasks`).

## Prerequisites

```bash
uv sync          # all deps already in pyproject.toml (darts, prophet, plotly, kaleido, pytest)
```

No `.env` or external services required — generation and Prophet are fully local.

## 1. Generate the dataset catalog

```bash
uv run python -c "from pocs.changepoint.slope_change.datasets import generate_all_datasets; \
d = generate_all_datasets(); print(list(d.keys())); \
print(d['S1_single_gentle'][1])"
```

**Expected**: prints all 10 dataset names (`S1_single_gentle` … `S10_frequent_changes`) and a
metadata dict for S1 whose `type == "slope_change"` with populated `changepoint_indices`,
`slope_deltas`, and `slopes_per_segment`.

## 2. Run the naive-Prophet evaluation

```bash
uv run python -m pocs.changepoint.slope_change.prophet_eval
```

**Expected**: a per-dataset table (10 rows) with detection precision/recall and held-out
MAE/RMSE/MAPE plus a `pass`/`borderline`/`fail` label. At least one simple dataset (S1/S2/S9) is
`pass`; at least one complex dataset (S10, and typically S3/S5/S8) is `fail` — demonstrating the
baseline breakdown (SC-004).

## 3. Run the tests

```bash
uv run pytest pocs/changepoint/slope_change/ -v
```

**Expected**: all tests pass (SC-007) — generator ground-truth (slope changes at planted indices,
continuous trend), reproducibility, control flatness, metadata schema, and the Prophet-eval smoke
on a simple and a complex dataset.

## 4. Inspect visually (interactive)

```bash
uv run python -m pocs.changepoint.slope_change.visualize
```

**Expected**: a Plotly figure opens with a dropdown over S1–S10 showing the raw series,
ground-truth slope-change markers, Prophet's detected changepoints, and the forecast-vs-actual
overlay on the held-out horizon (SC-006).

## 5. Export static plots

```bash
uv run python -m pocs.changepoint.slope_change.export_plots
```

**Expected**: one PNG per dataset written to `pocs/changepoint/slope_change/plots/` (10 files).

## 6. Confirm deliverables

- [ ] 10 datasets generate with ground-truth metadata (step 1)
- [ ] Per-dataset Prophet results table produced (step 2)
- [ ] All tests pass (step 3)
- [ ] Interactive + static visualizations render (steps 4–5)
- [ ] `slope_change_poc.md` summary report exists with the results table and the explicit
      "complex datasets where naive Prophet fails" section (FR-021/FR-022)
- [ ] No imports from `level_shift/` or `src/ailf/*` — verify:
      `grep -rE "level_shift|ailf" pocs/changepoint/slope_change/*.py` returns nothing (SC-008)
