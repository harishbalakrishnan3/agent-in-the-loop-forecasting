# Getting Started

This page gets the repository running locally. GitHub Pages hosts the documentation only; the
interactive application is a Streamlit server.

## Requirements

- Python 3.11 or newer
- `uv`
- One LLM backend:
  - Anthropic API key, preferred for local runs
  - AWS Bedrock credentials

## Install

```bash
uv sync
cp .env.example .env
```

Then edit `.env` and set one provider.

```ini
# Preferred
ANTHROPIC_API_KEY=sk-ant-...

# Or AWS Bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-west-2
```

If neither provider is configured, agent runs fail fast.

## Run the interactive UI

```bash
uv run streamlit run src/ailf/ui/app.py
```

The Streamlit front end is called ForeCast Explorer. The UI lets you:

- choose a built-in scenario or upload a custom CSV,
- choose visual and reasoning models,
- toggle diagnostics and intervention tools,
- watch the event stream live,
- inspect the final verdict and forecast comparison chart.

## Run a scenario from the CLI

```bash
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality
```

Each run writes artifacts under `reports/changepoint/<run_id>/`:

| Artifact | Purpose |
| --- | --- |
| `metrics.json` | Hidden-test metrics and winner. |
| `agent_trace.json` | Agent decisions, rationales, and gate outcomes. |
| `events.jsonl` | Event stream used by the UI. |
| `effective_config.json` | Fully resolved model, split, toggle, and seed config. |
| `forecast_comparison.csv` | Actuals and forecast series for plotting. |
| `forecast_comparison.png` | Static chart for inspection. |
| `report.md` | Run-level explanation report. |

## Hosted demo

The project report references a hosted Streamlit demo:

[Open ForeCast Explorer](https://agent-in-the-loop-forecasting.streamlit.app/)

If the hosted app is unavailable, sleeping, or access-controlled, use the local Streamlit command
above.

## Custom CSVs

Custom CSVs must have exactly two columns:

| Column | Meaning |
| --- | --- |
| `ds` | Timestamp, sorted chronologically. |
| `y` | Numeric target value. |

The file should not contain duplicate timestamps, missing timestamps, or missing target values. The
UI asks for train, validation, and test fractions that sum to `1.0`.

## Generate paper figures

The repository also includes figure and table helpers used by the report:

```bash
uv run python -m ailf.figures reports/changepoint/<run_id> --out figures/comparison.pdf --width double
uv run python -m ailf.metrics_table reports/changepoint --metric mae --out figures/results_mae.tex
```

These commands use committed run artifacts. They do not need to rerun the agent.
