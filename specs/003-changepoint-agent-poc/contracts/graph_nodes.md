# Contract: LangGraph Nodes & Edges

Graph in `graph/build.py`; state in `graph/state.py`; node fns in `graph/nodes.py`. State is one
serializable TypedDict. Test values (`y[test_idx]`) MUST NOT enter state until
`final_evaluation_node`.

## Edges (FR-015 concurrency)
```
START → visual_inspection_node
START → diagnostics_node
visual_inspection_node → react_decision_node
diagnostics_node       → react_decision_node     # decision waits for BOTH (join)
react_decision_node → validation_node
validation_node → react_decision_node            # conditional: not accepted AND iter < 5
validation_node → final_evaluation_node          # conditional: accepted OR iter == 5
final_evaluation_node → END
```
The two START fan-out branches run concurrently (no shared inputs); the join at
`react_decision_node` guarantees both complete first (FR-015). A completed `visual` result is
therefore always present before any decision (SC-003), regardless of concurrency.

## `visual_inspection_node`  (LLM: VISUAL_MODEL_ID — FR-016)
- **Reads**: `agent_context.png` bytes only.
- **MUST NOT read**: diagnostics, test data, audit fields.
- **Writes**: `state.visual: VisualInspectionResult`.
- **Forbidden**: choosing/naming an intervention. Output schema has no tool field.

## `diagnostics_node`  (deterministic — FR-017)
- **Reads**: `y[train_idx]`, `seasonal_period`, `n_changepoints_to_detect`.
- **No LLM.** Pure function → `state.diagnostics: DiagnosticsBundle` + `state.naive_summary`
  (the naive workflow is computed here or in a helper so the decision node can see it).
- **Writes**: `diagnostics`, `naive_summary`.

## `react_decision_node`  (LLM: REACT_MODEL_ID — FR-018)
- **Reads**: `state.visual`, `state.diagnostics`, `state.naive_summary` (val scores only),
  `state.rejected_signatures`.
- **Writes**: appends an `InterventionProposal` to `state.iterations`.
- **Rules**: returns exactly one tool from the menu within bounds; includes
  `visual_first_rationale` citing visual obs before numerics (SC-003). If proposal is invalid /
  out-of-bounds / a rejected signature / holiday-tool-while-not-recurring → it is added to
  `rejected_signatures` and the node re-prompts (does not advance to validation with a bad
  proposal).

## `validation_node`  (deterministic — FR-019)
- **Reads**: latest proposal, `split` (`fit_idx`/`val_idx` only).
- **Writes**: `val_result` on the current iteration; sets `beat_naive`. If accepted, sets
  `state.accepted`.
- **MUST NOT touch** `test_idx`.
- **Routing**: accepted OR `len(iterations) == 5` → final; else record rejected signature → back
  to decision.

## `final_evaluation_node`  (deterministic — FR-021)
- **Reads**: `state.accepted` else best-val proposal in `state.iterations`; full `train_idx` +
  `test_idx`.
- **Writes**: `state.final_candidate`, `state.final_case`; computes hidden-test metrics for ALL
  THREE methods (full-history Prophet, naive selected, agent final) — first and only place
  `test_idx` is read.
- Triggers artifact writes (or returns data for `run_poc.py` to write).

## Leakage invariants (asserted in code)
1. `agent_context.png` rendered only from `y[train_idx]` (SC-002).
2. No node except `final_evaluation_node` reads `y[test_idx]` or `audit_only`.
3. `state.visual` is populated before any `iterations` entry exists (SC-003).
