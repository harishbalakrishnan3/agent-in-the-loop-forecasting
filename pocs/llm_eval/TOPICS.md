# LLM Eval — High-Level Topics

> **Status:** scoping / living document. This file lists the *high-level topics* to implement.
> Each topic is filled in via live discussion (see **Open questions** under each one).
> Throwaway POC — lives entirely under `pocs/llm_eval/`, exempt from the quality gates
> (CLAUDE.md). Core (`src/ailf/core/`) stays untouched unless a piece is explicitly promoted.

Source of intent: `pocs/llm_eval/NOTES.md`.
References: teaching repo `temp/llm-evals-gouthamp-iisc/` (esp. `block5_evals/`) and
`notes/DA225o_Week01_02_Notes.tex` Lecture 11.

---

## Decisions (locked via discussion)

| # | Decision | Value |
|---|---|---|
| D1 | **Eval scope** | **Changepoint pipeline only** (it's the only track that runs the LLM agent; drift's LLM path was deleted in the 006 merge, anomaly has no LLM call). |
| D2 | **LLM provider for eval runs** | **AWS Bedrock** — LangGraph + `ChatBedrockConverse` auto-trace the full node+LLM tree to LangSmith with zero extra wiring (uses the `AWS_*` creds in `.env`). |
| D3 | **Dataset mix (~100)** | **70% synthetic-combined · 20% unsolvable · 10% real.** |
| D4 | **"Unsolvable" definition** | Structured-but-**out-of-tool-vocabulary** — NOT random noise. Two sub-flavors: **(a) out-of-vocabulary structure** (growing seasonal amplitude — the NOTES.md sinusoid, nonlinear trend, multiplicative seasonality) and **(b) conflicting simultaneous issues** (any single tool pick is wrong). **NOT** detector-defeating cases (dropped). Ground-truth label = `expected_intervention_family = fallback/none`, **verified at generation time by brute-forcing all 5 tools and confirming none beats naive on the held-out test**. Eval question: does the agent fall back gracefully (good) or pick a confidently-wrong tool and end up worse than naive (bad)? |
| D5 | **Real-data ground truth** | **Objective-outcome-only** — held-out future actuals are the ground truth; score only beat-naive + forecast metrics. **No** boundary labels for real data (boundary precision/recall stays on the 90% synthetic cases). No internet annotation needed. |
| D6 | **Failure-mode taxonomy method + sample sizes** | **Pure empirical coding** — open-code then axial-code from scratch (Lecture 11), no pre-seeded list. **Discovery ≠ measurement:** open-code only *failing* traces to **saturation** (~20–30, not all 100) → freeze codebook → **measure across all ~100** → **2 labellers double-code ~20 overlap** for **Cohen's κ**. See **Vocabulary** for the rationale and the golden-dataset-vs-traces distinction. |
| D7 | **Eval-driven-dev loop is a deliverable** | Add **Topic 7**: eval surfaces a systematic failure → intervene → **re-run the same eval** → before/after delta (visualized in LangSmith) proves the eval's value. This is the Lecture 11 *Analyze → Measure → Improve* loop. |
| D8 | **Three failure LEVERS, deliberately seeded** | The dataset tags each case with an `intended_failure_lever`, so each fix targets exactly the cases it should move: **(1) Competence baseline** (should succeed — control); **(2) Prompt** (solvable by an existing tool, but a prompt weakness misleads the agent → fix = new prompt `_vN`); **(3) Pipeline/diagnostic** (structure exists but a diagnostic threshold hides it → fix = tune a diagnostic); **(4) Tool/capability** = the D4 unsolvable cases (no tool expresses the structure → fix = add a tool). Separates **capability gap** (correct fallback, high error — *not* an agent bug) from **behavioral failure** (confidently-wrong pick). |
| D9 | **Demo rigor** | Per fix: build against a **dev** subset, report improvement on a **held-out test** subset, AND **regenerate fresh-seeded** cases of the same flavor to prove generalization (not eval-set overfitting). Track the **competence baseline** to confirm fixes don't regress easy cases. |
| D10 | **Fix location** | **POC driver, promote later.** A ~40-line driver in `pocs/llm_eval/` builds its own `RunContext` with swapped prompt / registry / diagnostics and calls `build_agent_graph(ctx)` — **zero `core/` or `pipeline.py` edits**. Each proven fix gets a separate promotion PR into the real pipeline afterward. See §5 for the mechanism. |
| D11 | **MVP first; re-sequenced** | Near-term deliverable = the **eval pipeline working end-to-end on the CURRENT code** (score + golden dataset in LangSmith + UI exploration), built on the **6 committed scenarios**. Topic 3 is reframed as this MVP and is the **next build**. Topic 2 (~100 cases), Topic 4 (taxonomy), Topic 5 (LLM-judge), Topic 7 (improvement loop) are **deferred** until the MVP produces a real number. Rationale: prove the plumbing + get a baseline before scaling data or chasing improvements. |

