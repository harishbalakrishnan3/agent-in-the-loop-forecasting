# Agent-in-the-Loop Forecasting

> An LLM-based agent that acts as a junior forecasting analyst — diagnosing time-series issues, recommending bounded interventions, and validating them through backtesting.

---

## Motivation

Time-series forecasting at scale requires both automation (for throughput) and human judgment (for robustness). Skilled forecasting analysts are expensive and scarce. This project modernizes Facebook Prophet's analyst-in-the-loop workflow by replacing the expert analyst with a **bounded LLM agent** that uses the following tools:

### Agent Tools — Definitions & Examples

#### 1. Drift Detection
**What it is:** Identifies when the statistical properties of a time series (mean, variance, distribution) gradually shift over time, making a model trained on old data unreliable for new data.

**Example:** An e-commerce site averages 1,000 orders/day for a year. Over 3 months, it slowly climbs to 1,500/day — not due to a single event, but a gradual market shift. A model trained on the old regime keeps forecasting ~1,000 and consistently under-predicts.

---

#### 2. Changepoint Detection
**What it is:** Locates specific timestamps where the series undergoes an abrupt structural change — a sudden jump in level, a change in trend slope, or a shift in variance.

**Example:** A SaaS company's daily revenue is growing steadily at 2%/month. On March 15, they launch a new pricing tier and revenue instantly jumps 30%. The date March 15 is a **changepoint**. A model unaware of this break will either over-smooth the jump or produce large errors around it.

---

#### 3. Outlier Detection
**What it is:** Flags isolated observations that are inconsistent with the local behavior of the series — extreme values caused by one-off events, measurement errors, or logging bugs.

**Example:** A sensor records temperature every hour at ~25°C. One reading shows 85°C due to a hardware glitch, then returns to normal. If not flagged, this single spike can distort trend estimation and widen prediction intervals far beyond what's useful.

---

#### 4. Model Comparison
**What it is:** Compares the current forecasting model against simple baselines (Seasonal Naive, AutoARIMA, ETS) to determine whether the model is actually adding value or performing worse than trivial methods.

