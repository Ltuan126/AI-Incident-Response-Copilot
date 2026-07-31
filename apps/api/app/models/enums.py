from enum import StrEnum


class IncidentStatus(StrEnum):
    NEW = "new"
    COLLECTING_EVIDENCE = "collecting_evidence"
    ANALYZING = "analyzing"
    NEEDS_APPROVAL = "needs_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    RESOLVED = "resolved"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_INCIDENT_STATUSES = frozenset(
    {
        IncidentStatus.RESOLVED,
        IncidentStatus.COMPLETED,
        IncidentStatus.REJECTED,
        IncidentStatus.FAILED,
    }
)


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


class DeploymentStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class IncidentEventType(StrEnum):
    INCIDENT_CREATED = "incident_created"
    ALERT_CORRELATED = "alert_correlated"
    SEVERITY_ESCALATED = "severity_escalated"
    STATUS_CHANGED = "status_changed"
    DEPLOYMENT_RECORDED = "deployment_recorded"
