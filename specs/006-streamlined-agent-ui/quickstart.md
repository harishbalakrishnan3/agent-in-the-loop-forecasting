# Quickstart & Validation: Streamlined Agent UI

A run/validation guide proving the feature works end-to-end. Implementation details live in `tasks.md`; design lives in `plan.md`, `data-model.md`, and `contracts/`.

## Prerequisites

```bash
uv sync                       # shared venv from uv.lock (no new deps: streamlit, plotly already present)
cp .env.example .env          # then set ONE provider:
#   ANTHROPIC_API_KEY=...     (preferred when both present)
#   — or — AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / region for Bedrock
```

## Launch the interface

```bash
uv run streamlit run src/ailf/ui/app.py
# opens http://localhost:8501
```

There is exactly one app and one Start control. No drift/changepoint/anomaly vocabulary is shown to the user (FR-001/002). The old surfaces no longer launch (see cleanup check below).

---

## Validate User Story 1 — built-in scenario, live stream, verdict + graph (P1)

1. In the left pane, keep **Dataset = built-in scenario** and pick a scenario from the dropdown (populated from scenario metadata).
2. Leave default models (Visual = Opus 4.8, Reasoning = Sonnet 4.6), default diagnostics/tools, Visual analysis = on.
3. Click **Start**.

**Expect**:
- The right area first shows run metadata (the equivalent CLI command + the resolved config) (FR-016).
- Events stream **incrementally** in `seq` order: `config_resolved → split_built → changepoint_detection → baselines → diagnostics_computed → visual_inspection → decision_iteration/validation_outcome (live, per iteration) → final_evaluation → run_complete` (FR-017/018).
- Each agent decision (tool, params, rationale, expected effect) and each validation outcome (accepted/rejected + reason) appears **as its own expandable entry while the run is still going** — not all at the end (SC-002).
- On completion: a **verdict banner** names the winner by lowest test MAE with the margin over naive (FR-023), and an **interactive Plotly graph** renders with the three forecasts + actuals, distinct train/val/test shading, changepoint markers, zoom/pan/hover, and a legend (FR-024/025/026).

---

## Validate User Story 2 — custom CSV (P2)

1. Switch **Dataset = custom CSV**. Confirm the help text states the required columns `ds` (time) and `y` (value) (FR-008).
2. Upload a two-column CSV. Set splits to `0.8 / 0.1 / 0.1`. Optionally adjust seasonal period / changepoints (advanced).
3. Click **Start** → same live experience and final verdict + graph as Story 1 (FR-024).

**Negative checks (must block before any run starts)**:
- Splits that don't sum to 1 → Start blocked / inputs flagged (FR-009, SC-003).
- A file missing `ds` or `y` → clear contract message, no run (FR-010, SC-003).

---

## Validate User Story 3 — configure the agent's instruments (P2)

1. Disable several of the 13 diagnostics and one or more tools; toggle Visual analysis **off**.
2. Start a run and inspect the stream:
   - `config_resolved` payload lists the disabled diagnostics under `hidden_diagnostics` and disabled tools under `removed_tools`.
   - `diagnostics_computed` exposes only the enabled diagnostics; `decision_iteration.menu` omits the disabled tools (the `full_history_default` fallback always remains) (FR-013/014, SC-004).
   - **No** `visual_inspection` event appears (visual node omitted) (FR-015, SC-004).

---

## Validate User Story 4 — one coherent interface (P1)

- Survey the controls: one Start, one pathway, no engine/demo-mode selector, no internal pathway names (FR-001/002/003, SC-008).

**Cleanup check** (FR-033/034/036, SC-007):

```bash
test ! -f src/ailf/pipelines/drift/streamlit_app.py && echo "old Streamlit UI removed"
test ! -f src/ailf/pipelines/drift/llm_reason.py    && echo "demo llm_reason removed"
test ! -f src/ailf/pipelines/drift/fallback.py      && echo "demo fallback removed"
# drift dataset-generation API is KEPT and still green:
uv run pytest tests/pipelines/drift/test_api.py -q
```

---

## Validate provider selection (SC-006)

```bash
# Anthropic only:
ANTHROPIC_API_KEY=sk-... uv run pytest tests/core/config/test_provider_detection.py -q   # detects "anthropic"
# Bedrock only (no Anthropic key): detects "bedrock"
# Neither set: resolve raises ConfigError with a clear message (verified by the same test module)
```

In the UI, launching with neither provider configured shows a clear pre-run error rather than a mid-run failure (FR-029).

---

## Automated test suite (deterministic guards)

```bash
uv run pytest tests/core/events/test_queue_sink.py \
              tests/core/config/test_provider_detection.py \
              tests/pipelines/changepoint/test_event_stream.py \
              tests/pipelines/changepoint/test_custom_split.py \
              tests/ui -q
# Full regression (core must stay green — Principle VII):
uv run pytest -q
```

Key invariants the suite protects:
- `test_event_stream.py`: events remain strictly seq-monotonic, unique, and in causal order **with live `.stream()` emission** and **no double-emit** (research R2).
- `test_queue_sink.py`: `QueueEventSink` is Protocol-conformant and preserves event order.
- `test_custom_split.py`: three fractions honored; sums ≠ 1 rejected; each segment ≥1 row.
- `test_provider_detection.py`: Anthropic-first precedence; neither-set raises `ConfigError`.
- `tests/ui/*`: pure helpers (override build, event view-model incl. `$ref` payloads, verdict math, chart-frame region labeling) verified without launching Streamlit.

## Success = all four stories validated + full `uv run pytest` green.
