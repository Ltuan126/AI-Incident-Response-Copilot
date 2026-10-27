"""LangGraph definition for controlled incident investigation."""

from typing import Any, Literal

from langgraph.graph import END, StateGraph

from apps.worker.agent.nodes.correlate_evidence import correlate_evidence_node
from apps.worker.agent.nodes.generate_hypotheses import generate_hypotheses_node
from apps.worker.agent.nodes.propose_actions import propose_actions_node
from apps.worker.agent.nodes.retrieve_runbooks import retrieve_runbooks_node
from apps.worker.agent.nodes.safety_check import safety_check_node
from apps.worker.agent.nodes.validate_grounding import validate_grounding_node
from apps.worker.agent.state import IncidentAgentState


def should_continue_investigation(
    state: IncidentAgentState,
) -> Literal["propose_actions", "end"]:
    """Conditional router: route to action proposal if evidence is valid and grounded."""
    if state.get("status") == "insufficient_evidence" or not state.get("selected_hypothesis"):
        return "end"
    return "propose_actions"


def build_investigation_graph() -> StateGraph[Any, Any, Any, Any]:
    """Build and compile the LangGraph incident investigation workflow."""
    workflow: StateGraph[Any, Any, Any, Any] = StateGraph(IncidentAgentState)

    # Register workflow nodes
    workflow.add_node("retrieve_runbooks", retrieve_runbooks_node)
    workflow.add_node("correlate_evidence", correlate_evidence_node)
    workflow.add_node("generate_hypotheses", generate_hypotheses_node)
    workflow.add_node("validate_grounding", validate_grounding_node)
    workflow.add_node("propose_actions", propose_actions_node)
    workflow.add_node("safety_check", safety_check_node)

    # Set workflow entrypoint
    workflow.set_entry_point("retrieve_runbooks")

    # Connect linear pipeline
    workflow.add_edge("retrieve_runbooks", "correlate_evidence")
    workflow.add_edge("correlate_evidence", "generate_hypotheses")
    workflow.add_edge("generate_hypotheses", "validate_grounding")

    # Conditional routing after evidence validation & grounding check
    workflow.add_conditional_edges(
        "validate_grounding",
        should_continue_investigation,
        {
            "propose_actions": "propose_actions",
            "end": END,
        },
    )

    # Post-validation actions and safety checks
    workflow.add_edge("propose_actions", "safety_check")
    workflow.add_edge("safety_check", END)

    return workflow


compiled_investigation_graph = build_investigation_graph().compile()
