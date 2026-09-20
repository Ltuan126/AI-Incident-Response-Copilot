"""Execute only approved actions against the bundled demo service."""

import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import Settings
from apps.api.app.models import (
    AgentRun,
    Approval,
    ApprovalStatus,
    Incident,
    IncidentEvent,
    IncidentEventType,
    IncidentStatus,
)
from apps.api.app.services.approval_service import ALLOWED_ACTIONS, action_digest


class RemediationError(ValueError):
    """An approved remediation could not be executed safely."""


async def execute_approval(
    session: AsyncSession, approval_id: uuid.UUID, settings: Settings
) -> Approval:
    approval = await session.get(Approval, approval_id)
    if approval is None:
        raise RemediationError("Approval not found")
    if approval.status != ApprovalStatus.APPROVED:
        raise RemediationError("Only approved actions can be executed")
    if approval.executed_at is not None:
        raise RemediationError("Approval has already been executed")
    if approval.action_type not in ALLOWED_ACTIONS:
        raise RemediationError("Action is not allow-listed")
    if (
        action_digest(approval.action_type, approval.parameters, approval.agent_run_id)
        != approval.action_hash
    ):
        raise RemediationError("Approval action integrity check failed")
    if approval.action_type != "simulated_rollback":
        raise RemediationError("Only simulated_rollback is implemented in this demo")

    incident_id = await session.scalar(
        select(AgentRun.incident_id).where(AgentRun.id == approval.agent_run_id)
    )
    if incident_id is None:
        raise RemediationError("Agent run not found")
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise RemediationError("Incident not found")
    incident.status = IncidentStatus.EXECUTING
    try:
        async with httpx.AsyncClient(
            timeout=settings.connector_timeout_seconds, trust_env=False
        ) as client:
            response = await client.post(
                f"{settings.demo_service_url}/internal/fault-mode", json={"mode": "normal"}
            )
            response.raise_for_status()
            health = await client.get(f"{settings.demo_service_url}/health")
            health.raise_for_status()
            health_state = health.json()
            if health_state.get("status") != "ok" or health_state.get("mode") != "normal":
                raise ValueError("Demo service health verification did not confirm normal mode")
    except (httpx.HTTPError, ValueError) as exc:
        approval.execution_status = "failed"
        approval.execution_error = str(exc)
        approval.executed_at = datetime.now(UTC)
        incident.status = IncidentStatus.FAILED
        await session.flush()
        raise RemediationError(
            "Rollback completed without a healthy recovery verification"
        ) from exc

    approval.execution_status = "succeeded"
    approval.execution_error = None
    approval.executed_at = datetime.now(UTC)
    incident.status = IncidentStatus.RESOLVED
    session.add(
        IncidentEvent(
            incident_id=incident.id,
            event_type=IncidentEventType.REMEDIATION_EXECUTED,
            message="Approved simulated rollback executed and recovery was verified.",
            event_metadata={"approval_id": str(approval.id), "action_type": approval.action_type},
        )
    )
    await session.flush()
    return approval
