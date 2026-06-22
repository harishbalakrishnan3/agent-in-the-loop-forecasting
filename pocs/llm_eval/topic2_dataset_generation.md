# Topic 2 — Diverse trace + dataset generation (~100 lever-tagged cases)

> **Status:** designed + **adversarially verified by EXECUTING recipes against the real Prophet
> detector + gate** (`llm_eval` @ `281ef7f`). The verification overturned the naïve design — read
> §0 first; it changes how every case is labeled. Companion to `TOPICS.md` (D3, D4, D8, D9) and
> `topic1_golden_record.md` (the schema these cases must conform to).

## 0. The finding that reshapes everything (verified by running real code)

**You cannot label a case's `expected_intervention_family` by what you injected. The gold label
is whatever the brute-force gate proves actually WINS.**

Proof (my own run, reproduced): inject a clean permanent level **step** of +45 at index 420 →
- detector snaps changepoints to its ~28-day grid: detected `[394, 450]` (neither is 420);
- `full_history_step_regressor` → val mae **32.8 / 26.7**, **loses** to naive (20.6);
- `full_history_ramp_regressor` → val mae **5.98**, **wins** decisively.

A step injection is best repaired by the **ramp** tool, because a step regressor at the
grid-snapped wrong index injects a hurtful discontinuity while a ramp between `[394,450]`
absorbs the shift. This is the same root cause as the Topic-1 detector blocker (Prophet ranks by
*slope* change, grid spacing ~28 days). **Consequence:** the generator **derives every gold label
from `verify.py`**, never from the injected primitive. The catalog's "C-step → step family"
assumption was a *systemic* error the adversarial pass caught.

**Three more blockers the verifiers found by execution** (all fixed in this spec):
1. **Gate crashes on validation-window indices.** `_invoke_ramp` raises a raw `IndexError` (not
   `ToolBoundsError`) when a drift interval's `end` lands in `[fit_end, train_end)` — because
   diagnostics span `[0, train_end)` but the gate builds tool context on `[0, fit_end)`. Fix:
   (a) `verify.py` catches `(ToolBoundsError, IndexError, ValueError, KeyError)` as "does not
   beat"; (b) **placement rule: all injected interval/event ENDS and gate-evaluable changepoints
   must be `< fit_end`** (= `train_end − validation_horizon` = 760 SHORT / 1490 LONG).
2. **Pipeline probes T1/T2/T3 as specified don't trip their lever.** T1's ramp got bracketed by
   detected CPs and surfaced a drift interval anyway; T2's 98-day flat excursion was *absorbed*
   by the 91-day rolling-median baseline (residual ≈ 0); T3's recurring blocks were *also*
   beaten by `clean_event`, so the lever wasn't unique. Fixes in §4.
