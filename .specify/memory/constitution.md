<!--

SYNC IMPACT REPORT
==================

Version change: (template) → 1.0.0
Rationale: Initial ratification — merged constitution derived from the
"Agent-in-the-Loop Forecasting" proposal (docs/agent_in_the_loop_forecasting_proposal.pdf)
and the team's high-level plan (docs/Confluence-high-level-plan-writeup.pdf).

Principles defined:
  I.   Importable Core (Serializable Boundary)
  II.  Test-First for Deterministic Logic (NON-NEGOTIABLE)
  III. Agent Quality Through Golden-Set Evaluation
  IV.  Bounded Interventions, Backtest-Gated (NON-NEGOTIABLE)
  V.   Reproducible & Honest Evaluation
  VI.  Transparent, Explainable Outputs
  VII. Shared Core, Independent Pipelines

Added sections:
  - Technology & Architecture Constraints
  - Development Workflow & Quality Gates
  - Governance

Removed sections: none (initial version)

Templates requiring updates:
  ✅ .specify/memory/constitution.md (this file)
  ⚠ .specify/templates/plan-template.md — verify "Constitution Check" gate references Principles II, IV & VII
  ⚠ .specify/templates/spec-template.md — ensure intervention bounds / eval metrics are capturable as requirements
  ⚠ .specify/templates/tasks-template.md — ensure task categories cover golden-eval + backtest-guardrail work

Follow-up TODOs: none — all placeholders resolved.
-->

# Agent-in-the-Loop Forecasting Constitution

## Core Principles

### I. Importable Core (Serializable Boundary)

All forecasting, diagnostics, agent-reasoning, and evaluation logic MUST live in a
standalone, importable core library whose public API takes and returns plain serializable
data (no front-end or UI types leaking in). Front-ends are optional and, if built, MUST be
thin clients over this core — never a place for business logic, and never a source of
duplicated core behavior.

**Rationale**: The project is both a research deliverable and a reusable tool. A clean,
serializable core boundary keeps the logic testable in isolation and lets any future
consumer (a script, a notebook, an API, or a chat UI) attach cheaply — without committing
the team to building front-ends the proposal treats as optional.

### II. Test-First for Deterministic Logic (NON-NEGOTIABLE)

Every deterministic component — data loading, the forecasting-model layer, drift /
changepoint / outlier diagnostics, metric computation (MAE, RMSE, MASE, WAPE, sMAPE,
PI-coverage), and the backtest guardrail — MUST be built test-first: write a failing
test, confirm it captures intent, watch it fail, implement to green, then refactor. No
deterministic logic merges without tests that fail before and pass after the change.
Diagnostic tools in particular MUST be tested against synthetic series with KNOWN injected
ground truth (precision / recall / false-positive rate).

**Rationale**: These components are the trustworthy substrate the agent and guardrail
stand on. If metrics or backtesting are wrong, every downstream recommendation is wrong.
Strict TDD here is cheap insurance on the parts that must be exactly correct.

### III. Agent Quality Through Golden-Set Evaluation

The LLM analyst layer is NOT unit-TDD'd on exact outputs (it is non-deterministic).
Its quality MUST instead be governed by a versioned golden evaluation set: time series
with known, injected issues plus the expected diagnosis and acceptable intervention(s).
Changes to prompts, models, or agent code MUST be measured against this set, and quality
metrics MUST NOT regress without explicit, documented sign-off. The plumbing *around* the
LLM (parsing, bounds-checking, menu enforcement, error handling) is still covered by
Principle II.

**Rationale**: Asserting exact LLM wording is brittle and meaningless. A labeled golden
set turns "is the agent good?" into a measurable, regression-guarded question while
keeping the deterministic scaffolding under strict tests.

### IV. Bounded Interventions, Backtest-Gated (NON-NEGOTIABLE)

The agent MAY ONLY propose interventions drawn from a fixed, explicit menu, and every
proposal MUST stay within declared numeric bounds. NO proposed intervention is applied to
the chosen forecast unless a rolling backtest demonstrates it does not worsen the selected
primary metric. An intervention that fails or skips backtesting MUST be rejected. The
agent never silently mutates the pipeline; it proposes, the guardrail disposes.

**Rationale**: This is the safety thesis of the project — an LLM is a fallible junior
analyst, so its suggestions must clear an objective, empirical gate before they affect
results. This principle is what makes "agent in the loop" trustworthy rather than dangerous.

### V. Reproducible & Honest Evaluation

Environments MUST be reproducible via `uv` with a committed lockfile; random seeds MUST be
fixed and recorded for any stochastic step. Evaluation MUST always compare against honest
baselines (at minimum Seasonal Naive, plus Prophet / AutoARIMA / ETS as applicable) over
rolling-origin backtests, and MUST report standard metrics rather than cherry-picked ones.
Results, datasets (or their generators), and the exact config that produced them MUST be
recoverable from the repository.

