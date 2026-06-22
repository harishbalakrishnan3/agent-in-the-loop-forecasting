---
layout: default
title: Agent-in-the-Loop Forecasting
---

# Agent-in-the-Loop Forecasting

**A bounded LLM agent acting as a junior forecasting analyst.** It diagnoses time-series failure
modes — drift, changepoints, outliers — proposes interventions from a fixed menu, validates them
with a rolling backtest, and writes an explanation report. **It does not forecast**: models
forecast, tools diagnose, the agent reasons and explains, and an objective guardrail decides.

> **Research question:** *Can a bounded LLM agent improve a forecasting pipeline by diagnosing
> common time-series failure modes, recommending interventions, and validating those interventions
> through backtesting?*

---

## Why it matters

Automatic forecasting models fail silently on drift, changepoints, and regime shifts; expert
analysts catch these but don't scale. This project modernizes the analyst-in-the-loop workflow by
replacing the human analyst with an LLM agent that is **confined to proposing** — every suggestion
must clear an empirical backtest gate before it can affect a forecast. The agent is a *fallible
junior analyst*; the guardrail, not the model, has final authority.

## How it works — five layers

| Layer | Role |
|------|------|
| **Data** | Seeded synthetic generators (via Darts) + standard datasets |
| **Forecasting models** | Seasonal Naive, Prophet (AutoARIMA/ETS optional) behind one interface |
| **Diagnostics** | Drift / changepoint / outlier detection + metric computation |
| **LLM analyst agent** | A ReAct loop: reads diagnostics, picks a tool, proposes a bounded intervention |
| **Evaluation / guardrail** | Rolling backtests accept or reject each intervention |

A use-case-agnostic **core** holds the agent loop, tool registry, backtest, metrics, live event
stream, and reporting. Each thin **pipeline** plugs in a diagnostic tool, a dataset, and versioned
prompts. The **changepoint** pipeline is the complete, agent-driven reference implementation.

## What the agent run looks like

1. **Detect** structural changes and compute baselines (full-history Prophet, seasonal naive).
2. **Diagnose** — a bundle of signals describes the series (where it shifted, how permanent, recurring events, drift…).
3. **Decide** — the agent picks one bounded intervention (e.g. mark a permanent level shift, model gradual drift, clean a one-off event) and explains its reasoning.
4. **Validate** — the guardrail backtests the proposal on a held-out validation fold; it's accepted only if it strictly beats the naive baseline.
5. **Report** — a verdict on a hidden test fold names the winner (agent vs. baselines) by lowest error, with an interactive comparison chart.

The interactive UI **streams every one of these steps live** and ends on a verdict plus a zoomable
forecast-comparison graph with the train / validation / test regions and changepoint markers labelled.

## Try it

The interactive interface is a [Streamlit](https://streamlit.io) app (a running Python server, so it
can't be hosted on GitHub Pages). To run it locally:

```bash
uv sync
cp .env.example .env          # set ANTHROPIC_API_KEY (preferred) or AWS Bedrock credentials
uv run streamlit run src/ailf/ui/app.py
```

Or run a scenario headless:

```bash
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality
```

## Learn more

- [Repository on GitHub](https://github.com/harishbalakrishnan3/agent-in-the-loop-forecasting)
- [README — setup & usage](https://github.com/harishbalakrishnan3/agent-in-the-loop-forecasting/blob/main/README.md)
- [SPEC — what we're building & why](https://github.com/harishbalakrishnan3/agent-in-the-loop-forecasting/blob/main/SPEC.md)
- [Constitution — principles & quality gates](https://github.com/harishbalakrishnan3/agent-in-the-loop-forecasting/blob/main/.specify/memory/constitution.md)

---

<sub>Built at IISc. Spec-driven (Spec Kit); deterministic logic is test-first, agent behavior is
governed by a golden evaluation set, and every intervention is bounds-checked and backtest-gated.</sub>
