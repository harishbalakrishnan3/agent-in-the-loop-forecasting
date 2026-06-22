# Topic 1 — Golden-record schema + ground-truth contract + boundary-matching policy

> **Status:** designed + adversarially verified against the real code & fixtures
> (`llm_eval` @ `281ef7f`). Companion to `TOPICS.md` (see Vocabulary + §4–§6 there).
> This is the **contract every other topic builds on**: the exact shape of the per-trace
> golden record, how ground truth is decoded, and how detection is scored.

## TL;DR of the hard part

`audit_only.true_injected_boundaries` is a **flat `list[int]` whose meaning changes with
`expected_intervention_family`** — so the matcher MUST branch on family, never on list length:

| Family | Real fixture boundaries | Decoded meaning |
|---|---|---|
| `full_history_step_regressor` | `[610, 700]` | **2 independent POINTS** (level-shift changepoints) |
| `full_history_ramp_regressor` | `[540, 720]` | **1 INTERVAL** `[start, end)` (drift transition) |
| `full_history_clean_event` | `[250,268, 420,444, 575,615]` | **3 INTERVAL pairs** (event blocks) |
| `full_history_clean_event` | `[690, 716]` | **1 INTERVAL pair** (sustained anomaly) |
| `full_history_prophet_tuned_holidays` | `[875, 1250]` | **2 independent POINTS** (trend kinks) |

`[610,700]` (step) and `[540,720]` (ramp) are **both even-length** but mean different things —
length parity is NOT a usable discriminator. The family is.

## ⚠️ The blocker the adversarial review caught (verified in source)

**Boundary precision/recall on POINT families measures the DETECTOR, not the AGENT — and must
NOT count as agent failure.**

- Level shifts are injected as a pure level jump: `df.loc[df.index >= cp, "y"] += lift`
  (`pocs/changepoint/export_scenario_csvs.py:60-61`) — **no slope change**.
- The detector keeps the top-N Prophet changepoints ranked by `abs(trend_delta)` =
  **slope change** (`src/ailf/pipelines/changepoint/detector.py:62`), on Prophet's coarse default
  grid (~25 points over the first 80% of history).
- **Result:** for `level_shift_loses_seasonality`, injected steps `[610,700]` vs detected
  `[197,366]` → tp=0, fp=2, fn=2, **precision=recall=0 even though the agent chose the right
  tool and beat naive.** For `prophet_prior_tuning` kinks `[875,1250]`, detected
  `[772,824,875,927,1236,1287]`: 875 hits exactly but 1250's nearest is 1236 (Δ14) → misses at
  a small tolerance, and the 4 extra detections become false positives.

