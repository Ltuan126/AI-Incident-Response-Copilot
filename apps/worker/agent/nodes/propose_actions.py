"""LangGraph node: propose remediation actions based on hypothesis and LLM hint.

The LLM may have produced a recommendation_hint in generate_hypotheses_node.
This node uses that hint but ALWAYS enforces:
  - requires_approval = True
  - action_type is re-checked against ALLOWED_ACTIONS in safety_check_node next
"""

from typing import Any

from apps.api.app.models.enums import RiskLevel
from apps.worker.agent.policies.safety import ALLOWED_ACTIONS
from apps.worker.agent.state import IncidentAgentState


def propose_actions_node(state: IncidentAgentState) -> dict[str, Any]:
    """Propose a remediation action, preferring the LLM hint when available."""
    selected_hyp = state.get("selected_hypothesis")
    incident_id = state.get("incident_id", "")
    retrieved_runbooks = state.get("retrieved_runbooks", [])

    if not selected_hyp:
        return {
            "selected_recommendation": None,
            "recommendations": [],
        }

    # LLM hint from generate_hypotheses_node (may be None for mock or if LLM skipped)
    llm_hint: dict[str, Any] | None = state.get("llm_recommendation_hint")

    runbook_title = retrieved_runbooks[0].get("title") if retrieved_runbooks else "standard runbook"

    if llm_hint and llm_hint.get("action_type") in ALLOWED_ACTIONS:
        # Use the LLM's proposed action (backend safety_check will still verify)
        action_type: str = llm_hint["action_type"]
        parameters: dict[str, Any] = llm_hint.get("parameters") or {"incident_id": str(incident_id)}
        rationale: str = llm_hint.get("rationale") or (
            f"Rollback the implicated deployment after human approval, then verify recovery "
            f"in accordance with {runbook_title}."
        )
    else:
        # Default deterministic fallback
        action_type = "simulated_rollback"
        parameters = {"incident_id": str(incident_id)}
        rationale = (
            f"Rollback the implicated deployment after human approval, then verify recovery "
            f"in accordance with {runbook_title}."
        )

    recommendation: dict[str, Any] = {
        "action_type": action_type,
        "parameters": parameters,
        "rationale": rationale,
        "risk_level": RiskLevel.MEDIUM,
        # INVARIANT: LLM cannot disable this — it is enforced here AND in safety_check
        "requires_approval": True,
        "status": "proposed",
    }

    return {
        "recommendations": [recommendation],
        "selected_recommendation": recommendation,
    }
