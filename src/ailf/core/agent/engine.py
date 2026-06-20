"""LangGraph engine (promoted from ``pocs/changepoint/graph/build.py``).

The ONLY module that imports ``langgraph`` (FR-003) — the serialized boundary (state, events,
trace) carries no LangGraph types. ``build_agent_graph(visual_enabled, ctx)`` compiles either:
- visual ON:  START → visual ∥ diagnostics → decision ↔ validation → final → END
- visual OFF: START → diagnostics → decision ↔ validation → final → END (no visual node)

Node bodies live in ``nodes.py`` and take ``(state, ctx)``; here they are bound to ``ctx`` and the
routing budget.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from ailf.core.agent.nodes import (
    decision_node,
    diagnostics_node,
    final_evaluation_node,
    route_after_validation,
    validation_node,
    visual_inspection_node,
)
from ailf.core.agent.runtime import RunContext
from ailf.core.agent.state import AgentState


def build_agent_graph(ctx: RunContext):
    """Compile the agent graph for this run, shaped by ``ctx.visual_enabled`` (FR-015)."""
    graph = StateGraph(AgentState)
    graph.add_node("diagnostics", lambda s: diagnostics_node(s, ctx))
    graph.add_node("decision", lambda s: decision_node(s, ctx))
    graph.add_node("validation", lambda s: validation_node(s, ctx))
    graph.add_node("final_evaluation", lambda s: final_evaluation_node(s, ctx))

    if ctx.visual_enabled:
        graph.add_node("visual_inspection", lambda s: visual_inspection_node(s, ctx))
        graph.add_edge(START, "visual_inspection")
        graph.add_edge(START, "diagnostics")
        graph.add_edge("visual_inspection", "decision")
        graph.add_edge("diagnostics", "decision")
    else:
        # Linear: the visual node is OMITTED entirely (no image produced/sent — SC-006).
        graph.add_edge(START, "diagnostics")
        graph.add_edge("diagnostics", "decision")

    graph.add_edge("decision", "validation")
    graph.add_conditional_edges(
        "validation",
        partial(route_after_validation, max_iterations=ctx.max_iterations),
        {"decision": "decision", "final_evaluation": "final_evaluation"},
    )
    graph.add_edge("final_evaluation", END)
    return graph.compile()