**Rationale**: As a research deliverable, the project's credibility rests on results
others can reproduce and on comparisons that don't flatter the system. Beating a naive
baseline on a fixed protocol is the bar; reproducibility is what makes the claim defensible.

### VI. Transparent, Explainable Outputs

Every run MUST be able to produce a concise, human-readable report covering: the dataset
and forecast horizon, the baseline comparison, detected issues, recommended and
backtest-accepted interventions (with before/after metric deltas), the final
recommendation, and the agent's stated limitations / open questions. The agent's reasoning
and the guardrail's accept/reject decisions MUST be inspectable, not opaque.

**Rationale**: The workflow exists to help a human analyst trust and act on forecasts. An
accepted change that can't be explained, or a decision a human can't audit, defeats the
purpose of keeping a human in the loop.

### VII. Shared Core, Independent Pipelines

The shared core is collectively owned, stable, and review-gated; changes to it MUST keep
all core tests green. Each use-case (drift, changepoint, anomaly) lives in its own pipeline
directory and owns only its dataset generation, diagnostic tool, and prompts. Pipelines
MUST NOT import or depend on one another. Work MUST stay inside a pipeline's own directories
so that parallel teams do not collide.

**Rationale**: Seven people across three sub-teams need to move in parallel without merge
conflicts, while the project must still read as one coherent system. Directory-level
isolation plus a single shared spine delivers both: independence in the leaves, coherence
at the trunk.

## Technology & Architecture Constraints

- **Language & tooling**: Python, managed exclusively with `uv` (single workspace,
  lockfile committed). No competing environment managers in the repo.
- **Forecasting stack**: Prophet and Seasonal Naive for the MVP; AutoARIMA / ETS and
  optional foundation models (Chronos / TimesFM) in the extended version, all behind a
  uniform model interface so they are interchangeable. Time-series handling and dataset
  generation use Darts.
- **Agent / LLM access**: Anthropic Claude is the primary model, accessed through a thin
  internal wrapper (prompt in → validated, menu-constrained proposal out). The wrapper is
  the only place that talks to the provider SDK, so the model is swappable and mockable.
- **Layered architecture** (per the proposal): (1) data, (2) forecasting models,
  (3) diagnostics, (4) LLM analyst, (5) evaluation/guardrail — with the agent confined to
  proposing and the evaluation layer holding final authority (Principle IV).
- **Prompt versioning**: all agent and LLM-judge prompts MUST be versioned. A released
  prompt is never edited in place; a new version is added and referenced by code and reports.
- **POC exemption**: throwaway exploration lives in a dedicated POC area and is exempt from
  the test and quality gates below, to enable fail-fast experimentation. Code is held to the
  full standards only once it is promoted out of the POC area into a pipeline or the core.

## Development Workflow & Quality Gates

- **Spec-driven**: features flow `/speckit.specify` → `/speckit.plan` → `/speckit.tasks` →
  implement, one feature branch per task, PR'd into `main`.
- **Scope phasing**: deliver the MVP loop first (load data → fit Prophet + Seasonal Naive →
  backtest → detect issue → intervention menu → explanation report), then layer on extended
  capabilities. Do not build extended features before the MVP loop is green.
- **Per-change gates** (all MUST pass before merge):
  1. Deterministic logic has failing-then-passing tests (Principle II).
  2. Agent-affecting changes run against the golden eval set with no unjustified
     regression (Principle III).
  3. Any intervention path is backtest-gated and bounds-checked (Principle IV).
  4. The run can still emit a complete explanation report (Principle VI).
  5. `uv` lockfile is current and the environment reproduces (Principle V).
  6. Changes touching the shared core get an extra review and keep core tests green
     (Principle VII).
- **Baselines are mandatory**: no forecasting result is reported without its baseline
  comparison and standard metrics.
- **Determinism discipline**: seeds fixed and logged; the config that produced any reported
  number is committed.
- **Session transparency**: each contributor exports their Claude sessions to the
  repository's session area, in a folder named by their IISc username, for provenance and
  grading.

## Governance

This constitution supersedes ad-hoc practices for this project. All changes — code reviews,
plans, and specs — MUST verify compliance with the principles above, and the two
NON-NEGOTIABLE principles (II: Test-First for Deterministic Logic, IV: Bounded
Interventions, Backtest-Gated) MUST NOT be waived.

**Amendments**: proposed via a documented change to this file, including rationale and,
where behavior changes, a migration note. Amendments take effect once merged.

**Versioning policy** (semantic):

- MAJOR — backward-incompatible removal or redefinition of a principle or governance rule.
- MINOR — a new principle/section or materially expanded guidance.
- PATCH — clarifications, wording, or non-semantic refinements.

**Compliance review**: every plan's "Constitution Check" and every review MUST confirm the
per-change gates above. Complexity or deviation MUST be justified in writing against these
principles; unjustified violations block merge.

**Version**: 1.0.0 | **Ratified**: 2026-06-12 | **Last Amended**: 2026-06-12