**Consequences baked into this spec:**
1. Point-family `boundary_eval` is a **detector-quality diagnostic**, reported but
   **excluded** from `is_behavioral_failure` (it is not the agent's fault).
2. Point tolerance `N` is tied to the **detector grid spacing** (~`0.8·train_end/25`), not to
   "a few days." Default `N = 25` for daily/long series; also report a strict `N`.
3. For `prophet_tuned_holidays`, **precision is `null`** (the recurring-holiday edges inflate
   fp by construction since `n_changepoints_to_detect` > GT point count); score **recall only**,
   and capture holiday correctness via `chose_expected_family`.
4. **Interval families (`clean_event`, `ramp_regressor`) are the trustworthy boundary signal** —
   `candidate_event_blocks` / `candidate_drift_intervals` are residual/slope-scan based and land
   on the injected indices (verified: 5/6 event blocks were byte-identical to ground truth in
   the real trace).

---

## 1. The golden record (one JSON object per run dir)

One record per `reports/changepoint/<run_id>/` where `run_id = "<scenario_id>-<seed>"`.
Stored at `pocs/llm_eval/golden_records/<run_id>.json` (or one JSONL line per run).

**Index convention (verified, load-bearing):** every integer index is a **0-based row into the
FULL committed series**, which equals the detector/diagnostics training-row index because
`train_df = series.iloc[:train_end]` on a `reset_index(drop=True)` frame
(`scenarios.py:60-61`) and the detector indexes via `enumerate(train_df["ds"])`
(`detector.py:54`). So **no remap** is needed for any index `< train_end`. The diagnostics frame
is `[0, train_end)` — NOT `[0, fit_end)`; the validation holdout `[fit_end, train_end)` is
internal to the gate and does not bound diagnostics. **All interval ends are normalized to
half-open `[start, end)` on both sides.**

```jsonc
{
  "record_schema_version": "1.0",
  "run_id": "many_temporary_events_long_history-1729",   // "<scenario_id>-<seed>"
  "scenario_id": "many_temporary_events_long_history",
  "seed": 1729,                       // varies for stability repeats → distinct run_ids/records

  // [A] GROUND TRUTH — audit_only, NEVER fed to the agent.
  //     For series_df-generated cases this is joined from POC metadata, not the Scenario.
  "ground_truth": {
    "ground_truth_kind": "boundary_and_objective", // | "objective_only" (real, D5 — no boundaries)
    "intended_failure_lever": "competence",        // "competence"|"prompt"|"pipeline"|"tool" (D8)
    "dev_or_test": "test",                          // "dev"|"test" (D9)
    "source_bucket": "synthetic_combined",          // "synthetic_combined"|"unsolvable"|"real" (D3)
    "expected_intervention_family": "full_history_clean_event",
      // gold label scored vs chosen_tool. One of the 5 structural tools, OR "fallback"
      // (D4 unsolvable: correct behavior = agent picks full_history_default and does NOT beat
      // naive), OR null for objective_only.
    "true_injected_boundaries_raw": [92,105,286,317,548,566,852,901,1320,1344,1441,1482],
      // verbatim audit_only.true_injected_boundaries (family-dependent semantics). null if objective_only.
    "ground_truth_events": [           // NORMALIZED, family-decoded. What the matcher consumes. null if objective_only.
      // each is exactly one of:
      //   {"kind":"point",    "index": int}
      //   {"kind":"interval", "start": int, "end": int, "interval_type": "event"|"drift"}   // half-open
      {"kind":"interval","start":92,  "end":105, "interval_type":"event"},
      {"kind":"interval","start":286, "end":317, "interval_type":"event"},
      {"kind":"interval","start":548, "end":566, "interval_type":"event"},
      {"kind":"interval","start":852, "end":901, "interval_type":"event"},
      {"kind":"interval","start":1320,"end":1344,"interval_type":"event"},
      {"kind":"interval","start":1441,"end":1482,"interval_type":"event"}
    ],
    "audit_only_note": "Six irregular, non-calendar event blocks ...",  // verbatim
    "n_changepoints_to_detect": 6,    // agent-VISIBLE; NOTE: ≠ ground-truth count for several families
    "seasonal_period": 365            // agent-VISIBLE
  },

  // [B] AGENT PREDICTION — from agent_trace.json.
  "prediction": {
    "chosen_tool": "full_history_clean_event",   // = final_candidate.tool (the tool scored on test)
    "chosen_tool_params": {"blocks":"all_closed"},
    "final_case": "accepted_beat_naive",          // "accepted_beat_naive"|"best_proposal_no_beat" (VALIDATION, not test winner)
    "is_fallback": false,                         // chosen_tool == "full_history_default"
    "n_iterations": 1,
    "rejected_signatures": [],
    "detected_changepoints": [                    // diagnostics.detected_changepoints (Prophet trend cps, top-N by |trend_delta|)
      {"index":309,"ds":"2019-11-06","trend_delta":-0.12541415}
    ],
    "primary_changepoint_index": 875,             // diagnostics.primary_changepoint.index (max |trend_delta|) | null
    "latest_changepoint_index": 1081,             // diagnostics.latest_changepoint.index (max index) | null
    "candidate_event_blocks": [                   // end already EXCLUSIVE — copied verbatim
      {"start":92,"end":105,"duration":13,"mean_excess":29.72,"closed_before_origin":true}
    ],
    "candidate_drift_intervals": [                // DriftInterval.end is INCLUSIVE → store normalized half-open under "end"
      {"start":669,"end":722,"slope_per_step":0.57,"total_delta":29.69}   // "end" = raw_end + 1
    ],
    "prompt_ids": {"decision":"react_decision_v2","visual":"visual_inspection_v1"},
    "model_ids": {"visual":"us.anthropic.claude-opus-4-8","decision":"us.anthropic.claude-sonnet-4-6"},
    "split": {"train_end":1610,"fit_end":1490,"val_rows":120,"n_rows":1730,"test_rows":120}
      // train_end is the authoritative detector frame bound (see §4 out-of-window).
  },

  // [C] OBJECTIVE OUTCOME — from metrics.json (deterministic oracle).
  "outcome": {
    "winner": "agent",                            // verbatim; min TEST mae over (full_history_prophet, naive_workflow, agent)
    "beat_naive": true,                           // = (winner == "agent") — the TEST signal
    "horizon": 120,
    "agent_test_metrics": {"mae":..,"rmse":..,"wape":..,"smape":..},    // metrics.json agent.* MINUS its "tool" key (tool lives in prediction.chosen_tool)
    "naive_test_metrics": {"mae":..,"rmse":..,"wape":..,"smape":..,"selected_window":".."},
    "full_history_prophet_test_metrics": {"mae":..,"rmse":..,"wape":..,"smape":..},
    "agent_minus_naive_mae": -1.23                // agent.mae - naive_workflow.mae (negative = agent better)
  },

  // [D] DERIVED EVAL — computed by the harness.
  "eval": {
    "chose_expected_family": true,                // see §3 step 5a; null for objective_only
    "boundary_eval": {                            // null if ground_truth_events is null (recent_window/fallback/objective_only)
      "channel": "event",                         // "point"|"event"|"drift"
      "measures": "agent",                        // "detector" for point families, "agent" for interval families (see blocker fix)
      "tolerance_steps": 25, "iou_threshold": 0.5,// the params used (defaults; configurable)
      "tp": 5, "fp": 0, "fn": 1,
      "precision": 1.0, "recall": 0.833,          // precision = null for prophet_tuned_holidays
      "matches": [ {"gt":{"start":92,"end":105}, "pred":{"start":92,"end":105}, "iou":1.0} ],
      "false_positives": [], "missed": [{"start":852,"end":901}],
      "excluded_out_of_window": []                // GT units ≥ train_end / in [0.8·train_end, train_end) for points
    },
    "is_capability_gap": false,                   // expected_family=="fallback" AND is_fallback AND NOT beat_naive
    "is_behavioral_failure": false,               // see §3 step 5c (guarded on solvability; EXCLUDES point-boundary detector misses)
    "failure_mode_labels": [],                    // Topic 4 fills (frozen slot now)
    "labeller_id": null
  },

  // provenance
  "joined_at": null,                              // stamped by the orchestrator after the run (no Date.now in workflows)
  "trace_path": "reports/changepoint/many_temporary_events_long_history-1729/agent_trace.json",
  "metrics_path": "reports/changepoint/many_temporary_events_long_history-1729/metrics.json"
}
```

---

## 2. POC-local golden DATASET metadata (the ground-truth store)

Mirrors `changepoint/data/scenario_metadata.json` (so `load_metadata`/`load_series` stay
compatible) + the eval additions. **This file is the single canonical ground-truth source for
all ~100 cases** — `series_df`-generated Scenarios carry no `audit_only`, so the harness joins
ground truth from here by `scenario_id`.

```jsonc
{
  "schema_version": "...", "description": "POC llm_eval golden dataset",
  "scenarios": [{
    "scenario_id": "...",            // stable, UNIQUE — the join key
    "title": "...", "csv_path": "pocs/llm_eval/data/csv/<id>.csv",
    "n_changepoints_to_detect": 6, "seasonal_period": 365,
    // split: use GOLDEN-style ABSOLUTE rows (NOT ratios) so the realized detector train_end
    // equals the metadata train_end — boundary scoring depends on this (see §4 / open #2).
    "train_end": 1610, "validation_horizon": 120, "test_horizon": 120,
    // eval additions:
    "intended_failure_lever": "competence",        // D8
    "dev_or_test": "test",                          // D9
    "source_bucket": "synthetic_combined",          // D3
    "ground_truth_kind": "boundary_and_objective",  // | "objective_only"
    "audit_only": {
      "note": "...",
      "true_injected_boundaries": [...],            // null/absent for objective_only
      "expected_intervention_family": "..."         // null for objective_only
    }
  }]
}
```

---

## 3. Join procedure (run dir + metadata → one golden record)

0. `scenario_id`, `seed` from `agent_trace.json`; `run_id = f"{scenario_id}-{seed}"`.
1. **Ground truth [A]:** look up `scenario_id` in the POC metadata; read levers/split/`audit_only`.
   *series_df runs carry no audit_only — this file is the ONLY source.* If
   `ground_truth_kind == "objective_only"`: `ground_truth_events = null`,
   `expected_intervention_family = null`, skip all boundary scoring.
2. **Decode [A] → `ground_truth_events`** by `expected_intervention_family` (§ routing table):
   `step`/`prophet_tuned_holidays` → one `{point, index}` per int; `ramp` → one `{interval, drift}`
   from the pair; `clean_event` → read **two-at-a-time** → one `{interval, event}` per pair;
   `recent_window`/`fallback` → `[]` and `boundary_eval = null`. **Never infer from list parity.**
3. **Prediction [B]** from `agent_trace.json`: `final_candidate.{tool,params}`, `final_case`,
   `is_fallback`, `len(iterations)`, `rejected_signatures`, `diagnostics.detected_changepoints`,
   `primary/latest_changepoint.index`, `candidate_event_blocks` (copy — end exclusive),
   `candidate_drift_intervals` (**normalize: store `end = raw_end + 1`**), `prompt_ids`,
   `model_ids`. **Split: read `split_provenance.derived.{train_end,fit_end}` +
   `resolved.{val_rows,n_rows,test_rows}` and FAIL LOUDLY if `derived.train_end` is missing**
   (it is the load-bearing frame bound; older pre-split-provenance traces have it null) — then
   assert it equals the metadata `train_end`.
4. **Outcome [C]** from `metrics.json`: `winner`; `beat_naive = (winner=="agent")`; `horizon`;
   the three method metric dicts (drop the agent method's `tool` key — it's in `prediction`);
   `agent_minus_naive_mae`.
5. **Derived [D]:**
   - **5a `chose_expected_family`:** if family `=="fallback"` → `(chosen_tool=="full_history_default")`;
     elif family is null → `null`; else `(chosen_tool == expected_intervention_family)`.
     (`recent_window` is a normal structural family: `chosen_tool == "recent_window"`.)
   - **5b `boundary_eval`:** null if `ground_truth_events` null. Else pick channel by family,
     apply out-of-window exclusion/clipping vs **`prediction.split.train_end`** (authoritative),
     run point (±N) or interval (IoU) greedy 1:1 matching (§4), set `measures` =
     `"detector"` for point families / `"agent"` for interval families, and `precision=null` for
     `prophet_tuned_holidays`.
   - **5c flags:**
     `is_capability_gap = (family=="fallback") AND is_fallback AND NOT beat_naive`.
     `is_behavioral_failure`:
       - `null` if `ground_truth_kind=="objective_only"` (no solvability oracle — do NOT infer
         failure from `NOT beat_naive` on real data), OR if the case is not known-solvable.
       - else `(NOT is_capability_gap) AND ((chose_expected_family==False) OR (NOT beat_naive))`.
       - **Point-family boundary misses NEVER feed this flag** (they measure the detector).
   - **5d** `failure_mode_labels=[]`, `labeller_id=null` (Topic 4 fills).
6. Emit one record (+ `trace_path`, `metrics_path`); `joined_at` stamped post-run by the orchestrator.

---

## 4. Boundary-matching policy (exact)

**End-normalization first (both sides):** GT event/drift pairs are half-open `[start,end)`
(generator uses `index>=start & index<end`). `EventBlock.end` is already exclusive (copy);
`DriftInterval.end` is **inclusive** → convert `end_excl = raw_end + 1`. After this, every
interval is `[start,end)` under the **same key `end`** (no `end_excl` vs `end` split — that was a
flagged off-by-one/KeyError risk).

**Point matching** (step / prophet kinks) — detected = `detected_changepoints[*].index`:
- `d` matches `g` iff `|d - g| <= N`. **1:1 greedy** assignment: enumerate all `(g,d)` with
  `|d-g|<=N`, sort ascending by `|d-g|` (tie-break smaller `g`, then smaller `d`), consume each
  `g` and `d` once. `tp`=matched GT, `fn`=unmatched GT, `fp`=unmatched detected.
- **This channel sets `measures="detector"` and is EXCLUDED from `is_behavioral_failure`** (blocker).
- **`prophet_tuned_holidays`: recall only, `precision=null`** (extra detections from holiday
  edges are not real fp).

**Interval matching** (events / drift) — `measures="agent"`:
- `inter = max(0, min(ge,pe) - max(gs,ps))`; `union = (ge-gs)+(pe-ps)-inter`; `IoU = inter/union`.
  Match iff `IoU >= iou_threshold`. **1:1 greedy** by descending IoU (tie-break smaller `gs`,
  then `ps`). `tp/fn/fp` as above.

**Precision / recall:**
- `precision = tp/(tp+fp)`; **if `tp+fp==0` → `precision = null`** (excluded from aggregation —
  "found nothing" must not score as 1.0).
- `recall = tp/(tp+fn)`; the `tp+fn==0` branch is unreachable for scored families (guard kept).
- Computed **per channel per case**; aggregate **across cases** at the eval level (micro-average:
  sum tp/fp/fn over the cohort; also report per-lever).
- **`fpr_per_100` dropped** (`null` everywhere): a top-N selector has no well-defined negative
  population; `train_end` as denominator makes it meaninglessly tiny. **Headline = fp count +
  precision** (with the point-family detector caveat).

**Out-of-window GT** (forward-compat for Topic-2; untriggered on the 6 fixtures):
- Cutoff is taken from **`prediction.split.train_end`** (what the detector actually indexed).
- Point GT `>= train_end` → excluded from tp/fn. **Also**: point GT in `[0.8·train_end, train_end)`
  is undetectable (Prophet default `changepoint_range=0.8`) → record as `excluded_out_of_window`
  / `undetectable_by_grid`, do not count as fn. (Interval channels span full `[0,train_end)` —
  unaffected.)
- Interval straddling `train_end` → clip GT to `[start, min(end, train_end))`; **exclude if
  <50% of its width is in-window** (so a mostly-test-tail event isn't scored as a miss the
  detector could never hit).

**Recommended values + rationale (revised per review):**
- **POINT tolerance `N = 25`** (daily). Tied to the **detector grid**: Prophet's ~25 changepoints
  over the first `0.8·train_end` rows give ~50-row spacing, so a kink quantizes 20-25 rows off
  its true index (verified: GT 1250 → nearest detected 1236, Δ14). `N≈25` ≈ half the grid
  spacing. *(The earlier "N=7 = one week" rationale was unsound — folklore, not grid-based.)*
- **INTERVAL IoU = 0.5** (standard majority-overlap; tolerates a few-row edge drift on noisy
  Topic-2 cases while rejecting wrong-half coverage).
- **Configurable + sensitivity sweep:** store `tolerance_steps`/`iou_threshold` per record;
  expose global overrides; emit metrics at default **(N=25, IoU=0.5)** AND strict
  **(N=10, IoU=0.7)** so grid-quantization sensitivity is visible. Default is the headline.
- **Frequency-aware default:** tie `N` to detector grid spacing `≈ round(0.8·train_end/25)`
  (clamped to a sane floor), NOT to `seasonal_period/52` (which only coheres for annual-on-daily).

---

## 5. Canonical sanity check (the real existing trace)

`many_temporary_events_long_history-1729` (`clean_event`, 6 GT event pairs): the trace's
`candidate_event_blocks` matched 5/6 GT pairs byte-identically; block `[852,901)` was missed →
**tp=5, fp=0, fn=1, precision=1.0, recall=0.833** at IoU=0.5. Any implementation MUST reproduce
this. (And the agent chose the right tool and beat naive → `chose_expected_family=true`,
`beat_naive=true`, `is_behavioral_failure=false`.)

---

## 6. Open decisions (carry to discussion)

1. **Point tolerance `N`** — default **25** (grid-based) vs a sweep `{10, 25, 50}`. *Rec: 25 default + report strict 10.*
2. **Split style for generated cases** — generate with **absolute/golden** splits so metadata
   `train_end` == realized detector `train_end` (boundary scoring depends on it). *Rec: yes, golden-style.*
3. **`prophet_tuned_holidays` precision** — confirm **recall-only, precision=null** is acceptable
   (the alternative — surfacing holiday windows to subtract them from fp — contradicts the
   "omit holidays from boundaries" choice). *Rec: recall-only.*
4. **Aggregation** — micro-average across cohort + per-lever breakdown. *Rec: both; per-lever is the headline for Topic 7.*
