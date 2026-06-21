# Contract: agent graph engine, RunContext, node contracts, visual on/off

Owner: `core/agent/{engine,state,nodes,runtime}.py`. Covers FR-003, FR-005, FR-013, FR-014, FR-015,
US1-AC3, US3, SC-002, SC-006. Generalizes the POC `graph/{build,nodes,state}.py`.

## LangGraph confinement (Principle I / FR-003)

`langgraph` is imported **only** in `core/agent/engine.py` (+ its test). `state.py`, `nodes.py`,
`runtime.py`, `registry.py`, the gate, events, and all pipeline modules are import-clean of `langgraph`.
An import-guard test asserts this. The serialized boundary (state, events, trace, artifacts) therefore
carries no LangGraph types.

## `GraphSpec` + `build_agent_graph` (`engine.py`)

`GraphSpec` is a **plain** description the pipeline submits: ordered stage names, edges, and
concurrency-group labels. `build_agent_graph(spec, ctx: RunContext)` compiles it onto a LangGraph
`StateGraph`. Two shapes the changepoint pipeline builds from `EffectiveConfig`:

- **visual on**: `START → visual_inspection`; `START → diagnostics`; both → `decision`;
  `decision → validation`; `validation → decision` (loop, < MAX_ITER and not accepted) |
  `validation → final_evaluation`; `final_evaluation → END`. (`visual ∥ diagnostics` =
  concurrency group `visual_diagnostics`.)
- **visual off**: `START → diagnostics → decision → validation (loop) → final_evaluation → END`.
  The `visual_inspection` node is **omitted entirely** — no `agent_context.png` is produced or sent to
  any model (SC-006).

The executor runs branches such that event emission for the concurrent pair is driven single-threaded
(see `event_contract.md`); no `assert`-based control flow (stripped under `-O`).

## `AgentState` (`state.py`) — POC shape, plain-serializable

Verbatim from the POC TypedDict (`_take_right` reducer for the branch join). Carries `visual` (dict),
`diagnostics` (**filtered** view), `naive_summary`, `iterations`, `rejected_signatures`, `accepted`,
`final_candidate`, `final_case`, `_final_eval`. **Never** carries toggles, the registry, the emitter,
model handles, or the full diagnostics bundle.

## `RunContext` (`runtime.py`) — all non-serializable handles + per-run config

`visual_model`, `decision_model`, `model_ids`, `full_diagnostics` (unfiltered bundle for tools/gate),
`naive_result`, `image_path`, `tool_registry` (`for_run()` projection), `visual_enabled: bool`,
`enabled_diagnostics: frozenset[str]`, `emitter`, `split: ResolvedSplit`, `prompt_ids: dict`. Threaded
to node bodies via closure (POC pattern); never enters `AgentState`.

## Node contracts (`nodes.py`)

| Node | Model | Reads | Writes | Invariants |
|------|-------|-------|--------|------------|
| `visual_inspection` (visual on only) | visual | `image_path` bytes only | `state.visual` | MUST NOT read diagnostics/test/audit; no intervention field |
| `diagnostics` | none | full bundle (ctx) | `state.diagnostics` (**filtered** by `enabled_diagnostics`), `naive_summary` | full bundle always computed; only filtered view exposed (FR-013) |
| `decision` | decision | `state.visual` (if on), `state.diagnostics` (filtered), `naive_summary`, `rejected_signatures`, registry menu | appends `Proposal` to `iterations` | menu from `for_run()` registry (FR-014); rationale visual-first iff `visual_enabled`; visual-first **`StageError`** if visual on and no visual result |
| `validation` | none | latest proposal, `split` (fit/val only) | `val_result`, `beat_naive`, `accepted?` | gate is sole authority; MUST NOT touch test indices; bounds/precondition/not-beat = normal rejection |
| `final_evaluation` | none | accepted else best-val proposal; train + test | `final_candidate`, `final_case`, `_final_eval` | the ONLY place test indices are read |

Routing: `accepted` OR `len(iterations) == MAX_ITER (5)` → `final_evaluation`; else record rejected
signature → `decision`.

## Toggle plumbing

- **Hidden diagnostics** (FR-013): `enabled_diagnostics` (from config) is applied in the `diagnostics`
  node via `to_agent_dict(enabled)`; full bundle stays on `RunContext` for tools/gate. Golden config
  (all 13) ⇒ filtered view byte-identical to the POC (parity guard, SC-001).
- **Removed tools** (FR-014): `tool_registry` is already the `for_run()` projection; the decision menu
  and the gate's allowed-set both derive from it (same fact).
- **Trace** records `visual_analysis_enabled`, `hidden_diagnostics`, `removed_tools`, prompt ids +
  versions, model ids (SC-004/005/012).

## Prompt selection (see also `tool_registry.md`)

`visual_enabled` selects `react_decision_v2.md` (visual-on) vs `react_decision_diagnostics_only_v1.md`
(visual-off); both fill `{{tool_menu}}` from the enabled registry. `visual_inspection_v1.md` is used
only when visual is on. Prompts are pipeline-side; `core/prompts/loader.py` only loads + fills.
