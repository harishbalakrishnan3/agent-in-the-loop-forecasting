# Topic 3 (MVP) — Eval pipeline on the CURRENT code → score → LangSmith

> **Status:** ✅ **BUILT + RAN END-TO-END** on real Bedrock + LangSmith (2026-06-23). Code lives in
> `pocs/llm_eval/llm_eval/` (see `README.md`). Companion to `TOPICS.md`, `topic1_golden_record.md`.

## First baseline result (current code, 6 committed scenarios)

| Metric | Result |
|---|---|
| **beat-naive rate (HEADLINE)** | **5/6 (83%)** |
| 3-way winner (diagnostic) | 5/6 |
| chose-authored-family (diagnostic, caveated) | 5/6 |
| interval boundary recall (micro, 4 interval families) | 0.909 |

**The single miss = `level_shift_loses_seasonality`** — agent chose `full_history_ramp_regressor`
(authored intent was `full_history_step_regressor`) and `full_history_prophet` won. This is the
**live confirmation of the Topic-2 finding**: a clean injected level *step* is best repaired by the
ramp tool / handled by Prophet, not the step regressor — so the authored-family label diverges from
the gate-winner, exactly as predicted. The eval surfaced a real, explainable behavior on run one.
Dataset + scored experiment are live in LangSmith (APAC workspace, dataset `changepoint-golden-6`).

## 0. Scope (locked by the user)

**Goal:** form the eval pipeline end-to-end, get a **score on the CURRENT agent code**, push the
**golden dataset to LangSmith**, and explore it from the **LangSmith UI**.

| In scope (MVP) | Out of scope (later topics) |
|---|---|
| Batch-run the current agent over the **6 committed scenarios** | Topic 2's ~100 generated cases (NOT needed) |
| Topic-1 join → golden records | LLM-as-judge (Topic 5) — all evaluators are deterministic code |
| Deterministic code-check evaluators → a real number | Failure-mode taxonomy (Topic 4) |
| Golden dataset + experiment in LangSmith, explorable in UI | Prompt-improvement before/after loop (Topic 7) |
| Provider = AWS Bedrock, tracing ON | Any `core/`/`pipeline.py` edit |

**First real artifact:** a headline = **beat-naive rate (X/6)** + diagnostics (family-match,
interval-boundary recall), printed to stdout **and** attached to a named LangSmith experiment.
Uses the 6 fixtures' committed `audit_only` ground truth — no Topic-2 dependency.

## 1. Two correctness fixes the adversarial review forced (read before implementing)

The naïve evaluator design had two headline-distorting bugs (verified against real artifacts):

1. **`winner=='agent'` is a 3-WAY win, not "beat naive."** `metrics.json.winner` = min TEST mae
   over `{agent, naive_workflow, full_history_prophet}`. So an agent that beats naive but loses to
   plain Prophet scores 0 — punishing the agent for Prophet being good, which is NOT the
   "agent-in-the-loop adds value over naive" question. **Fix:** the **primary headline is the true
   2-way `beat_naive` = (agent.mae < naive_workflow.mae)**; keep `agent_is_winner` (3-way) as a
   secondary diagnostic.
2. **`chose_expected_family` compares to AUTHORED intent.** Topic 2 proved by brute force that the
   fixtures' authored `expected_intervention_family` can differ from the family that actually wins
   the gate (a clean step is best fixed by the ramp tool). So an agent picking a *valid, winning*
   non-authored tool would be scored "wrong." **Fix:** report it as **`chose_authored_family` (a
   diagnostic, not a correctness headline)**, with a caveat; do not average it into the headline.

**Honest headline = `beat_naive` rate** (objective, baseline-relative, the constitution's Principle-V
bar). Everything else is a labeled diagnostic.

## 2. Architecture (all under `pocs/llm_eval/`, zero core edits)

```
pocs/llm_eval/llm_eval/
  scenarios.py      # SCENARIO_IDS() = the 6 from load_metadata() (NOT REQUIRED_SCENARIO_IDS — that omits sustained_anomaly_block); load_ground_truth(sid)
  batch.py          # build_credentials(); run_all(sids, seed_runs=1) → run_dirs  (reuses run_scenario, tracing ON)
  golden.py         # decode_ground_truth_events(); build_golden_record(run_dir); interval IoU matcher; build_all/write_jsonl
  evaluators.py     # the deterministic LangSmith evaluators (fn(run,example)->{key,score}); ALL_EVALUATORS
  langsmith_push.py # ensure_dataset(); run_experiment_replay()/_live(); summarize()
  cli.py            # subcommands: batch | join | push | eval | all
```

**Reuse (no core edits):** `batch.py` imports `run_scenario` + `RunCredentials`. Tracing is on
purely by `credentials=RunCredentials(langsmith_tracing=True, langsmith_api_key=…,
langsmith_project=…)` — `pipeline.py:168-194` sets/restores the `LANGSMITH_*` env around the run.