Still open (see §3): boundary-matching tolerance, stability-repeat count, which real datasets, the 2 labellers, judge model + calibration bar.

---

## 0. Goal (restated from NOTES.md)

Build an LLM-evaluation system for the agent-in-the-loop forecasting agent that:

1. **Generates ~100 diverse time-series traces** — including deliberately *hard / unsolvable*
   cases the agent's current tools can't cleanly handle (e.g. a sinusoid whose peaks at
   `π/2, 3π/2` grow over time *and* carry per-wave random noise), plus real downloaded
   series — **each with tracked ground truth**.
2. **Runs the existing agent over all traces**, finds where it performs *worse*, and
   **buckets the failures into named failure modes**.
3. **Defines an evaluator + methodology per failure mode.**
4. **Surfaces everything in LangSmith** (tracing + datasets + experiments) so the eval is
   visible and trackable.

The agent does **not** forecast. The eval measures *diagnosis quality, tool/intervention
choice, backtest discipline, and explanation quality* against known ground truth and against
the naive/Prophet baselines.

---

## Constitution alignment (`.specify/memory/constitution.md`, v1.0.0)

This eval work is not just permitted by the constitution — Principle III essentially **mandates
it**. Key ties (full per-topic notes live in each topic doc):

- **III — Agent Quality Through Golden-Set Evaluation:** "a versioned golden evaluation set:
  time series with known, injected issues plus the expected diagnosis and acceptable
  intervention(s) … changes to prompts/models/agent code MUST be measured against this set, and
  quality metrics MUST NOT regress without documented sign-off." → Our golden dataset (Topics
  1–2) **is** that set; Topic 7 (before/after on the same set) **is** the regression discipline.
- **V — Reproducible & Honest Evaluation:** seeds fixed + recorded; compare against honest
  baselines (Seasonal Naive at minimum) over rolling backtests; report standard metrics. → Our
  beat-naive/winner oracle + seeded generators + committed configs satisfy this.
- **IV — Bounded Interventions, Backtest-Gated (NON-NEGOTIABLE):** the agent may only pick from
  the fixed menu; nothing applies unless a backtest shows no worse. → Our "unsolvable = the gate
  rejects every bounded tool" and the Topic-7 new tool (must itself be bounded + gated) honor this.
- **POC exemption (explicit):** all of `pocs/llm_eval/` is gate-exempt for fail-fast work.
  **Promotion bar** for anything graduating to a pipeline/core: **II — Test-First** (deterministic
  logic — our scorer/verifier/join — needs failing-then-passing tests against known ground truth),
  **prompt-versioning** (judge prompts + `react_decision_v3` as `<name>_vN.md`, never edit a
  released version), and **VII** review-gate for shared-core changes.
- **Spec-kit:** `feature.json` currently points at `006-streamlined-agent-ui`. If the eval
  promotes out of the POC it should become a formal `specs/NNN-llm-eval/` feature with a
  Constitution Check in its plan. Until then: POC-only, no spec-kit ceremony required.

---

## Vocabulary (read first — three different things get called "dataset")

The word "dataset"/"trace" is overloaded across **three distinct artifacts**. They are related
by *"run the agent,"* **not by identity.** Pinning them prevents the recurring confusion.

```
  GOLDEN DATASET                 run agent              TRACES                   EVAL
  (the INPUT, w/ answers)     ───────────────►       (the OUTPUT, behavior)   ──────────►  scores
  ~100 series + ground truth   driver / run_scenario   agent_trace.json         evaluators   per
  + lever tag                                          + metrics.json           compare      failure mode
```

| # | Artifact | What it is | Where it lives | Committed? | Built by |
|---|---|---|---|---|---|
| 1 | **Golden dataset** | the ~100 **input** cases — each = the `(ds,y)` series **+ ground truth** (`audit_only`: `true_injected_boundaries`, `expected_intervention_family`) **+ `intended_failure_lever`**. The "answer key." | `pocs/llm_eval/data/` (tiny CSVs + metadata json) | **yes** (small) | Topic 2 |
| 2 | **Traces** | the agent's recorded **behavior** on one golden case — diagnoses seen, tool picks, accept/reject, per-method metrics. **Derived; one per run.** | `reports/changepoint/<run_id>/` where `run_id = "<scenario_id>-<seed>"` | **no** (`reports/` gitignored — regenerated) | Topic 3 |
| 3 | **LangSmith dataset** | a *registration* of the golden dataset's `(inputs, expected_outputs)` so `evaluate()` can run the agent + score + track experiments over time. A re-shaping of #1, not new data. | LangSmith cloud | n/a | Topic 6 |

