# SPEC: Agent-in-the-Loop Forecasting

> This is the single source of truth for *what* we are building and *why*.
> For the rules that govern *how* we build, see `.specify/memory/constitution.md`.
> For day-to-day operation of the repo, see `CLAUDE.md`. Background: `docs/`.

## 1. Problem & Research Question

Automatic forecasting models fail silently on drift, changepoints, outliers, and regime
changes; expert analysts catch these but do not scale. This project modernizes Prophet's
analyst-in-the-loop workflow by replacing the human analyst with a **bounded LLM agent**
that acts as a junior forecasting analyst.

**Core question:** *Can a bounded LLM agent improve a forecasting pipeline by diagnosing
common time-series failure modes, recommending interventions, and validating those
interventions through backtesting?*

The agent does not forecast. Models forecast, tools diagnose, the agent reasons, explains,
and validates.

## 2. System Architecture (5 layers)

1. **Data** — synthetic (seeded, knob-driven via Darts) and standard datasets.
2. **Forecasting models** — Seasonal Naive, Prophet, AutoARIMA / ETS (Chronos / TimesFM
   optional), behind a uniform interface.
3. **Diagnostics** — drift / changepoint / outlier detection tools + metric computation.
4. **LLM analyst agent** — a ReAct loop: reads diagnostics, picks tools, proposes bounded
   interventions, writes explanations.
5. **Evaluation / guardrail** — rolling backtests accept or reject interventions; LLM judge
   and manual evals assess agent behavior.

The agent is confined to *proposing*; the evaluation layer holds final authority.

## 3. Use-case tracks

The three use-cases run in parallel. Each plugs its diagnostic tool, dataset generator, and
prompts into the shared core agent + backtest + eval spine.

| Track       | Deliverables                                                      |
|-------------|-------------------------------------------------------------------|
| Drift       | dataset generation, drift-detection tool, prompts, pipeline, evals |
| Changepoint | dataset generation, changepoint-detection tool, prompts, pipeline  |
| Anomaly     | dataset generation, outlier-flagging tool, prompts, pipeline       |

## 4. Capability roadmap (priority order)

The project stays useful even if only the first few are implemented well.

1. Detect drift
2. Identify changepoints
3. Flag outliers
4. Compare baseline models
5. Recommend interventions (from the bounded menu below)
6. Validate through backtesting
7. Produce explanation report

## 5. MVP — the minimum complete loop

Load dataset → fit Prophet + Seasonal Naive → run rolling backtest → detect issue →
agent diagnoses and chooses from a small intervention menu → refit → compare before/after
metrics → write explanation report.

## 6. Intervention menu (bounded)

Add / relax changepoints · switch additive ↔ multiplicative seasonality · add weekly /
yearly / custom seasonality · treat a short interval as outlier-contaminated · add known
holidays or event regressors · switch to a different baseline model · retrain on a more
recent window when drift is detected.

Each recommendation must state: **symptom**, **likely cause**, **proposed intervention**,
and the **metric that decides** whether it is accepted.

## 7. Metrics & evaluation

**Forecast metrics:** MAE, RMSE, MASE, WAPE, sMAPE, and prediction-interval coverage.

**Agent-level evals:** diagnostic correctness (precision / recall / FPR on injected ground
truth), tool-use correctness, intervention quality, backtest discipline, forecast outcome
vs. baselines, constraint adherence, explanation quality, and stability across repeated runs.

**Baselines to beat:** Prophet-default (no diagnostic loop), Seasonal Naive, a rule-based
diagnostic loop (no LLM), and an LLM-only diagnosis (no tools — to show why tool grounding
and backtesting matter).