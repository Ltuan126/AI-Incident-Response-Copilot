"""LangGraph node: validate evidence grounding and reject ungrounded citations.

Invariants:
1. Every hypothesis MUST cite at least one evidence ID.
2. Every cited evidence ID MUST exist in the evidence collected for THIS run (no hallucinated IDs).
3. If validation fails, the hypothesis is immediately rejected and status transitions to
   'insufficient_evidence' with summary 'Insufficient evidence to determine a reliable root cause.'
"""

from typing import Any

from apps.worker.agent.state import IncidentAgentState


def validate_grounding_node(state: IncidentAgentState) -> dict[str, Any]:
    """Validate that hypothesis citations strictly match collected evidence."""
    selected_hyp = state.get("selected_hypothesis")
    evidence_records = state.get("evidence_records", [])

    if not selected_hyp:
        return {
            "status": "insufficient_evidence",
            "summary": "Insufficient evidence to determine a reliable root cause.",
            "selected_hypothesis": None,
        }

    cited_ids = selected_hyp.get("evidence_ids", [])
    if not cited_ids:
        # Rejection: No citations
        return {
            "status": "insufficient_evidence",
            "summary": "Insufficient evidence to determine a reliable root cause.",
            "error_message": "Grounding check failed: Hypothesis contains zero evidence citations.",
            "selected_hypothesis": None,
            "hypotheses": [],
        }

    # Set of valid evidence IDs from collected evidence
    collected_id_set = {str(e.get("id")) for e in evidence_records if e.get("id")}

    # Check for hallucinated or cross-run IDs
    invalid_ids = [cid for cid in cited_ids if str(cid) not in collected_id_set]
    if invalid_ids:
        # Rejection: Hallucinated evidence citations detected
        return {
            "status": "insufficient_evidence",
            "summary": "Insufficient evidence to determine a reliable root cause.",
            "error_message": (
                f"Grounding check failed: Hallucinated evidence IDs cited: {invalid_ids}"
            ),
            "selected_hypothesis": None,
            "hypotheses": [],
        }

    # Grounding check passed!
    return {
        "status": "running",
        "grounding_validated": True,
    }