Key consequences (verified on disk):
- **Golden ≠ traces.** Golden is the input *with answers*; traces are the output. Failure modes
  are found by reading **traces (#2)** and comparing each to its golden **ground truth (#1)**.
- Same `scenario_id`+`seed` **overwrites** the same run dir → stability-repeats (D-open) must
  vary the seed to keep N traces.
- The 6 scenarios currently in `changepoint/data/scenario_metadata.json` are the **seed** of the
  golden dataset; Topic 2 grows it to ~100 with lever tags. (Their `reports/` traces — e.g. the
  one existing `many_temporary_events_long_history-1729` — happen to *succeed*; failure-mode
  coding needs the *failing* traces our hard cases are designed to produce.)

### How many datapoints to find failure modes? (discovery ≠ measurement)

Three different N for three different jobs:

| Job | What | N |
|---|---|---|
| **Discovery** (open-code → taxonomy) | code only **failing** traces until **saturation** (no new codes). The agent is bounded (5 tools, 4 lever classes) so codes saturate fast. | **~20–30 failing traces** (not all 100) |
| **Measurement** (apply frozen codebook) | apply the fixed taxonomy to **all ~100** for per-mode counts/rates — a *population* for statistics. | **~100** |
| **Agreement** (Cohen's κ) | 2 labellers double-code an overlap subset. | **~20 overlap traces** |

Our mix deliberately seeds ~40–50 designed-to-fail cases (~20 unsolvable + the prompt/pipeline
probes among the 70 synthetic), so the discovery pool is healthy. **~100 total is not arbitrary:
it's "enough failures to saturate discovery AND enough population to measure rates."**

---

## 1. Grounding facts (verified against current code on `llm_eval` @ `281ef7f`)

These are settled by reading the code; they are *inputs* to the topics, not open questions.

### The agent under eval = the **changepoint pipeline only**
It is the only track that runs the core ReAct agent + LLM. (Drift's LLM path
`llm_reason.py` was deleted in the 006 merge; anomaly has no LLM call.)

### Agent input (the "case")
- `Scenario` (`changepoint/scenarios.py:83-91`): `{scenario_id, title, split: SeriesSplit,
  n_changepoints_to_detect, seasonal_period, audit_only}`.
- Only the **training region** of `split` is visible to the agent; test is held out.
- The LangGraph invoke payload is tiny (`pipeline.py:362`):
  `{scenario_id, image_path, seasonal_period, iterations:[], rejected_signatures:[]}`.
  Everything real (split, diagnostics, baselines, tool registry, prompts, models) rides
  out-of-band on `RunContext`.

### Ground truth (the "golden output") — held out from the agent
- `Scenario.audit_only = {note, true_injected_boundaries: list[int],
  expected_intervention_family: str}`, stored in `changepoint/data/scenario_metadata.json`.
- **Never** passed to any agent node (FR-003/FR-033); enforced by `core/events/leakage.py`.
- The **deterministic prediction** to score against it = the `DiagnosticsBundle`
  (`detected_changepoints[*].index`, `candidate_event_blocks`, `candidate_drift_intervals`)
  plus the agent's chosen tool (`iterations[*].proposal.tool`, `final_candidate.tool`).

### Agent output + persisted artifacts (the eval's raw material)
Per run, `reports/changepoint/<run_id>/` holds:
- `agent_trace.json` — full replayable record (visual, diagnostics, naive_summary,
  iterations, rejected_signatures, accepted, final_candidate, final_case, prompt_ids,
  model_ids, seed).
- `metrics.json` — per-method forecast metrics (MAE/RMSE/WAPE/sMAPE) for
  `{agent, naive_workflow, full_history_prophet}` + `winner`.
- `effective_config.json`, `events.jsonl`, `report.md`, `forecast_comparison.{png,csv}`.

### Objective oracle (non-LLM signal we get for free)
The backtest gate (`core/backtest/gate.py`) + `metrics.json` tell us, per case, whether the
agent **beat naive** and who **won** — a cheap, deterministic correctness signal.

### Injection seams (so the POC never edits core)
`run_scenario(...)` (`changepoint/pipeline.py:138`) accepts:
- `series_df=` — run on an arbitrary `(ds, y)` DataFrame with custom `train/val/test` ratios
  (bypasses fixtures). **Note:** this path builds a `Scenario` with **no `audit_only`**, so
  the harness must hold ground truth externally and join it.
- `model_wrappers=` — inject wrapped/fake `ModelWrapper`s.
- `credentials=` (`RunCredentials`) — BYO Anthropic/AWS keys **and LangSmith** opt-in.
- `extra_sinks=` — extra event sinks.

### LangSmith — already partially wired
- `langsmith==0.8.15` is installed.
- `run_scenario` sets `LANGSMITH_TRACING/_API_KEY/_PROJECT` env vars (scoped to the run,
  restored in `finally`) when `RunCredentials.has_langsmith` (`pipeline.py:168-194`).
- The **Bedrock** path (`ChatBedrockConverse`, a LangChain Runnable under LangGraph)
  auto-traces the node tree from those env vars. The **raw-Anthropic** path
  (`AnthropicStructuredClient`) bypasses LangChain auto-tracing → needs explicit wrapping
  if we eval on the Anthropic provider.
- Eval-experiment wiring (`Client.create_dataset` / `create_examples` /
  `langsmith.evaluation.evaluate`) does **not** exist yet — Topic 6 builds it.

### What's missing today
`src/ailf/core/eval/` is a docstring-only stub. No failure-mode taxonomy, no ~100-case
generator, no golden-record join, no judge prompts, no boundary-matching policy, no
LLM-nondeterminism/stability handling.

---

## 2. High-level topics (ordered; each is one coherent work chunk)

### Topic 1 — Golden-record schema + ground-truth contract + boundary-matching policy ✅ DESIGNED
**Why:** every downstream step needs one stable per-trace record. Ground truth is currently
fragmented and `audit_only` is never surfaced into any artifact.
**→ Full design (adversarially verified): [`topic1_golden_record.md`](./topic1_golden_record.md).**
**Scope (done):**
- Canonical per-trace golden record (joins `audit_only` GT + `agent_trace.json` prediction +
  `metrics.json` outcome + derived eval fields + Topic-4 label slots).
- **Boundary matching policy that branches on `expected_intervention_family`** — the flat
  `true_injected_boundaries` means POINTS for step/prophet-kink families but INTERVAL pairs for
  ramp/clean-event families.
- **Key finding (blocker caught in review):** point-family precision/recall measures the
  **detector** (Prophet ranks by slope-change; pure level shifts never land on the grid), NOT
  the agent — so it's reported as a detector diagnostic and **excluded from
  `is_behavioral_failure`**. Interval families (`clean_event`/`ramp`) are the trustworthy
  boundary signal.
- Ground truth for generated cases lives in a POC-local metadata file (since `series_df` runs
  carry no `audit_only`).
**Depends on:** none.
**Resolved:** point tolerance `N=25` (grid-based) + strict `N=10`; IoU `0.5` + strict `0.7`;
`fpr_per_100` dropped; generate with golden-style absolute splits. Remaining open items → §6 of
the design doc (carried as confirmations, not blockers).

### Topic 2 — Diverse trace + dataset generation (~100 cases, lever-tagged) ✅ BUILT (90 cases generated)
**Built:** `pocs/llm_eval/generator/` — base signal + injectors + out-of-vocab primitives,
`verify.py` brute-force gate (runs the REAL detector+gate), `catalog.py`, `export.py`. **90
synthetic cases generated** under `pocs/llm_eval/data/` (competence 33 / prompt 25 / pipeline 20 /
tool 12; gate-labeled families: ramp 42, clean_event 23, fallback/unsolvable 17, step 8).
**Honest labeling realized:** the gold `expected_intervention_family` = the gate-winning family, NOT
the injected intent — **31/90 cases diverge** (authored vs gate-winner both recorded). Real-data
(10) bucket deferred. (Original design doc below.)
### Topic 2 (design) — Diverse trace + dataset generation ✅ DESIGNED
**Why:** runtime only ships 6 committed fixtures; NOTES.md wants ~100 diverse traces with
tracked ground truth, including hard/unsolvable cases and real downloaded series.
**→ Full design (recipes verified by EXECUTING them against the real detector+gate):
[`topic2_dataset_generation.md`](./topic2_dataset_generation.md).**
**Key finding (overturned the naïve design):** you **cannot** label a case's
`expected_intervention_family` by what you injected — a clean level *step* at idx 420 is best
fixed by the **ramp** tool (step tool loses 32.8 vs naive 20.6; ramp wins 5.98), because Prophet
snaps changepoints to its ~28-day grid. **The gold label = whatever the brute-force gate proves
WINS.** The generator proposes; `verify.py` (real detector+gate) disposes.
**Reuse found in-repo:** `pocs/changepoint/seasonalityV2/datasets.py` already generates the
growing/multiplicative seasonality (the NOTES.md sinusoid); `pocs/data/sec*.csv` (20 series) are
ready unsolvable candidates; `darts.datasets` + `statsmodels` cover the 10 real (objective-only).
**Mix (D3):** ~70 synthetic-combined · ~20 unsolvable · ~10 real — **and every case is also
tagged with an `intended_failure_lever` (D8)** so each Topic-7 fix targets exactly the right
cases. The lever tag is orthogonal to the source bucket (a synthetic-combined case can be a
competence, prompt, or pipeline probe; the unsolvable cases are the tool/capability lever).
**Scope:**
- **Synthetic-combined (~70)** — seeded generator (reuse the existing `np.random.default_rng`
  + fixed-index-injection pattern) emitting `(ds, y)` CSVs with multi-issue series (drift +
  changepoint + event blocks + recurring events combined) where the right answer **is** one of
  the 5 tools. Exact `audit_only` ground truth (`true_injected_boundaries`,
  `expected_intervention_family`). This bucket carries the **competence baseline**,
  **prompt-probe**, and **pipeline-probe** levers (see §6 for the concrete probes).
- **Unsolvable (~20, D4)** = the **tool/capability lever** — structured-but-out-of-vocabulary:
  (a) out-of-vocabulary structure (growing seasonal amplitude / nonlinear trend /
  multiplicative seasonality) and (b) conflicting simultaneous issues. Ground-truth
  `expected_intervention_family = fallback`, **verified by brute-forcing all 5 tools at
  generation time and confirming none beats naive on the held-out test** (a generation-time
  gate, not a guess).
- **Real (~10, D5)** — ingested real public series, **objective-outcome-only**: no boundary
  labels; held-out future actuals are the ground truth.
- POC-local metadata file mirroring `scenario_metadata.json`
  (`train_end`, `validation_horizon`, `test_horizon`, `seasonal_period`, `audit_only`) plus
  `intended_failure_lever` and `dev_or_test` (D9 split); for real cases `audit_only` carries no
  boundaries (a `ground_truth_kind: objective_only` flag).
- Each lever's cases come in **dev** and **held-out test** partitions, with a generator that
  can emit **fresh-seeded** cases of the same flavor on demand (D9 generalization check).
- Seed + record everything (constitution Principle V).
**Depends on:** Topic 1.
**Open questions:** which real datasets/source; exact knob ranges per synthetic flavor; the
dev/test count per lever.

### Topic 3 (MVP) — Eval pipeline on the CURRENT code → score → LangSmith ✅ BUILT + RAN (5/6 beat-naive)
**Scope pivot (user decision D11):** the near-term goal is to **form the eval pipeline
end-to-end on the CURRENT agent code** — produce a real **score**, push the **golden dataset to
LangSmith**, and explore it from the **UI**. *Not yet*: the prompt-improvement loop (Topic 7),
the failure-mode taxonomy (Topic 4), or the LLM-judge (Topic 5). **Runs on the 6 committed
scenarios — no Topic-2 dependency.**
**→ Full design (a verifier ran a real end-to-end `evaluate()` against live LangSmith):
[`topic3_mvp_pipeline.md`](./topic3_mvp_pipeline.md).**
**Scope (MVP):**
- Batch-run `run_scenario(..., credentials=RunCredentials(langsmith_tracing=True,...))` over the
  6 fixtures on **Bedrock (D2)**, tracing ON; join each run dir + `audit_only` → Topic-1 golden
  record. No core/pipeline edits.
- **6 deterministic code-check evaluators** (no LLM judge). **Headline = true 2-way `beat_naive`
  rate** (`agent.mae < naive.mae`) + diagnostics (interval-boundary recall, family-match, 3-way
  winner). All read `metrics.json` / `agent_trace.json` / `scenario_metadata.json`.
- Push `changepoint-golden-6` via `Client.create_examples(examples=[{...}])` (**0.8.15 modern
  form — NOT the teaching repo's `inputs=/outputs=`**) → `evaluate(target, data, evaluators)` →
  scored experiment in the UI.
**Two correctness fixes the review forced:** (1) `winner=='agent'` is a *3-way* win, not
beat-naive → headline uses the true 2-way `agent.mae < naive.mae`; (2) `chose_expected_family`
compares to *authored* intent (which Topic 2 showed ≠ gate-winner) → demoted to a caveated
diagnostic `chose_authored_family`, not the headline.
**"Run from the UI" — honest answer:** the heavy local Prophet+Bedrock agent **cannot** be
launched from a UI button (hard `0.8.15` limit). What IS in the UI: browse/edit the dataset,
view per-evaluator score averages (the headline), **compare** experiments, browse agent traces.
Re-launching is one CLI command.
**Depends on:** Topic 1 (schema). **NOT** Topic 2. **Open items:** REPLAY vs LIVE target
(default REPLAY); single-run vs N-repeat (default 1); dataset/project names — all in the doc's §7.

### Topic 4 — Error analysis → forecasting failure-mode taxonomy ✅ BUILT (deterministic classifier)
**Built:** `pocs/llm_eval/llm_eval/failure_modes.py` — a 6-mode taxonomy + deterministic classifier
over golden records, preserving the **capability-gap vs behavioral-failure** split (D8). Modes:
`clean_success`, `capability_gap` (unsolvable, agent rightly didn't beat naive — not a bug),
`spurious_win_on_unsolvable`, `accepted_worse_than_naive` (behavioral), `wrong_family_but_won`
(behavioral), `missed_boundary_structure` (pipeline blindness). Surfaced as a categorical
`failure_mode` LangSmith evaluator + a per-lever×class cross-tab in `poc_cli score`. *(MVP-scope:
deterministic coding, not the 2-human-labeller κ exercise — that's the rigor upgrade if needed.)*
### Topic 4 (design) — Error analysis → forecasting failure-mode taxonomy
**Why:** NOTES.md step 2/3 + Lecture 11 "Analyze" — bucket failures into a small named
taxonomy by coding the ~100 traces.
**Method (D6):** pure empirical open/axial coding — **no** pre-seeded candidate list.
**Scope:**
- Open-code the persisted traces (label what actually went wrong, in vivo), then axial-code
  the open codes into 4–8 named failure modes.
- Each mode = name + one-line definition + count + which traces carry it.
- **2 human labellers** double-code a sample; report **Cohen's κ** for agreement.
- The candidate codes from earlier drafts (missed/false changepoint, wrong intervention
  family, intervention-outside-menu, accepted-worse-than-naive, …) are explicitly *not*
  assumed up front — they may or may not emerge from the coding.
- **Crucial distinction to preserve in coding (D8):** separate a **capability gap** (the agent
  *correctly* fell back because no tool fits — high error, but **not** an agent bug; motivates a
  new tool) from a **behavioral failure** (the agent picked a confidently-wrong tool / looped /
  ignored a clear diagnostic — fixed by prompt or pipeline). Conflating them would mean trying
  to fix a missing capability with a prompt tweak. Cross-tab each failure mode against the
  `intended_failure_lever` to confirm the levers actually fire as designed.
- **Sample sizes (D6):** open-code failing traces to saturation (~20–30) → freeze codebook →
  measure all ~100 → double-code ~20 overlap for κ. (See **Vocabulary** for why these N.)
**Depends on:** Topic 3.
**Open questions:** who are the 2 human labellers (the only open item — sizes now set in D6).

### Topic 5 — Per-failure-mode evaluators (code-check + validated LLM-judge) + methodology
**Why:** NOTES.md step 3 + Lecture 11 "Measure" — one failure mode → one binary pass/fail →
one evaluator; cheapest sufficient oracle.
**Scope:**
- Code-check evaluators where an oracle is cheap: intervention-in-menu
  (`registry.allowed_names`), chose-expected-family (vs `audit_only`), beat-naive
  (`metrics.json`), changepoint precision/recall/FPR within the Topic-1 tolerance.
- LLM-as-judge (4-part anatomy, versioned prompt `prompts/<name>_vN.md`, cheaper judge model)
  for rationale/explanation quality + constraint adherence; validate on a frozen
  train/dev/test split, report TPR/TNR, bias-correct θ + bootstrap 95% CI.
- All evaluators return the LangSmith `{key, score}` signature.
**Depends on:** Topic 4.
**Open questions:** judge model choice + calibration thresholds (min TPR/TNR/κ) before a judge
is "trusted".

### Topic 6 — LangSmith integration: tracing + persistent dataset + `evaluate()` experiments
**Why:** NOTES.md step 4 — see the eval in LangSmith. Mirror `block5_evals/option_a_langsmith.py`.
**Scope:**
- Ensure per-LLM-call spans on whichever provider we run (Bedrock auto-traces; add a
  LangSmith-wrapped/`wrap_anthropic` client for the raw-Anthropic path if needed).
- Create a persistent named dataset (`ailf-changepoint-traces-v1`) via
  `Client.create_dataset` / `create_examples` (`inputs=case`, `outputs=ground-truth`).
- Run `langsmith.evaluation.evaluate(target_fn, data=dataset, evaluators=[Topic-5],
  experiment_prefix=...)`; verify result-parsing against installed `langsmith==0.8.15`.
- (Optional) Phoenix offline/no-account fallback (`block5_evals/option_b_phoenix.py`).
**Depends on:** Topic 5 (uses its evaluators) — but tracing can be smoke-tested earlier.
**Open questions:** LangSmith vs Phoenix (LangSmith confirmed by NOTES.md; Phoenix as
fallback?); whether any evaluators/judge-prompts graduate from the POC into
review-gated `src/ailf/core/eval/`.

### Topic 7 — Close the loop: lever-targeted fixes + before/after demonstration
**Why (D7):** the payoff of the eval. Surfacing a systematic failure, intervening, and re-running
the *same* eval to show measurable improvement (visualized as experiment-over-experiment deltas
in LangSmith) is the strongest possible proof the eval is useful — the Lecture 11
*Analyze → Measure → Improve* loop. Demonstrating fixes across **three different levers** (prompt,
pipeline, tool) is far stronger than one fix.
**Mechanism (D10, see §5):** a ~40-line POC driver builds its own `RunContext` with swapped
prompt / tool-registry / diagnostics and calls `build_agent_graph(ctx)` — **no `core/` or
`pipeline.py` edits.** Writes the same `agent_trace.json` / `metrics.json` the eval consumes.
**Scope (one cycle per lever, D8/D9):**
- **Prompt lever** — author `react_decision_v3.md` in the POC fixing a prompt weakness (§6:
  P1–P5), inject as `RunContext.decision_prompt`. Re-run the prompt-probe cases.
- **Pipeline lever** — a tuned-threshold copy of `compute_diagnostics` in the POC (§6: T1–T3),
  inject as `RunContext.full_diagnostics`. Re-run the pipeline-probe cases.
- **Tool lever** — a new pure invoker + `ToolSpec` (e.g. multiplicative-seasonality / amplitude
  regressor) registered onto the registry and added to the rendered menu; likely paired with a
  new diagnostic so the structure is *surfaced*. Re-run the unsolvable cases.
- **Demo rigor (D9):** build each fix against the **dev** subset, report the lift on the
  **held-out test** subset, and regenerate **fresh-seeded** same-flavor cases to prove
  generalization. Confirm the **competence baseline doesn't regress**.
- Each cycle = a named LangSmith experiment pair (before/after) on the same dataset.
- Proven fixes get a **separate promotion PR** into the real pipeline (prompt `_vN`, diagnostic
  tune, or new `ToolSpec`) — out of POC scope, flagged for the changepoint team's review gate.
**Depends on:** Topic 6 (re-runs through the same dataset + evaluators).
**Open questions:** which specific weakness(es) to fix first per lever; whether the tool-lever
fix is in scope for the POC timeline or deferred to a promotion PR.

---

## 3. Cross-cutting open questions (still open — resolved ones moved to **Decisions**)

1. ~~**Boundary-matching tolerance (Topic 1)**~~ — **resolved** in `topic1_golden_record.md`
   (point `N=25`+strict `10`; IoU `0.5`+strict `0.7`; `fpr_per_100` dropped). 4 confirmations
   remain in that doc's §6.
2. **Stability repeats (Topic 3)** — how many repeated runs per case to measure
   nondeterminism; concurrency/cost budget for ~100 Bedrock runs.
3. **Real datasets (Topic 2)** — which public series to ingest for the 10% real bucket.
4. **Labellers (Topic 4)** — who are the 2 human coders. (Sample sizes set in D6 / Vocabulary.)
5. **Judge model + calibration thresholds (Topic 5)** — which (cheaper) model judges;
   min TPR/TNR/κ before a judge is "trusted".
6. **Promotion path (Topic 6)** — which pieces stay throwaway vs graduate to
   review-gated `src/ailf/core/eval/`.

*Resolved:* eval scope (D1), provider (D2), dataset mix (D3), unsolvable definition (D4),
real-data ground truth (D5), taxonomy method (D6), eval-driven-dev loop (D7), failure levers
(D8), demo rigor (D9), fix location (D10).

---

## 4. Failure levers — at a glance (D8)

Every dataset case is tagged with one lever. A lever defines *why* the agent fails and *which
fix* moves it — making each Topic-7 before/after unambiguous.

| Lever | The agent fails because… | The fix (Topic 7) | Probe cases |
|---|---|---|---|
| **Competence** (control) | nothing — it should succeed | — (must NOT regress) | clean single-issue, one dominant tool |
| **Prompt** | it saw the right info; the prompt steered it wrong | new prompt `_vN` | §6 P1–P5 |
| **Pipeline** | a diagnostic threshold *hid* the structure → agent flew blind | tune a diagnostic | §6 T1–T3 |
| **Tool/capability** | no tool can express the structure | add a tool (+ diagnostic) | the D4 unsolvable cases |

"High error" alone is **not** the failure signal — relative-to-baseline (beat-naive / winner)
is, because absolute error mostly measures data difficulty. And a **capability gap** (correct
fallback, high error) is *not* an agent bug — only a **behavioral failure** (confidently-wrong
pick) is. The agent's own fallback is `full_history_default` (plain Prophet on full history),
distinct from the `naive_workflow` baseline it is scored against.

---

## 5. Injection mechanism — iterating prompts/tools/diagnostics from the POC (D10)

The core engine is driven entirely by a `RunContext` the caller constructs; the prompt, tool
registry, and diagnostics are **plain values on it, not baked into core** (`runtime.py:15-36`).
So a POC driver builds its own `RunContext` and calls `build_agent_graph(ctx)` — swapping any
lever with **zero edits to `core/` or `pipeline.py`**. Verified seams:

- **Prompt** — `RunContext.decision_prompt` is just a string (`runtime.py:31`); the node reads
  it verbatim (`nodes.py:55`). Write `pocs/llm_eval/prompts/react_decision_v3.md`, load via the
  existing `load_prompt(POC_DIR, "react_decision", 3, fill={"tool_menu": menu})`.
- **New tool** — `ToolRegistry.register()` is public + mutating (`registry.py:119`); a tool is a
  pure `(ToolContext, params) -> {"yhat", "resolved_params"}` invoker (`registry.py:18-22`) +
  a `ToolSpec`. Register onto `register_changepoint_registry()`, enable via `.for_run({...})`.
  Building the `RunContext` ourselves **bypasses the config lockstep** (`resolve_config`'s tool
  validation only runs inside `run_scenario`).
- **Tuned diagnostics** — `RunContext.full_diagnostics` is duck-typed: anything with
  `.to_agent_dict(enabled)` (`runtime.py:24`). Pass a threshold-tweaked copy of
  `compute_diagnostics`'s bundle.

**The one catch:** `run_scenario()` hardcodes prompt/registry/diagnostics
(`pipeline.py:289-304`), so the lever-swap path does **not** reuse `run_scenario` — it is a
~40-line driver mirroring `pipeline.py`'s prelude (detect → baselines → diagnostics → build ctx
→ `build_agent_graph().stream()` → `write_agent_trace`/`write_metrics_json`), importing only
public symbols. The unmodified Topic-3 batch run still uses `run_scenario` directly.

---

## 6. Concrete weaknesses found in the current code (candidate Topic-7 targets)

Found by reading the prompt + node + diagnostics source. These are *hypotheses* the eval will
confirm or refute — not assumed bugs. Each is a probe-case design + a one-lever fix.

### Prompt lever (fix = `react_decision_v3.md`)
- **P1 — no "do nothing / fallback" rule.** The decision rules map 4 patterns → 4 structural
  tools and never say when to pick `full_history_default` (`react_decision_v2.md:14-29`). On a
  clean series the prompt pressures a force-fit. *Probe: clean seasonal series, no real structure.*
- **P2 — "must strictly beat naive" framing encourages over-intervention.** "If it beats the
  naive workflow you win" / "the bar you must strictly beat" (`react_decision_v2.md:1-4`,
  `nodes.py:42`) frames a contest — backwards on hard cases, discourages graceful fallback.
  **This is the bridge: the unsolvable cases also surface this prompt bug, not only the tool gap.**
- **P3 — visual-first mandate over-anchors.** "rationale MUST begin by citing the visual
  inspection BEFORE any numeric diagnostic" (`react_decision_v2.md:6-9`) with no rule to
  distrust an ambiguous chart when numbers are crisp. *Probe: subtle drift that reads as a step.*
- **P4 — no multi-issue tie-break.** Rules assume one pattern; no "address the largest-magnitude
  structure first." *Probe: large permanent shift + small temporary event.*
- **P5 — no within-tool param guidance.** `step_regressor` takes `{primary, all_detected}` with
  no when-to-use rule. *Probe: one true changepoint + spurious detections.*

### Pipeline lever (fix = tuned diagnostic thresholds)
- **T1 — drift just under threshold.** `_slope_scan_drift_intervals` rejects `duration < 45` or
  `total_delta < 25` (`diagnostics.py:230-248`) → no `candidate_drift_intervals` → ramp tool's
  precondition can't fire. *Probe: genuine ~40-day drift.*
- **T2 — event just over the duration cap.** Event blocks require `3 ≤ duration ≤ 90`
  (`diagnostics.py:148`) → a 95-day event isn't flagged → `clean_event` unavailable.
  *Probe: 95-day temporary event.*
- **T3 — recurring event under the year bar.** Needs `≥3 distinct years` (`diagnostics.py:177`)
  → a 2-year recurring pattern reads `is_calendar_recurring=False` → holiday tool's precondition
  (`interventions.py:243`) rejects it. *Probe: 2-year recurring event.*

### Tool/capability lever (fix = new `ToolSpec`, the D4 unsolvable cases)
- The 5 tools express step / ramp / clean-event / holidays / recent-window only. **No tool
  expresses multiplicative or amplitude-growing seasonality** (the NOTES.md sinusoid). A new
  invoker (+ a diagnostic that surfaces "growing seasonal amplitude") closes it. Keep it a
  *generally useful* intervention, not a case-specific hack.

---

## 7. ⚠️ Security note

`.env.example` currently has a **real-looking LangSmith key** filled in
(`LANGSMITH_API_KEY=lsv2_pt_…`) in the working tree. `.env.example` is committed to git, so
this value must be **kept empty there** and the real key placed only in the gitignored `.env`.
If this key was ever committed/pushed, **rotate it**. (Currently it's an *uncommitted* local
edit — keep it that way.)
