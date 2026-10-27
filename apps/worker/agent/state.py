"""State definition for the LangGraph incident investigation agent."""

from typing import Any

from typing_extensions import TypedDict


class IncidentAgentState(TypedDict, total=False):
    """Execution state passed between LangGraph nodes during incident investigation."""

    incident_id: str
    agent_run_id: str
    service_name: str
    alert_type: str
    severity: str
    started_at: str | None
    lookback_seconds: int
    step_seconds: int
    log_limit: int
    min_confidence: float

    # Raw collected evidence records
    metrics_evidence: list[dict[str, Any]]
    logs_evidence: list[dict[str, Any]]
    deployments_evidence: list[dict[str, Any]]
    runbook_evidence: list[dict[str, Any]]

    # Normalized list of all evidence items (id, source_type, summary, raw_data)
    evidence_records: list[dict[str, Any]]

    # Runbooks retrieved from knowledge base via RAG
    retrieved_runbooks: list[dict[str, Any]]

    # Correlation analysis
    signals: dict[str, Any]

    # Structured outputs
    hypotheses: list[dict[str, Any]]
    selected_hypothesis: dict[str, Any] | None
    recommendations: list[dict[str, Any]]
    selected_recommendation: dict[str, Any] | None

    # Investigation control flow & safety
    status: str  # "running", "completed", "insufficient_evidence", "failed"
    summary: str
    error_message: str | None
    safety_check_passed: bool
    requires_approval: bool

    # Auditing
    tool_calls: list[dict[str, Any]]
    input_tokens: int
    output_tokens: int
