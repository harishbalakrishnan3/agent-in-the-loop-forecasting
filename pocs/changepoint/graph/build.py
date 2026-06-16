"""Compile the agent graph (T028, contracts/graph_nodes.md).

START fans out to visual_inspection and diagnostics concurrently; both join at react_decision.
react_decision ↔ validation loops up to 5 iterations; routes to final_evaluation → END.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from pocs.changepoint.graph.nodes import (
    RunContext,
    make_decision_node,
    make_diagnostics_node,
    make_final_evaluation_node,
    make_validation_node,
    make_visual_node,
    route_after_validation,
)
from pocs.changepoint.graph.state import AgentState


def build_agent_graph(ctx: RunContext):
    graph = StateGraph(AgentState)
    graph.add_node("visual_inspection", make_visual_node(ctx))
    graph.add_node("diagnostics", make_diagnostics_node(ctx))
    graph.add_node("react_decision", make_decision_node(ctx))
    graph.add_node("validation", make_validation_node(ctx))
    graph.add_node("final_evaluation", make_final_evaluation_node(ctx))

    # Concurrent fan-out from START; both feed the decision node (join).
    graph.add_edge(START, "visual_inspection")
    graph.add_edge(START, "diagnostics")
    graph.add_edge("visual_inspection", "react_decision")
    graph.add_edge("diagnostics", "react_decision")

    graph.add_edge("react_decision", "validation")
    graph.add_conditional_edges(
        "validation",
        route_after_validation,
        {"react_decision": "react_decision", "final_evaluation": "final_evaluation"},
    )
    graph.add_edge("final_evaluation", END)

    return graph.compile()