**Feasibility fixes (from review):**
- **Bedrock (D2) requires `has_aws`:** `build_credentials()` must read non-blank
  `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` (+ optional `AWS_REGION`, default `us-west-2`) and
  **assert `credentials.has_aws`** (fail loud), and assert `ANTHROPIC_API_KEY` is **absent** (else
  the provider silently flips to Anthropic). Also need `VISUAL_MODEL_ID` / `REACT_MODEL_ID` set.
- **cwd / reports-root tension:** `llm_eval` is not an installed package and `run_scenario` writes
  to `Path("reports/...")` relative to cwd. **Run from the repo root** with `PYTHONPATH=pocs/llm_eval`
  (or a tiny `pocs/llm_eval/run.py` shim that sets `sys.path`), and pass an explicit
  `reports_root=Path("reports/changepoint")` so run dirs are deterministic regardless of cwd.
- **`seed_runs>1` overwrites** unless the seed varies (`run_id="<sid>-<seed>"`): pass
  `override=ConfigOverride(seed=base+rep)` to get distinct dirs. (MVP default `seed_runs=1`.)

## 3. The deterministic evaluators (`fn(run, example) -> {"key","score"}`)

REPLAY puts the full golden record in **both** `example.outputs` (ground truth) and `run.outputs`
(prediction/outcome); each evaluator reads the convenient side. Pure, no I/O, no LLM.

**Headline (agent-scored):**
1. **`beat_naive`** *(PRIMARY)* — `1 if outcome.agent_test_metrics.mae < outcome.naive_test_metrics.mae else 0`. The honest baseline-relative signal. All 6 scored.
2. **`boundary_recall_interval`** — interval families only (`full_history_clean_event`,
   `full_history_ramp_regressor`): IoU≥0.5 greedy match of `candidate_event_blocks` /
   `candidate_drift_intervals` (end-normalized) vs decoded interval pairs. Returns `score=None`
   (value `"n/a_point_family"`) for point families → excluded from the mean.

