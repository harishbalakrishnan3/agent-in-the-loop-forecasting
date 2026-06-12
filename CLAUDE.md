# Agent-in-the-Loop Forecasting

An LLM agent acting as a *bounded junior forecasting analyst*: it diagnoses time-series
failure modes (drift, changepoints, outliers) with tools, proposes bounded interventions,
validates them via backtesting, and writes an explanation report. It does NOT forecast.

## Read these first
- **What we're building & why** → `SPEC.md`
- **Rules you must follow (principles, quality gates, non-negotiables)** →
  `.specify/memory/constitution.md`
- **Background** → `docs/` (proposal + high-level plan)

## Repository map (pointers — see SPEC.md for the architecture)
- `src/ailf/core/` — SHARED, stable, review-gated: models, backtest, metrics, agent
  (ReAct loop + tool registry), eval (+ LLM judge), reporting, prompts.
- `src/ailf/pipelines/<usecase>/` — THIN, team-owned: dataset generation, the diagnostic
  tool, versioned prompts, and `pipeline.py` wiring the tool into the core loop.
- `pocs/<usecase>/` — throwaway fail-fast exploration; exempt from the quality gates.
  Prove a use-case here before promoting code into a pipeline.
- `tests/core/` and `tests/pipelines/<usecase>/` — tools are tested against synthetic data
  with KNOWN injected ground truth.
- `specs/` — spec-kit feature dirs (`NNN-<name>/{spec,plan,tasks}.md`).
- `sessions/<iisc-username>/` — export your Claude sessions here, in a folder named by
  your IISc username (provenance + grading).
- `data/`, `reports/` — bulk artifacts are gitignored; commit only tiny samples.

## Environment & commands (uv, single workspace)
- `uv sync` — create/update the shared venv from `uv.lock`.
- `uv run pytest` — all tests · `uv run pytest tests/pipelines/drift` — one pipeline.
- `uv add <pkg>` — add a dependency (commit the updated `uv.lock`).
- `uv run python -m ailf.pipelines.<usecase>.pipeline` — run a pipeline end-to-end.
- Copy `.env.example` → `.env` (gitignored). Never commit secrets.

## Workflow (spec-kit, one feature branch per task)
1. `/speckit.specify` a feature → creates `specs/NNN-<name>/` + branch `NNN-<name>`.
2. `/speckit.plan`, then `/speckit.tasks`, then implement on that branch.
3. Keep changes inside your pipeline's directories to avoid cross-team conflicts.
4. PR into `main`. Touching `core/`? Flag it for review and keep core tests green.

## Conventions
- Diagnostic tools: pure, typed functions with a clear contract; tests written first.
- Prompts: `prompts/<name>_vN.md`; never edit a released version — add a new one.
- Seed all synthetic data generation for reproducibility.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
