# Agent-in-the-Loop Forecasting

> A bounded LLM agent acting as a **junior forecasting analyst**: it diagnoses time-series
> failure modes (drift, changepoints, outliers), proposes bounded interventions, validates them
> with a rolling backtest, and writes an explanation report. **It does not forecast** — models
> forecast, tools diagnose, the agent reasons and explains, and an objective guardrail decides.

Automatic forecasting models fail silently on drift, changepoints, and regime shifts; expert
analysts catch these but don't scale. This project modernizes the analyst-in-the-loop workflow by
replacing the human analyst with an LLM agent that is **confined to proposing** — every suggestion
must clear an empirical backtest gate before it can affect a forecast.

**Research question:** *Can a bounded LLM agent improve a forecasting pipeline by diagnosing common
time-series failure modes, recommending interventions, and validating those interventions through
backtesting?*

**Documentation:** the public project docs are built with MkDocs from [`docs/`](docs/) and deployed
to GitHub Pages.

---

## Architecture (5 layers)

1. **Data** — seeded synthetic generators (via Darts) + standard datasets.
2. **Forecasting models** — Seasonal Naive, Prophet (AutoARIMA/ETS optional) behind a uniform interface.
3. **Diagnostics** — drift / changepoint / outlier detection tools + metric computation.
4. **LLM analyst agent** — a ReAct loop that reads diagnostics, picks a tool, and proposes a bounded intervention.
5. **Evaluation / guardrail** — rolling backtests accept or reject each intervention; the agent never has final authority.

The shared **core** (`src/ailf/core/`) is a use-case-agnostic spine — the agent loop, tool registry,
backtest, metrics, event stream, and reporting. Each **pipeline** (`src/ailf/pipelines/<usecase>/`)
is thin: it supplies a diagnostic tool, a dataset, versioned prompts, and the wiring that plugs them
into the core. The **changepoint** pipeline is the complete, agent-driven reference implementation.

```
┌─────────────── core (shared, review-gated) ───────────────┐
│  agent (ReAct loop) · tool registry · backtest gate ·      │
│  metrics · event stream · reporting · config resolution    │
└────────────────────────────▲──────────────────────────────┘
                             │ supplies tools / diagnostics / prompts / data
        ┌────────────────────┴────────────────────┐
        │      pipelines/changepoint  (complete)   │
        └──────────────────────────────────────────┘
```

---

## Quick start

Requires [`uv`](https://docs.astral.sh/uv/) and Python ≥ 3.11.

```bash
uv sync                       # create the shared venv from uv.lock
cp .env.example .env          # then set ONE LLM provider (see below)
```

**LLM provider** — the backend prefers the **Anthropic API** when `ANTHROPIC_API_KEY` is set, and
otherwise falls back to **AWS Bedrock** when AWS credentials are set. If neither is configured, a run
fails fast with a clear message. Set one in `.env`:

```ini
# Preferred:
ANTHROPIC_API_KEY=sk-ant-...
# — or — AWS Bedrock:
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-west-2
```

### Run the interactive UI

```bash
uv run streamlit run src/ailf/ui/app.py
```

A single, presentation-ready interface: pick a built-in scenario (or upload a custom CSV), choose the
visual and reasoning models, toggle which diagnostics and tools the agent may use, then **Start**. The
right panel **streams the agent's reasoning live** — detection, baselines, each decision and the
guardrail's accept/reject — and ends on a verdict (who won, by hidden-test MAE) plus an interactive
comparison graph with the three forecasts, actuals, train/validation/test regions, and changepoint markers.

### Run a scenario from the CLI

```bash
uv run python -m ailf.pipelines.changepoint.pipeline --scenario level_shift_loses_seasonality
```

Artifacts (metrics, agent trace, report, forecast comparison, event stream) are written under
`reports/changepoint/<run_id>/`.

---

## Custom data

For a custom CSV the file must have **exactly two columns**: `ds` (timestamp) and `y` (numeric value),
sorted chronologically with no duplicate timestamps or missing values. You supply train/validation/test
fractions that sum to 1 (e.g. `0.8 / 0.1 / 0.1`).

---

## Development

```bash
uv run pytest                               # full test suite
uv run pytest tests/pipelines/changepoint   # one pipeline
uv add <pkg>                                # add a dependency (commit the updated uv.lock)
```

The project is **spec-driven** (Spec Kit): features flow `specify → plan → tasks → implement`, one
feature branch per task, PR'd into `main`. Deterministic logic is built test-first; agent behavior is
governed by a golden evaluation set; every intervention is bounds-checked and backtest-gated. Keep
changes inside your pipeline's directories; changes to `src/ailf/core/` get an extra review. See
[`.specify/memory/constitution.md`](.specify/memory/constitution.md) for the non-negotiables.

## Repository map

| Path | What it holds |
|------|---------------|
| `src/ailf/core/` | Shared, stable, review-gated spine: agent loop, registry, backtest, metrics, events, reporting, config |
| `src/ailf/pipelines/<usecase>/` | Thin, team-owned: dataset generation, the diagnostic tool, versioned prompts, pipeline wiring |
| `src/ailf/ui/` | The streamlined Streamlit front-end (a thin client over the changepoint pipeline) |
| `pocs/` | Throwaway fail-fast exploration (exempt from the quality gates) |
| `tests/` | Tools tested against synthetic data with **known injected ground truth** |
| `specs/` | Spec Kit feature directories (`NNN-<name>/{spec,plan,tasks}.md`) |
| `sessions/` | Exported Claude sessions, one folder per IISc username (provenance) |
| `docs/` | Project proposal, high-level plan, decision records |
| `data/`, `reports/` | Bulk artifacts (gitignored; only tiny samples committed) |

## Further reading

- **What we're building & why** → [`SPEC.md`](SPEC.md)
- **How we build (principles & quality gates)** → [`.specify/memory/constitution.md`](.specify/memory/constitution.md)
- **Day-to-day repo operation** → [`CLAUDE.md`](CLAUDE.md)
- **Public docs** → [`docs/`](docs/) (MkDocs source), decisions in [`docs/decisions/`](docs/decisions/)
