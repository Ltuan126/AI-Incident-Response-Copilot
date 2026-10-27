"""LangGraph node: propose remediation actions based on hypothesis and runbooks."""

from typing import Any

from apps.api.app.models.enums import RiskLevel
from apps.worker.agent.state import IncidentAgentState


def propose_actions_node(state: IncidentAgentState) -> dict[str, Any]:
    """Propose structured remediation action adhering to runbook recommendations."""
    selected_hyp = state.get("selected_hypothesis")
    incident_id = state.get("incident_id", "")
    retrieved_runbooks = state.get("retrieved_runbooks", [])

    if not selected_hyp:
        return {
            "selected_recommendation": None,
            "recommendations": [],
        }

    # Reference runbook guidance in rationale
    runbook_title = retrieved_runbooks[0].get("title") if retrieved_runbooks else "standard runbook"
    rationale = (
        f"Rollback the implicated deployment after human approval, then verify recovery "
        f"in accordance with {runbook_title}."
    )

    action_type = "simulated_rollback"
    parameters = {"incident_id": str(incident_id)}

    recommendation = {
        "action_type": action_type,
        "parameters": parameters,
        "rationale": rationale,
        "risk_level": RiskLevel.MEDIUM,
        "requires_approval": True,
        "status": "proposed",
    }

    return {
        "recommendations": [recommendation],
        "selected_recommendation": recommendation,
    }
