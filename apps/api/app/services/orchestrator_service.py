"""Orchestrator tying evidence collection, analysis, and approval request together."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import Settings
from apps.api.app.models import Incident
from apps.api.app.schemas.analysis import AnalyzeIncidentRequest
from apps.api.app.schemas.collection import CollectEvidenceRequest
from apps.api.app.schemas.investigation import ApprovalRead
from apps.api.app.schemas.orchestrator import (
    InvestigateIncidentRequest,
    InvestigateIncidentResponse,
)
from apps.api.app.services.analysis_service import analyze_incident
from apps.api.app.services.approval_service import request_approval
from apps.api.app.services.collection_service import (
    CollectionNotFoundError,
    collect_incident_evidence,
)


class OrchestrationError(ValueError):
    """An incident investigation could not be completed."""


async def investigate_incident(
    session: AsyncSession,
    incident_id: uuid.UUID,
    request: InvestigateIncidentRequest,
    settings: Settings,
) -> InvestigateIncidentResponse:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise CollectionNotFoundError("Incident not found")

    # Step 1: Collect Evidence
    collection_request = CollectEvidenceRequest(
        lookback_seconds=request.lookback_seconds,
        step_seconds=request.step_seconds,
        log_limit=request.log_limit,
    )
    collection_result = await collect_incident_evidence(
        session, incident_id, collection_request, settings
    )

    # Step 2: Analyze Evidence
    analysis_request = AnalyzeIncidentRequest(
        agent_run_id=collection_result.agent_run_id,
        min_confidence=request.min_confidence,
    )
    analysis_result = await analyze_incident(session, incident_id, analysis_request)

    # Step 3: Automatically Request Approval if a recommendation requires approval
    approval_read: ApprovalRead | None = None
    if analysis_result.recommendation is not None and request.auto_request_approval:
        approval = await request_approval(session, analysis_result.recommendation.id)
        approval_read = ApprovalRead.model_validate(approval)

    await session.refresh(incident)
    return InvestigateIncidentResponse(
        incident_id=incident_id,
        agent_run_id=collection_result.agent_run_id,
        incident_status=incident.status,
        evidence_count=analysis_result.evidence_count,
        hypothesis=analysis_result.hypothesis,
        recommendation=analysis_result.recommendation,
        approval=approval_read,
        investigated_at=datetime.now(UTC),
    )
