"""LangGraph node: safety check and allowlist enforcement."""

from typing import Any

from apps.worker.agent.policies.safety import ALLOWED_ACTIONS
from apps.worker.agent.state import IncidentAgentState


def safety_check_node(state: IncidentAgentState) -> dict[str, Any]:
    """Verify that proposed actions comply with the allowlist and require approval."""
    recommendation = state.get("selected_recommendation")

    if not recommendation:
        return {
            "safety_check_passed": False,
            "status": "failed",
            "error_message": "Safety check failed: No recommendation provided.",
        }

    action_type = recommendation.get("action_type", "")
    if action_type not in ALLOWED_ACTIONS:
        return {
            "safety_check_passed": False,
            "status": "failed",
            "error_message": f"Safety policy violation: Action '{action_type}' is not allowed.",
            "selected_recommendation": None,
        }

    # Invariant: Mutating actions ALWAYS require human approval
    recommendation["requires_approval"] = True

    return {
        "safety_check_passed": True,
        "requires_approval": True,
        "status": "completed",
    }
