"""Human approval boundary for proposed, allow-listed remediation actions."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import (
    AgentRun,
    Approval,
    ApprovalStatus,
    Incident,
    IncidentEvent,
    IncidentEventType,
    IncidentStatus,
    Recommendation,
)
from apps.api.app.schemas.investigation import ApprovalDecision

APPROVAL_TTL = timedelta(minutes=30)
ALLOWED_ACTIONS = frozenset(
    {"simulated_restart", "simulated_rollback", "simulated_scale", "create_incident_note"}
)


class ApprovalError(ValueError):
    """A recommendation cannot enter or change the approval state."""


def action_digest(action_type: str, parameters: dict[str, object], agent_run_id: uuid.UUID) -> str:
    canonical = json.dumps(
        {"action_type": action_type, "parameters": parameters, "agent_run_id": str(agent_run_id)},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def request_approval(session: AsyncSession, recommendation_id: uuid.UUID) -> Approval:
    recommendation = await session.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise ApprovalError("Recommendation not found")
    if recommendation.action_type not in ALLOWED_ACTIONS:
        raise ApprovalError("Action is not allow-listed")
    existing = await session.scalar(
        select(Approval).where(Approval.recommendation_id == recommendation_id)
    )
    if existing is not None:
        return existing
    run = await session.get(AgentRun, recommendation.agent_run_id)
    if run is None:
        raise ApprovalError("Agent run not found")
    approval = Approval(
        recommendation_id=recommendation.id,
        agent_run_id=recommendation.agent_run_id,
        action_type=recommendation.action_type,
        parameters=recommendation.parameters,
        action_hash=action_digest(
            recommendation.action_type, recommendation.parameters, recommendation.agent_run_id
        ),
        expires_at=datetime.now(UTC) + APPROVAL_TTL,
    )
    session.add(approval)
    incident_id = run.incident_id
    incident = await session.get(Incident, incident_id)
    if incident is not None:
        incident.status = IncidentStatus.NEEDS_APPROVAL
        session.add(
            IncidentEvent(
                incident_id=incident_id,
                event_type=IncidentEventType.APPROVAL_REQUESTED,
                message="Remediation recommendation is waiting for human approval.",
                event_metadata={
                    "approval_id": str(approval.id),
                    "recommendation_id": str(recommendation_id),
                },
            )
        )
    await session.flush()
    return approval


async def decide_approval(
    session: AsyncSession, approval_id: uuid.UUID, decision: ApprovalDecision
) -> Approval:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise ApprovalError("Approval not found")
    if approval.status != ApprovalStatus.PENDING:
        raise ApprovalError("Approval has already been decided")
    now = datetime.now(UTC)
    expires_at = approval.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise ApprovalError("Approval has expired")
    if decision.decision not in {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}:
        raise ApprovalError("Decision must be approved or rejected")
    if (
        action_digest(approval.action_type, approval.parameters, approval.agent_run_id)
        != approval.action_hash
    ):
        raise ApprovalError("Approval action integrity check failed")
    approval.status = decision.decision
    approval.decided_by = decision.decided_by
    approval.decision_reason = decision.reason
    approval.decided_at = now
    run = await session.get(AgentRun, approval.agent_run_id)
    if run is not None:
        incident = await session.get(Incident, run.incident_id)
        if incident is not None:
            incident.status = (
                IncidentStatus.APPROVED
                if decision.decision == ApprovalStatus.APPROVED
                else IncidentStatus.REJECTED
            )
            session.add(
                IncidentEvent(
                    incident_id=incident.id,
                    event_type=IncidentEventType.APPROVAL_DECIDED,
                    message=f"Approval {decision.decision.value} by {decision.decided_by}.",
                    event_metadata={"approval_id": str(approval.id)},
                )
            )
    await session.flush()
    return approval
