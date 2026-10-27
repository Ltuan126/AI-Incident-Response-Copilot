"""LangGraph node: correlate signals across metrics, logs, and deployments."""

from typing import Any

from apps.worker.agent.state import IncidentAgentState


def correlate_evidence_node(state: IncidentAgentState) -> dict[str, Any]:
    """Correlate metrics, logs, and deployment events to identify causal patterns."""
    evidence_records = state.get("evidence_records", [])

    metrics = [e for e in evidence_records if e.get("source_type") == "metric"]
    logs = [e for e in evidence_records if e.get("source_type") == "log"]
    deployments = [e for e in evidence_records if e.get("source_type") == "deployment"]
    runbooks = [e for e in evidence_records if e.get("source_type") == "runbook"]

    combined_text = " ".join(
        f"{e.get('summary', '')} {str(e.get('raw_data', ''))}".lower() for e in evidence_records
    )

    has_deployment = (
        any(
            bool(e.get("raw_data", {}).get("deployments"))
            or (
                "no deployment" not in e.get("summary", "").lower()
                and "0 records" not in e.get("summary", "").lower()
                and "not found" not in e.get("summary", "").lower()
            )
            for e in deployments
        )
        if deployments
        else False
    )
    has_error_logs = (
        any(
            "timeout" in e.get("summary", "").lower()
            or "error" in e.get("summary", "").lower()
            or "500" in e.get("summary", "").lower()
            for e in logs
        )
        or "database connection timeout" in combined_text
    )
    has_metric_anomaly = (
        any(
            "error rate" in e.get("summary", "").lower()
            or "latency" in e.get("summary", "").lower()
            for e in metrics
        )
        or "error rate" in combined_text
    )

    is_connection_exhaustion = (
        "connection timeout" in combined_text
        or "connection exhaustion" in combined_text
        or "db_connections" in combined_text
    )
    is_high_latency = "latency" in combined_text and not has_error_logs

    signals = {
        "has_deployment": has_deployment,
        "has_error_logs": has_error_logs,
        "has_metric_anomaly": has_metric_anomaly,
        "is_connection_exhaustion": is_connection_exhaustion,
        "is_high_latency": is_high_latency,
        "metrics_count": len(metrics),
        "logs_count": len(logs),
        "deployments_count": len(deployments),
        "runbooks_count": len(runbooks),
    }

    return {"signals": signals}
