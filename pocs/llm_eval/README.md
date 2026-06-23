# LLM Eval — MVP pipeline

Forms the eval pipeline end-to-end on the **current** changepoint agent over the **6 committed
scenarios**: batch-run → join into golden records → deterministic code-check evaluators → a real
**score** → push a golden dataset to **LangSmith** + run an experiment explorable in the UI.

No LLM-judge, no failure-mode taxonomy, no prompt-improvement loop (later topics). **No `src/ailf`
edits** — reuses `run_scenario(..., credentials=RunCredentials(langsmith_tracing=True, ...))`.

Design + rationale: [`topic3_mvp_pipeline.md`](./topic3_mvp_pipeline.md) ·
schema: [`topic1_golden_record.md`](./topic1_golden_record.md) · plan: [`TOPICS.md`](./TOPICS.md).

## Run (from the repo root)

```bash
# 1) Offline score on whatever run dirs already exist — NO credentials needed:
PYTHONPATH=pocs/llm_eval uv run python -m llm_eval.cli score

# 2) Full pipeline: run the agent on all 6 (Bedrock), join, push to LangSmith, run experiment.
#    Needs .env: AWS_ACCESS_KEY_ID/SECRET (+ VISUAL_MODEL_ID, REACT_MODEL_ID) and LANGSMITH_API_KEY.
#    ANTHROPIC_API_KEY must be UNSET (else the provider flips off Bedrock).
PYTHONPATH=pocs/llm_eval uv run python -m llm_eval.cli all \
  --dataset-name changepoint-golden-6 --experiment-prefix changepoint-current-code
```

Subcommands: `batch` (run agent → run dirs) · `join` (run dirs → `golden_records/golden.jsonl` +
score) · `score` (print headline) · `push` (dataset only) · `eval` (push + experiment) · `all`.

## The score

- **Headline: beat-naive rate** (X/6) — the true 2-way `agent.mae < naive.mae` (NOT `winner=='agent'`,
  which is a 3-way win that also requires beating plain Prophet).
- **Diagnostics:** interval boundary recall (IoU≥0.5, the 4 interval families), 3-way winner,
  chose-authored-family (caveat: authored intent may differ from the gate-winning family),
  agent−naive MAE, and a point-family detector recall (measures Prophet's grid, *not* the agent).

## "Run from the LangSmith UI" — honest scope

The heavy local Prophet+Bedrock agent **cannot** be triggered from a UI button (hard `0.8.15`
limit). In the UI you CAN: browse/edit the dataset, read per-evaluator score averages (the
headline), **compare** experiments, and browse the agent's traces. Re-launching is the one-line
`... cli all` (or `eval`) command above.
