# 0001 — Shared core + independent pipelines

**Status:** accepted · **Date:** 2026-06-12

## Context

Seven contributors across three sub-teams (drift, changepoint, anomaly) must work in
parallel without merge conflicts, while the repository must read as one coherent system.
The three use-cases share a large substrate: forecasting models, backtesting, metrics, the
ReAct agent loop, eval harness, and LLM judge.

## Decision

- A collectively owned, stable `src/ailf/core/` holds the shared substrate.
- Each use-case lives in a thin, team-owned `src/ailf/pipelines/<usecase>/` (dataset
  generation, diagnostic tool, prompts, pipeline wiring) and must not depend on other
  pipelines.
- A separate `pocs/<usecase>/` area is exempt from quality gates for fail-fast work.
- Claude sessions live under `sessions/<person>/`.
- One `uv` workspace for the whole monorepo; one feature branch per spec-kit task.

See constitution Principle VII and `SPEC.md` §2–§3.

## Consequences

- Teams work in non-overlapping directories → minimal merge conflicts.
- A single shared spine → coherent project, no triplicated logic.
- Cost: changes to `core/` require coordination and an extra review, and must keep core
  tests green.
