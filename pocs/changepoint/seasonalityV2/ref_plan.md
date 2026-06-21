# Plan: Changepoint POC — Seasonality Amplitude Shift

**Feature**: `pocs/changepoint/seasonality/` (original) → reference copy in `pocs/changepoint/seasonalityV2/`
**Spec**: `ref_SPEC.md` (same directory)
**Created**: 2026-06-15 (original), copied 2026-06-20
**Exemption**: POC area — no quality gates, no CI, no PR requirements.

---

## Clarifications & Decisions

Four ambiguities in the spec were resolved here before implementation.
These are not user questions — each has a documented default and a
fallback path.

### C1 — What signal feeds PELT: raw values or rolling-std feature?

**Risk**: `ruptures.Pelt(model="rbf")` detects distributional shifts in
the raw signal. A 2× amplitude jump is a large distributional change
and *should* be detectable on raw values — but the seasonal
periodicity itself is a confounding source of variance that rbf sees
before the amplitude changes.

**Decision**: try raw values first. If goal 2 fails (planted change not
found) at any `pen` in `[0.5, 10]`, switch to a rolling-std feature:
compute a rolling standard deviation with `window = seasonality_period`
and feed that to PELT instead. This isolates the amplitude signal
cleanly. Document which approach worked as a comment in
`ref_tools_seasonal.py`.

### C2 — `min_size` default should be ≈ one seasonal period, not 2

**Problem**: `min_size=2` allows PELT to carve within-cycle segments,
manufacturing false positives from normal within-season variance —
directly fighting goal 3.

**Decision**: set `min_size` default to `seasonality_period` (30 for
daily data). This enforces that no detected segment is shorter than one
full cycle. Expose `min_size` as a parameter so callers can override.

### C3 — Detection tolerance should be ≈ one period, not ±5 points

**Problem**: PELT localizes breaks to the start of the segment where the
distributional shift becomes statistically significant. For a
period-30 seasonal series, this can be up to a half-cycle (≈15 points)
away from the true `break_index`. A ±5 tolerance is likely too tight.

**Decision**: use `abs(detected[0] - true_break) <= seasonality_period`
(i.e. ±30) as the acceptance window. Record the actual observed offset
as a comment in `ref_test_seasonal.py` once the POC runs.

### C4 — `pen=3.0` is a hypothesis, not a known answer

**Problem**: the spec pins `pen=3.0` in both the tool and the test
assertions, but the POC's job is to *find* a working penalty. If 3.0
happens to fail, the test structure would look like a detection failure
rather than a tuning gap.

**Decision**: the test sweeps `pen ∈ [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]`
and reports, for each:
- planted-change found within tolerance? (True/False)
- control clean? (True/False)

The test passes if **at least one pen value satisfies both**.
The "proven" pen range is then noted as a comment in
`ref_tools_seasonal.py` and the default parameter set to the midpoint of
that range. This is the correct POC discipline — discover first, then
pin.

---

## Environment Prerequisite (Hard Blocker)

**Nothing executes until this is resolved.** The `.venv` is currently
empty — `uv sync` fails with SSL `UnknownIssuer` against
`pythonhosted.org`, meaning even `import darts` fails. Code can be
authored without the env, but visual proof and test proof both require
a working environment.

### Steps

1. Find the Walmart Artifactory pip/uv index URL (search internal docs
   or use `content_search "uv pip index url artifactory"`).
2. Configure uv to use it:
   ```bash
   uv sync --index-url <ARTIFACTORY_URL>
   # or set UV_INDEX_URL=<ARTIFACTORY_URL> in .env
   ```
3. Add `ruptures`:
   ```bash
   uv add ruptures --index-url <ARTIFACTORY_URL>
   ```
4. Verify:
   ```bash
   uv run python -c "import darts, ruptures, plotly; print('env ok')"
   ```
5. Commit updated `pyproject.toml` and `uv.lock`.

Writing all four files can happen in parallel with env setup. Proof
(running `ref_viz_seasonal.py` and `ref_test_seasonal.py`) is gated on step 4.

---

## Build Order

```
Step 0  Fix environment (hard prerequisite for proof)
Step 1  ref_datasets_seasonal.py   — generator (no ruptures dependency)
Step 2  ref_viz_seasonal.py        — visual proof (needs darts + plotly only)
Step 3  ref_tools_seasonal.py      — PELT wrapper (needs ruptures)
Step 4  ref_test_seasonal.py       — proof assertions (needs all of the above)
```

Steps 1 and 2 can be authored without a working env. Step 3 and 4
require ruptures to be installable.

---

## What "proven" means (updated from spec)

| Goal | Proof |
|---|---|
| 1. Visual | `ref_viz_seasonal.py` shows unambiguous swing widening/narrowing at `vline` |
| 2. Detection | `test_working_pen_exists` passes; working pen range documented |
| 3. No false positives | Same test — control branch clean for the working range |

The POC is **done** when all three goals are proven and the working
penalty range is written as a comment in `ref_tools_seasonal.py`.

---

## Out of scope (carried forward from spec)

- Phase shifts, multiple changepoints, variance jump flavor.
- Integration with `ailf.core.datasets.Case`.
- Promotion to `src/ailf/pipelines/changepoint/`.
- Formal quality gates, CI, PR requirements.