3. **Unsolvable proven on validation can still win on TEST.** Growing-amplitude cases where no
   tool beats naive on validation had tools beating on test. Fix: weaken the claim to "no tool
   beats naive **on the validation gate** (what the agent's accept logic uses)" and **also gate
   on test** for the unsolvable bucket (`evaluate_on_test`), re-rolling if a tool wins on either.

The lesson: **every case is admitted only by `verify.py` running the real detector+gate** — the
generator proposes, the gate disposes (mirrors constitution Principle IV).

---

## 1. Reuse — don't reinvent (existing assets found in-repo)

| Asset | What it gives us | Use |
|---|---|---|
| `pocs/changepoint/export_scenario_csvs.py` | the seeded `_base_signal` (trend+annual+weekly+noise) + fixed-index injection idiom + `write_all`/`verify`/sha256/metadata | **base of the generator** |
| `pocs/changepoint/seasonalityV2/datasets.py` | a working **multiplicative / growing-amplitude seasonality** generator (amplitude scales with trend level, L153-156) — literally the NOTES.md sinusoid | **the tool-gap (unsolvable) generator** |
| `pocs/data/*.csv` (20 series, `ds,y`, 1825 rows) | lecture-section synthetic series: `sec10_sine`, `sec11_A_exponential_concept`, `sec11_B/C_covariate`, `sec12_covariate_seasonal`, `sec9_*` | **harvest as unsolvable candidates** (each must still pass `verify.py`) |
| `darts.datasets` (27, cached offline in `~/.darts/`), `statsmodels.datasets` (bundled), `prophet/tests/data.csv` | real series | **the 10 real cases** (§5) |
| `src/ailf/core/datasets/case.py` (`Case`, darts-`TimeSeries`-based) | the shared corpus idiom | mirror its provenance fields; but the POC uses the **changepoint `scenario_metadata.json`** shape (golden splits) for run compatibility |

---

## 2. Generator architecture (`pocs/llm_eval/generator/`)

```
generator/
  config.py      # REPO_ROOT, POC_DATA_DIR, CSV_DIR, METADATA_PATH, split constants, seed allocator
  base.py        # _base_signal (verbatim) + pure injectors, each returns (df, [gt_records])
  primitives.py  # one flavor recipe per case-type; chains injectors, unions GT
  real.py        # the 10 real-series ingestors → (ds,y) daily + golden split + objective_only
  verify.py      # the brute-force solvability gate (THE admission authority) — §3
  catalog.py     # the declarative ~100 CaseSpec list (§ counts)
  export.py      # write_all()/verify()/--fresh CLI; writes CSVs + scenario_metadata.json
```

**Base signal (verbatim from `export_scenario_csvs.py:45-55`):** `rng = default_rng(seed)`,
daily from `2019-01-01`; `y = 100 + 0.018·t + [22·sin+7·cos](365) + 2.5·sin(7) + N(0,1.7)`.

**Injectors (pure, append ground-truth records):**
- `inject_step(cps:[(idx,lift)])` → `y[idx:]+=lift`; GT `{point, index}` each.
- `inject_ramp(start,end,lift)` → clipped ramp; GT `{interval, drift, start, end}`.
- `inject_event(blocks:[(start,end,lift)])` → half-open `[start,end)`; GT `{interval, event}` each.
- `inject_recurring(month,d0,d1,lift,years)` → per-year block; GT optional (holiday family).
- `inject_kink(cps:[(idx,slope_delta)])` → `y[idx:]+=slope_delta·(t−idx)`; GT `{point, index}`.
- **Out-of-vocabulary (unsolvable; NO point/interval GT, family resolved to `fallback`):**
  `inject_growing_seasonal_amplitude(growth_rate)`, `inject_multiplicative_seasonality(strength)`,
  `inject_nonlinear_trend(curvature)`, `compose_conflicting(...)` (step+ramp+event at once).
  *Reuse `seasonalityV2/datasets.py` for the multiplicative/growing ones.*

**Split layout (golden absolute — Topic-1 #2 satisfied automatically):** SHORT len 1000 /
`train_end` 880; LONG len 1730 / `train_end` 1610; `validation_horizon`=`test_horizon`=120;
`seasonal_period`=365. `golden_split_from_metadata` makes `ResolvedSplit.train_end ==` metadata
`train_end` (verified). Invariant `row_count == train_end + test_horizon`.

**Two placement cutoffs (do not conflate — blocker #1):**
- **`< fit_end`** (760 / 1490): every injected interval/event END and every gate-evaluable
  changepoint, so the gate never crashes on a validation-window index.
- **`< 0.8·train_end`** (704 / 1288): points that must be **boundary-scorable** (Prophet
  `changepoint_range=0.8`; beyond this they're `undetectable_by_grid`, per Topic-1 §4).

**Seeding (reproducible + disjoint partitions):** per-case fixed seed from a deterministic
allocator — dev `1000–1199`, test `2000–2199`, fresh-check `3000+`. `--fresh` re-emits the same
flavor recipes with `3000+` seeds and `-fresh` scenario_id suffix (D9 generalization). `write_all`
mirrors `export_scenario_csvs.py` exactly (csv text → sha256 → metadata, same key order).

---

## 3. `verify.py` — the brute-force solvability gate (admission authority)

`prove_solvability(df, train_end, val_h, test_h, n_cps, seasonal_period) -> dict`, run at
generation time on **every synthetic case**. Validation-window bar, mirroring the live gate.

1. **Build split** via `ResolvedSplit.from_lengths(train_rows=train_end−val_h, val_rows=val_h,
   test_rows=test_h, source='golden', units='golden', n_rows=len(df))` → `SeriesSplit`.
2. **Detect + bar + diagnostics, reusing one `cps` object** (live ordering):
   `cps = detect_changepoints(split.train_df, n_changepoints_to_detect=n_cps)`;
   `naive = naive_workflow(split, cps)`; `naive_val_mae = naive.selected.val_mae`;
   `full_diag = compute_diagnostics(split.train_df, changepoints=cps, seasonal_period=...).to_agent_dict()`
   (None = FULL bundle, so no field is hidden → no spurious `ToolBoundsError`).
3. **Full registry** `register_changepoint_registry()` (no `.for_run`); enumerate every
   tool×param **except** `full_history_default`:
   `recent_window`(2) · `step`(2) · `ramp`(2) · `clean_event`(`all_closed` + each closed-block
   singleton + top-k by `|mean_excess|`) · `tuned_holidays`(64). For each:
   `evaluate_on_validation(Proposal(tool,params), split, registry, full_diagnostics=full_diag,
   naive_val_mae=...)`; **catch `(ToolBoundsError, IndexError, ValueError, KeyError)` → record as
   "does not beat", never abort** (blocker #1).
4. **Aggregate:** `family_beats = {name: any(beat) over non-raising combos}` initialized with all
   5 structural names → `False` (avoids `KeyError`); `min_tool_val_mae = min(mae)`;
   `n_beating_families = sum(family_beats.values())`.
5. **Accept/reject with a jitter MARGIN (strict `<` is fragile to cmdstan jitter):**
   - **UNSOLVABLE** (`fallback`): require `n_beating_families == 0` **and**
     `min_tool_val_mae >= naive_val_mae·(1+eps)`, `eps=0.01`, **and** the same no-beat on **TEST**
     (`evaluate_on_test`, blocker #3). Else re-roll the flavor knob.
   - **SOLVABLE-BY-EXACTLY-ONE-FAMILY** (competence/prompt/pipeline-after-tune): require
     `n_beating_families == 1`, the winner's `mae <= naive·(1−eps)` (clear beat), every other
     family `>= naive·(1−eps_small)` (clear non-beat). **`expected_intervention_family` := the
     winning family** (NOT the injected primitive — §0).
6. **Persist** `{naive_val_mae, min_tool_val_mae, family_beats, n_beating_families, per_combo}`
   beside metadata as a reproducible audit trail (Principle V).

`n_changepoints_to_detect` is a **pinned per-case probe parameter** (not a free knob — it
determines whether the ramp CP-fallback fires and whether drift surfaces): set to the true
point/interval count for solvable cases; **small/0** for hidden-structure pipeline probes and
unsolvable cases. Validated by `verify.py`.

---

## 4. Case catalog (~100) + probe recipes

Three orthogonal axes: `source_bucket` (D3) × `intended_failure_lever` (D8) × `dev_or_test` (D9,
~60:40). **All labels are provisional drafts → `verify.py` confirms or overrides the family and
rejects cases that don't behave as intended.**

| Lever | Count | Bucket | dev/test | What it needs `verify.py` to confirm |
|---|---|---|---|---|
| **Competence** (control) | 25 | synthetic_combined | 15/10 | exactly one family wins, clear margin; relabel to the *actual* winner |
| **Prompt** (P1–P5, 5 each) | 25 | synthetic_combined | 15/10 | solvable by exactly one family; the weakness is the prompt, not the data |
| **Pipeline** (T1/T2/T3) | 20 | synthetic_combined | 12/8 | hidden under STOCK diag (0 beats) **but** solvable under TUNED diag |
| **Tool** (unsolvable) | 20 | unsolvable | 12/8 | 0 beats on validation **and** test, margin ≥ 1% |
| **Real** (objective-only) | 10 | real | 6/4 | naive doesn't already win (SPEC headroom filter); no boundary scoring |

**Prompt probes** (data is cleanly solvable; the prompt is the only thing in the way):
- **P1 (no-fallback rule):** pure `_base_signal`, no injection → `verify` asserts
  `n_beating_families == 0` with margin (robust, not seed-luck) → family `fallback`. Probe value:
  the prompt has no do-nothing rule, so the agent force-fits a tool.
- **P2 (beat-naive overreach):** a clear single-family-beating drift with **comfortable** headroom
  (not the razor-thin 5% the draft had). Tests whether contest framing pushes needless intervention.
- **P3 (visual-over-anchor):** a drift steep enough to *look* like a step but slope-scan marks it a
  ramp; `verify` must confirm **ramp is the unique winner** (the draft's version had step *also*
  beating — widen the separation).
- **P4 (multi-issue tie-break):** dominant structure + a smaller distractor; `verify` confirms the
  unique winner is the dominant-structure family (whatever the gate says — likely **ramp**, per §0)
  and the distractor doesn't beat.
- **P5 (within-tool param):** a recipe where `verify` shows the family beats with one param value
  but not another (e.g. `primary` vs `all_detected`), so the prompt's missing param guidance bites.

**Pipeline probes** — run `verify.py` **twice** (STOCK vs a provisional TUNED diagnostic copy):
- **T1 (drift hidden):** a genuine drift that WOULD beat naive if surfaced, but a diagnostic
  threshold drops it. STOCK assert: `candidate_drift_intervals == []` **and** ramp doesn't beat;
  TUNED (duration floor 30 / min_delta 15) assert: drift surfaces **and** ramp beats. Must *also*
  pin `n_cps` so the ramp CP-fallback can't surface it (draft's `n_cps=2` bracketed the ramp).
- **T2 (event over cap):** the excursion must **survive the 91-day rolling-median baseline** — so
  make it ≥120–150 days (a 98-day flat excursion is absorbed → residual ≈ 0, no block forms). Or
  retarget the lever to the **MAD threshold floor (8.0)** with a sub-threshold `mean_excess`. STOCK:
  no block covers it / `clean_event` can't fire; TUNED (cap 120+ or floor lowered): block appears,
  `clean_event` beats.
- **T3 (recurring under 3-year bar):** the recurring structure must be exploitable **only** by the
  holiday tool — `clean_event` must NOT also beat it (draft's Feb blocks were closed-before-origin
  so `clean_event` won). Make the windows extend toward the origin / be the wrong width for event
  blocks. STOCK: `is_calendar_recurring == False` (2<3 years) → holiday precondition raises; TUNED
  (years bar → 2): holiday tool beats. **Holiday family without injected kinks ⇒
  `true_injected_boundaries = []` ⇒ `boundary_eval = null`** (Topic-1: holidays score recall-only
  on kink points, recurring windows are not boundaries).

**Unsolvable (tool lever):** `growing_seasonal_amplitude`, `multiplicative_seasonality`,
`nonlinear_trend`, `compose_conflicting` — knob tuned so `verify` asserts the ≥1% no-beat margin on
**both** validation and test. Harvest `pocs/data/sec*` series as additional candidates (each must
still pass the gate). Prefer the **LONG** layout so a drift interval is less likely to fall in the
validation window and crash a tool.

---

## 5. Real bucket (10, objective-only)

Materialize each **once** to a committed `ds,y` CSV + `csv_sha256` (no live download dependency).
Set `expected_intervention_family = null`, `ground_truth_kind = "objective_only"`,
`n_changepoints_to_detect = 0`, **no** `audit_only` boundaries → boundary scoring skipped (Topic-1).
Pass the **SPEC.md problem-reproduction filter**: keep only series where naive does *not* already
win on validation (headroom exists). Non-daily series → `resample('D').interpolate()` (document
that this fabricates intra-period points; set `seasonal_period` accordingly).

Provisional shortlist (least friction, offline-available — confirm in open decision #4):
darts `TemperatureDataset`, `USGasolineDataset`, `ILINetDataset`, `AirPassengersDataset`,
`WineDataset`, `MonthlyMilkDataset` (easy control), `IceCreamHeaterDataset`, `AusBeerDataset`;
statsmodels `co2`; `prophet/tests/data.csv`. **Do not rename the 5 `REQUIRED_SCENARIO_IDS`** —
`load_all_scenarios()` guards on them; add real cases as new entries / a separate loader.

---

## 6. Schema conformance (→ `topic1_golden_record.md`)

Each case writes a `scenario_metadata.json` entry: `scenario_id` (unique join key), `title`,
`csv_path` (under `pocs/llm_eval/data/csv/`), golden split keys (`train_end`,
`validation_horizon`, `test_horizon`), `n_changepoints_to_detect`, `seasonal_period`, `csv_sha256`,
plus the eval fields `intended_failure_lever`, `dev_or_test`, `source_bucket`, `ground_truth_kind`,
and `audit_only` with **family-correct** `true_injected_boundaries`: **points** for step/kink
families, **`[start,end)` pairs** for event/drift families, **`[]`** for `fallback`/`recent_window`/
holiday-without-kinks/objective-only. All scorable boundaries are `< train_end` (in-window).

---

## 7. Constitution alignment (`.specify/memory/constitution.md`)

- **Principle III (golden-set eval):** this dataset *is* the "versioned golden evaluation set …
  with known injected issues + expected diagnosis + acceptable intervention(s)" the principle
  mandates. The `verify.py` audit trail + seeds make it versioned & reproducible.
- **Principle V (reproducible & honest):** seeds fixed+recorded; golden splits committed; the
  beat-naive bar is exactly the honest baseline the principle requires.
- **Principle IV (bounded, backtest-gated):** the gold label = the gate's verdict; the unsolvable
  definition = "the gate rejects every bounded tool." Generation mirrors propose-then-gate.
- **POC exemption:** all of `pocs/llm_eval/` is gate-exempt. **Promotion bar** (if any evaluator /
  generator graduates): test-first (Principle II) against known ground truth + review (VII).

---

## 8. Open decisions (recommended defaults in **bold**)

1. **Counts:** competence 25 · prompt 25 · pipeline 20 (T1=7/T2=7/T3=6) · tool 20 · real 10; dev:test ~60:40. *Confirm or rebalance.*
2. **Gate every synthetic case** through `verify.py` (the only guarantee of solvable-by-one /
   truly-unsolvable). Cost ~76 Prophet-fit combos × ~90 cases, run once, cached. *Recommend: yes.*
3. **Jitter margin `eps = 0.01`** (1%). *Accept or tune.*
4. **Real shortlist** (the 10 in §5). *Confirm the set.*
5. **Pin provisional tuned thresholds now** (T1 dur 30/Δ15; T2 cap 120; T3 years 2) purely so
   `verify.py` can assert solvable-after-tune; the production tune is Topic-7's PR. *Recommend: yes.*
6. **`n_changepoints_to_detect` per case** = true point/interval count for solvable, small/0 for
   hidden-structure & unsolvable. *Confirm.*