**Example:** Prophet is configured with custom seasonality and regressors, producing MAE = 12.5. A simple Seasonal Naive (repeat last week's values) achieves MAE = 10.2. The comparison reveals Prophet is over-fitting, and the simpler model is better — the agent should flag this.

---

#### 5. Intervention Recommendation
**What it is:** After diagnosing an issue, the agent proposes a bounded fix from a predefined menu (e.g., add a changepoint, remove outliers, switch model). It does NOT invent arbitrary solutions.

**Example:** The agent detects a changepoint on June 1 and rising forecast error after that date. It recommends: *"Add an explicit changepoint at 2024-06-01 to allow Prophet's trend to reset."* The recommendation includes the symptom, likely cause, proposed fix, and the metric to judge success.

---

#### 6. Backtesting
**What it is:** Simulates historical forecasts by training on past data and predicting known future values. Used as a guardrail — an intervention is accepted **only** if backtesting shows it improves (or at least doesn't worsen) forecast accuracy.

**Example:** The agent recommends adding a changepoint. Backtesting is run: without the changepoint, RMSE = 15.3; with it, RMSE = 11.7. The improvement is confirmed numerically, so the intervention is accepted. If RMSE had worsened, the agent would reject its own recommendation.

---

#### 7. Report Generation
**What it is:** Produces a structured, human-readable summary of the entire diagnostic loop — what was detected, what was tried, what worked, and what remains uncertain.

**Example output:**
> **Issue detected:** Level-shift changepoint on 2024-06-01 (confidence: high).  
> **Evidence:** Forecast error increased 3× after June 1; changepoint detection tool identified break with p < 0.01.  
> **Intervention:** Added explicit changepoint at 2024-06-01.  
> **Result:** RMSE improved from 15.3 → 11.7 on backtest.  
> **Remaining uncertainty:** Cause of the level shift is unknown — recommend human analyst review for business context.

---

### Core Research Question

> Can a bounded LLM agent improve a forecasting pipeline by diagnosing common time-series failure modes, recommending interventions, and validating those interventions through backtesting?

---

## System Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Time-Series    │────▶│  Forecasting     │────▶│  Rolling           │
│  Data           │     │  Models          │     │  Backtests         │
└─────────────────┘     └──────────────────┘     └────────┬───────────┘
                                                          │
                                                          ▼
┌─────────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  Explanation    │◀────│  LLM Junior      │◀────│  Diagnostics       │
│  Report         │     │  Analyst Agent   │     │  Tools             │
└─────────────────┘     └──────────────────┘     └────────────────────┘
                                │
                                ▼
                        ┌──────────────────┐
                        │  Candidate       │
                        │  Interventions   │
                        └──────────────────┘
```

---

## Project Plan

### Phase 0: Foundation Setup

| Task | Owner | Status |
|------|-------|--------|
| GitHub repo & add collaborators | All | ✅ |
| First PR: `CLAUDE.md`, `SPEC.md` | — | ☐ |
| Decide tentative deadlines (fail fast) | All | ☐ |
| Repo structure (evolves with PRs) | All | ☐ |

---

### Phase 1: Datasets

#### 1a. Custom Dataset Generation (using [Darts TimeSeries Generation](https://unit8co.github.io/darts/generated_api/darts.utils.timeseries_generation.html))

| Dataset Type | Owners | Notes |
|---|---|---|
| Drift | Sowmya, Harish | Gradual distribution shift over time |
| Changepoints | Goutham, Meena, Dinesh | Abrupt level/slope changes (easier) |
| Outlier Flagging | Nadhiya, Amudhaval | Isolated anomalous observations |

**Requirements:**
- Configurable knobs/parameters: start time, drift/changepoint parameters, number of outliers, etc.
- Use Darts timeseries generation utilities

#### 1b. Standard/Benchmark Datasets

- Source real-world datasets exhibiting drift, changepoints, and outliers
- Label known ground-truth events for evaluation

---

### Phase 2: Problem Reproduction

| Task | Details |
|------|---------|
| Run baseline models | Prophet, ARIMA, Seasonal Naive (via Darts) on datasets from Phase 1 |
| Reproduce failure modes | Demonstrate where models fail on drift/changepoints/outliers |
| Construct train-test sets | Filter out datasets where issues are not observed |

---

### Phase 3: Agent Development

**Agent Loop:** Diagnosis → Intervention → Backtest → Recommendation

#### 3a. ReAct Agent with Tools

The agent receives a matplotlib graph of historical data + forecast as input.

**Tool Development (with unit tests):**

| # | Tool | Purpose |
|---|------|---------|
| 1 | Drift Detection | Identify if data-generating process or residual distribution has shifted |
| 2 | Changepoint Detection | Locate abrupt changes in trend level or slope |
| 3 | Outlier Flagging | Detect isolated observations distorting model fitting |
| 4 | Baseline Model Comparison | Determine if current model is worse than simple alternatives |
| 5 | Intervention Recommendation | Propose bounded fixes from a predefined menu |
| 6 | Backtesting | Accept only changes improving out-of-sample performance |
| 7 | Report Generation | Summarize evidence, decision, intervention, and uncertainty |

#### 3b. Agent Constraints (Junior Analyst Guardrails)

- Must inspect metrics/plots before recommending changes
- Must describe detected failure mode
- May only choose from predefined intervention menu
- Must rerun backtests after intervention
- Must compare before/after metrics
- Must reject its own recommendation if backtest worsens
- Must separate evidence from speculation in reports

#### Intervention Menu

- Add or relax changepoints
- Switch additive ↔ multiplicative seasonality
- Add weekly, yearly, or custom seasonality
- Treat interval as outlier-contaminated
- Add known holidays or event regressors
- Prefer a different baseline model
- Retrain using a more recent window (drift)

#### 3c. Integration & Verification

- Integrate tools with agent framework
- Verify agent can diagnose issues from train dataset
- Version all prompts

---

### Phase 4: Report Generation

The agent produces a structured report containing:
- Dataset summary
- Selected forecast horizon
- Baseline model comparison
- Detected issues (drift, changepoints, outliers)
- Recommended & tested interventions
- Before/after metrics
- Final model recommendation
- Limitations and open questions for human analyst

---

### Phase 5: Agent Evals

#### 5a. Manual Evaluation
- Failure mode identification
- Human review of diagnostic correctness

#### 5b. LLM Judge Deployment
- Versioned evaluation prompts
- Automated grading of agent outputs

#### Eval Dimensions

| Dimension | What it measures |
|-----------|-----------------|
| Diagnostic correctness | Precision/recall on drift, changepoints, outliers |
| Tool-use correctness | Does agent call required tools before recommending? |
| Intervention quality | Are chosen interventions reasonable from the menu? |
| Backtest discipline | Are interventions accepted only when backtest supports? |
| Forecast outcome | MAE, RMSE, MAPE, sMAPE, prediction interval coverage |
| Constraint adherence | Does agent stay within junior-analyst role? |
| Explanation quality | Clarity of evidence, decision, and uncertainty |
| Stability | Consistency across repeated runs |

#### Comparison Baselines
- Prophet default (no diagnostic loop)
- Seasonal Naive
- Rule-based diagnostic workflow (no LLM)
- LLM-only diagnosis (no tool outputs / no backtesting)

---

### Phase 6 (Optional): Chat Interface / UI

- **Input:** Graph + timeseries data
- **Output:** Report + optional dynamic widget

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Time-series generation & models | [Darts](https://unit8co.github.io/darts/) |
| Forecasting models | Prophet, AutoARIMA, Seasonal Naive, ETS |
| Agent framework | [LangGraph](https://academy.langchain.com/courses/intro-to-langgraph) |
| Observability | LangSmith (optional) |
| LLM | TBD |
| Optional advanced models | Chronos, TimesFM |

---

## Learning Resources

1. **Time-Series Forecasting:** [Forecasting: Principles and Practice (3rd ed)](https://otexts.com/fpp3/)
2. **Agent Framework:** [Intro to LangGraph](https://academy.langchain.com/courses/intro-to-langgraph)
3. **Observability:** [Intro to LangSmith](https://academy.langchain.com/courses/intro-to-langsmith)
4. **Inspiration:** [Thinking with Visual Primitives (DeepSeek)](https://github.com/ailuntx/Thinking-with-Visual-Primitives)

---

## References

1. Taylor & Letham. *Forecasting at Scale.* PeerJ Preprints, 2017.
2. Ansari et al. *Chronos: Learning the Language of Time Series.* 2024.
3. Das et al. *A Decoder-Only Foundation Model for Time-Series Forecasting.* Google Research, 2024.
4. Jin Tan et al. *Are Language Models Actually Useful for Time Series Forecasting?* NeurIPS, 2024.
5. Aera Technology. *Agentic Decision Intelligence for Forecasting.* 2025.
6. TimeCopilot. *The GenAI Forecasting Agent.* 2025.
7. Dynatrace. *Forecast Agent.* 2026.

---

## Team

| Member | Focus Area |
|--------|-----------|
| Sowmya | Drift datasets |
| Harish | Drift datasets, proposal lead |
| Goutham | Changepoint datasets |
| Meena | Changepoint datasets |
| Dinesh | Changepoint datasets |
| Nadhiya | Outlier datasets |
| Amudhaval | Outlier datasets |