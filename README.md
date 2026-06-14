# Agent-in-the-Loop Forecasting

A bounded LLM agent that acts as a *junior forecasting analyst*: it diagnoses time-series
failure modes (drift, changepoints, outliers) using tools, proposes interventions from a
fixed menu, validates them through backtesting, and writes an explanation report. The
agent does not forecast — models forecast, tools diagnose, the agent reasons and validates.

## Start here

- **What we're building & why** → [`SPEC.md`](SPEC.md)
- **Rules & principles (how we build)** → [`.specify/memory/constitution.md`](.specify/memory/constitution.md)
- **Working in the repo day-to-day** → [`CLAUDE.md`](CLAUDE.md)
- **Background** → [`docs/`](docs/) (proposal + high-level plan), decisions in [`docs/decisions/`](docs/decisions/)

## Layout

```
src/ailf/core/         shared, stable spine (models, backtest, metrics, agent, eval, reporting, prompts)
src/ailf/pipelines/    one thin pipeline per use-case (drift, changepoint, anomaly)
pocs/                  throwaway fail-fast exploration (exempt from quality gates)
tests/                 core + per-pipeline tests
specs/                 spec-kit feature dirs (NNN-<name>/)
sessions/              exported Claude sessions, one folder per IISc username
docs/                  proposal, plan, decisions
```

## Quickstart

```bash
uv sync                 # set up the shared environment from uv.lock
cp .env.example .env    # add your ANTHROPIC_API_KEY
uv run pytest           # run the test suite
```

## Contributing

Spec-driven, one feature branch per task: `/speckit.specify` → `/speckit.plan` →
`/speckit.tasks` → implement → PR into `main`. Keep your changes inside your pipeline's
directories; changes to `src/ailf/core/` get an extra review. See `CLAUDE.md` for details.
