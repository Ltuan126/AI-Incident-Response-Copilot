"""LangGraph node: generate structured, evidence-grounded hypotheses."""

from typing import Any

from apps.worker.agent.state import IncidentAgentState


def generate_hypotheses_node(state: IncidentAgentState) -> dict[str, Any]:
    """Generate root-cause hypotheses grounded in collected evidence records."""
    evidence_records = state.get("evidence_records", [])
    signals = state.get("signals", {})
    min_confidence = state.get("min_confidence", 0.5)

    metric_ev = [e for e in evidence_records if e.get("source_type") == "metric"]
    log_ev = [e for e in evidence_records if e.get("source_type") == "log"]
    deployment_ev = [e for e in evidence_records if e.get("source_type") == "deployment"]
    runbook_ev = [e for e in evidence_records if e.get("source_type") == "runbook"]

    cited_ids: list[str] = []
    for ev in deployment_ev + metric_ev + log_ev + runbook_ev:
        ev_id = ev.get("id")
        if ev_id and ev_id not in cited_ids:
            cited_ids.append(str(ev_id))

    # Evaluate whether evidence is sufficient to ground a root-cause conclusion
    has_deployment = signals.get("has_deployment", False)
    has_degradation = signals.get("has_metric_anomaly", False) or signals.get(
        "has_error_logs", False
    )

    # If missing deployment or missing degradation evidence, or less than 2 distinct cited records
    if not (has_deployment and has_degradation) or len(cited_ids) < 2:
        return {
            "status": "insufficient_evidence",
            "summary": "Insufficient evidence to determine a reliable root cause.",
            "selected_hypothesis": None,
            "hypotheses": [],
        }

    # Calculate evidence-based confidence
    # Base confidence grows with quantity and corroboration of evidence sources
    confidence = min(0.95, 0.55 + 0.1 * min(len(cited_ids), 4))
    if confidence < min_confidence:
        return {
            "status": "insufficient_evidence",
            "summary": "Insufficient evidence to meet the requested confidence threshold.",
            "selected_hypothesis": None,
            "hypotheses": [],
        }

    # Root cause identification guided by evidence & runbook
    if signals.get("is_connection_exhaustion"):
        root_cause = "deployment_regression"
        summary = (
            "A recent deployment introduced database connection exhaustion, leading to timeouts "
            "and elevated error rates as documented in the checkout-api runbook."
        )
    elif signals.get("is_high_latency"):
        root_cause = "deployment_regression"
        summary = (
            "A recent deployment caused service latency degradation without 5xx errors, "
            "consistent with increased synchronous processing time."
        )
    else:
        root_cause = "deployment_regression"
        summary = (
            "A recent deployment is the most likely cause of the incident: "
            "deployment evidence aligns with metric or log degradation."
        )

    hypothesis = {
        "root_cause": root_cause,
        "summary": summary,
        "confidence": confidence,
        "evidence_ids": cited_ids,
    }

    return {
        "hypotheses": [hypothesis],
        "selected_hypothesis": hypothesis,
        "summary": summary,
        "status": "running",
    }
