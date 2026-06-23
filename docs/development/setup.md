# Development Setup

## Install

```bash
uv sync --extra dev
```

## Run tests

```bash
uv run pytest
```

Run a focused subset:

```bash
uv run pytest tests/pipelines/changepoint
uv run pytest tests/core
uv run pytest tests/ui
```

## Lint

```bash
uv run ruff check .
```

## Repository map

| Path | Purpose |
| --- | --- |
| `src/ailf/core/` | Shared agent, backtest, metrics, events, config, and reporting code. |
| `src/ailf/pipelines/` | Thin use-case-specific pipelines. |
| `src/ailf/ui/` | Streamlit front end. |
| `tests/` | Unit, parity, UI, and pipeline tests. |
| `specs/` | Spec Kit feature directories. |
| `sessions/` | AI session exports for provenance, grouped as `sessions/<iisc-username>/`. |
| `docs/` | Public documentation, diagrams, and project records. |
| `figures/` | Paper-ready generated figures and result tables. |
| `reports/` | Generated run artifacts; bulk outputs are normally ignored. |

## Development principles

- Keep deterministic logic test-first.
- Keep pipeline code thin and domain-specific.
- Treat `src/ailf/core/` as shared infrastructure.
- Keep agent-facing tool choices bounded.
- Preserve hidden-test discipline.
- Write effective run configuration beside each run's artifacts.