**Diagnostics (reported, NOT headline):**
3. **`agent_is_winner`** — `1 if outcome.winner=="agent"` (3-way; explains when Prophet beats both).
4. **`chose_authored_family`** — `1 if prediction.chosen_tool == ground_truth.expected_intervention_family`. Caveat: authored intent, may differ from gate-winner (Topic 2).
5. **`agent_minus_naive_mae`** — `agent.mae − naive.mae` (continuous; negative = better). Canonical check: `1.8217 − 13.9533 = −12.1316`.
6. **`point_boundary_recall_detector`** — point families only (step/holiday), `N=25` grid tolerance. Labeled a **detector** diagnostic (measures Prophet's grid, NOT the agent — Topic-1 blocker); never in the headline.

**Aggregation (`summarize()`):** skip `score is None` per key. Headline = **beat-naive rate** =
mean of `beat_naive` over 6; interval recall = **micro** `Σtp/(Σtp+Σfn)` recomputed locally from
records (the UI column shows a per-case macro mean — caption the difference). Canonical sanity:
`many_temporary_events_long_history-1729` → tp=5, fp=0, fn=1, recall=0.833 at IoU=0.5.

**Decode branches on the FULL family names** (from real metadata):
`full_history_step_regressor` + `full_history_prophet_tuned_holidays` → POINT;
`full_history_ramp_regressor` → one INTERVAL; `full_history_clean_event` → INTERVAL pairs
(two-at-a-time). The 6 fixtures: 1 step, 1 ramp, **3 clean_event**, 1 holiday → **4 interval
families get boundary recall**, 2 point families get only the detector diagnostic.

## 4. LangSmith integration — matched to INSTALLED `0.8.15` (independently re-confirmed)

**⚠️ API differs from the teaching repo.** `create_examples` in 0.8.15 takes a **list of example
dicts**, NOT parallel `inputs=[]`/`outputs=[]` lists (mixing them raises `ValueError`):

```python
client = Client()                                  # needs LANGSMITH_API_KEY (LANGCHAIN_API_KEY fallback)
name = "changepoint-golden-6"
if not client.has_dataset(dataset_name=name):      # cleaner than try/except read_dataset
    ds = client.create_dataset(name, description="6 committed changepoint scenarios; audit_only GT")
    client.create_examples(
        dataset_id=ds.id,
        examples=[{"inputs":  {"scenario_id": rec["scenario_id"], "seed": rec["seed"],
                                "n_changepoints_to_detect": ..., "seasonal_period": ...},  # AGENT-VISIBLE only
                   "outputs": rec,                                                          # FULL golden record
                   "metadata": {"family_channel": "interval"|"point", ...}}
                  for rec in records],
        max_concurrency=3)                          # must be 1..3

from langsmith.evaluation import evaluate
results = evaluate(target_fn, data=name, evaluators=ALL_EVALUATORS,   # target is POSITIONAL-ONLY (the "/")
                   experiment_prefix="changepoint-current-code", max_concurrency=4, client=client)
for r in results:                                   # ExperimentResults is iterable; has .url, .to_pandas()
    for e in r.get("evaluation_results", {}).get("results", []):
        e.key, e.score                              # attributes; guard e.score is None
```

`evaluate()` also has `num_repetitions: int` (built-in stability repeats — no custom loop needed).

**Target = REPLAY (recommended):** `target_fn(inputs)` looks up the prebuilt golden record by
`inputs["scenario_id"]` and returns its prediction+outcome. Fast, deterministic, **no Bedrock
cost**, still a real comparable experiment. The agent's rich traces already exist from the batch
step (tracing ON). **LIVE** target (re-invokes `run_scenario` per example, 10–30 min, rate-limited)
is opt-in for nesting agent traces inside the experiment.

## 5. "Run it from the LangSmith UI" — the honest answer

**The heavy local Prophet+Bedrock agent CANNOT be triggered from a UI button.** The UI Playground
runs only prompt/model configs (and LangGraph *deployments* via Studio); it can't invoke an
arbitrary local Python target. This is a hard limit of `0.8.15` + a non-deployed local agent.

| Genuinely a UI action (works today) | Must be a CLI/script |
|---|---|
| Browse/edit the **dataset** `changepoint-golden-6` (inputs + ground-truth outputs) | Running the agent over the scenarios |
| View an experiment's per-example scores + **per-evaluator-key averages** (the headline is read off here) | Launching/re-launching the offline experiment |
| **Compare** 2+ experiments side-by-side (regression/improvement highlighting) | The deterministic join + evaluators |
| Browse the agent's **traces** (auto-attached from the batch step) | — |
| Define/run **online/automation** evaluators on live traces (later) | — |

**Closest workflow that satisfies the intent:** run once from the CLI; thereafter the dataset, the
scored experiment, the compare view, and the agent traces are **all fully explorable in the UI**,
and re-launching is one command:
```
uv run python -m llm_eval.cli all --target replay \
  --dataset-name changepoint-golden-6 --experiment-prefix changepoint-current-code
```

## 6. Sequencing (each step independently runnable; the SCORE comes before LangSmith)

- **Step 0** — sanity-check the one existing run dir
  (`reports/changepoint/many_temporary_events_long_history-1729/`, `winner=="agent"`, `agent.mae=1.8217`).
- **Step 1** — `golden.py` join + IoU matcher; verify canonical tp=5/fp=0/fn=1/recall=0.833;
  assert `derived.train_end == 1610 == metadata train_end`.
- **Step 2** — `evaluators.py` (all 6) driven by a fake `run`/`example` from that record. Verify
  `beat_naive=1`, `boundary_recall_interval=0.833`, `agent_minus_naive_mae=−12.1316`. **First real
  score, fully offline.**
- **Step 3** — `batch.py`: `run_scenario` over all 6 on Bedrock, tracing ON (10–30 min, run in
  background). Verify 6 run dirs; 6 traces land in the LangSmith project.
- **Step 4** — `build_all` → `golden_records/golden.jsonl` (6 records); print the local headline
  (beat-naive rate / family diagnostics / micro interval-recall). **The score on current code.**
- **Step 5** — `ensure_dataset` → push `changepoint-golden-6`; verify 6 examples in the UI.
- **Step 6** — `run_experiment_replay` + `summarize`; verify `results.url` and that UI per-key means
  match the local headline. Print headline + URL.
- **Step 7** *(optional)* — `--target live` to nest agent traces in the experiment.

Rationale: steps 1–2 give a real number with zero external deps / zero Bedrock cost; step 3 is the
only slow/credentialed step; LangSmith (5–6) is purely additive, so an outage never blocks the score.

## 7. Open decisions (recommended defaults in **bold**)

1. **Target = REPLAY** for the MVP (fast, deterministic, free); LIVE opt-in for nested traces.
2. **`seed_runs=1`** (single pass = a sample, not a fixed score — Opus has no temperature so tool
   choice varies); expose `--seed-runs N` (varying seed) for later modal-winner aggregation. *Note:
   varying seed also changes the deterministic prelude, so it conflates prelude + LLM variance.*
3. **Dataset name `changepoint-golden-6`**; re-push refreshed records under a `-v2` suffix (so old
   experiments stay attached) rather than `delete_dataset`.
4. **LangSmith project = `agent-in-the-loop-forecasting`** (repo default) so traces + experiments co-locate.
5. Set **`LANGSMITH_TRACING_V2="true"`** (lowercase) in the eval/push process to be unambiguous.
6. Point-family detector tolerance **`N=25`** headline (optionally also emit `N=10`); diagnostic-only.
7. Example **inputs = agent-visible fields only**; full golden record in outputs.

## 8. Constitution alignment

Principle **III** (this experiment on current code = the first measurement against the versioned
golden set), **V** (beat-naive is the honest baseline; seeds recorded), **POC-exempt** (all under
`pocs/llm_eval/`). Promotion bar unchanged (test-first + versioned prompts + core review).
