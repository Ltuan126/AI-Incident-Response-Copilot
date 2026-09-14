"""Deterministic, evidence-grounded analysis used as the first agent MVP.

This analyzer intentionally has no side effects and no model/API dependency. It provides a
reliable baseline while a provider-backed worker is added later.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import (
    AgentRun,
    AgentRunStatus,
    Evidence,
    EvidenceSourceType,
    Hypothesis,
    Incident,
    Recommendation,
    RiskLevel,
)
from apps.api.app.schemas.analysis import (
    AnalysisHypothesisRead,
    AnalysisRecommendationRead,
    AnalyzeIncidentResponse,
    AnalyzeIncidentRequest,
)
from apps.api.app.services.investigation_service import (
    InvalidEvidenceReferenceError,
    InvestigationNotFoundError,
    record_hypothesis,
    record_recommendation,
)


async def analyze_incident(
    session: AsyncSession,
    incident_id: uuid.UUID,
    request: AnalyzeIncidentRequest,
) -> AnalyzeIncidentResponse:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise InvestigationNotFoundError("Incident not found")

    if request.agent_run_id is not None:
        run = await session.get(AgentRun, request.agent_run_id)
        if run is None or run.incident_id != incident_id:
            raise InvestigationNotFoundError("Agent run not found for this incident")
    else:
        run = await session.scalar(
            select(AgentRun)
            .where(AgentRun.incident_id == incident_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
            .limit(1)
        )
        if run is None:
            raise InvestigationNotFoundError("Collect evidence before analyzing the incident")

    evidence = list(
        await session.scalars(
            select(Evidence)
            .where(Evidence.agent_run_id == run.id)
            .order_by(Evidence.collected_at.asc(), Evidence.id.asc())
        )
    )
    if not evidence:
        run.status = AgentRunStatus.INSUFFICIENT_EVIDENCE
        run.finished_at = datetime.now(UTC)
        run.error_message = "No evidence was collected for this run."
        await session.flush()
        return AnalyzeIncidentResponse(
            incident_id=incident_id,
            agent_run_id=run.id,
            status=run.status,
            summary="Insufficient evidence to determine a reliable root cause.",
            hypothesis=None,
            recommendation=None,
            evidence_count=0,
            analyzed_at=run.finished_at,
        )

    run.status = AgentRunStatus.RUNNING
    run.started_at = run.started_at or datetime.now(UTC)
    run.provider = "deterministic"
    run.model_name = "evidence-rules-v1"
    run.prompt_version = "analysis-rules-v1"

    metric_ids = [item.id for item in evidence if item.source_type == EvidenceSourceType.METRIC]
    log_ids = [item.id for item in evidence if item.source_type == EvidenceSourceType.LOG]
    deployment_ids = [
        item.id for item in evidence if item.source_type == EvidenceSourceType.DEPLOYMENT
    ]
    text = " ".join(
        f"{item.summary} {item.query}".lower() for item in evidence
    )
    deployment_regression = bool(deployment_ids) and (
        bool(metric_ids) or bool(log_ids) or "error" in text or "timeout" in text
    )
    cited_ids = list(dict.fromkeys(deployment_ids + metric_ids + log_ids))
    if not deployment_regression or len(cited_ids) < 2:
        run.status = AgentRunStatus.INSUFFICIENT_EVIDENCE
        run.finished_at = datetime.now(UTC)
        run.error_message = "Evidence did not support a cited root-cause hypothesis."
        await session.flush()
        return AnalyzeIncidentResponse(
            incident_id=incident_id,
            agent_run_id=run.id,
            status=run.status,
            summary="Insufficient evidence to determine a reliable root cause.",
            hypothesis=None,
            recommendation=None,
            evidence_count=len(evidence),
            analyzed_at=run.finished_at,
        )

    confidence = min(0.95, 0.55 + 0.1 * len(cited_ids))
    if confidence < request.min_confidence:
        run.status = AgentRunStatus.INSUFFICIENT_EVIDENCE
        run.finished_at = datetime.now(UTC)
        run.error_message = "Computed confidence is below the requested threshold."
        await session.flush()
        return AnalyzeIncidentResponse(
            incident_id=incident_id,
            agent_run_id=run.id,
            status=run.status,
            summary="Insufficient evidence to meet the requested confidence threshold.",
            hypothesis=None,
            recommendation=None,
            evidence_count=len(evidence),
            analyzed_at=run.finished_at,
        )

    hypothesis = await record_hypothesis(
        session,
        run.id,
        {
            "root_cause": "deployment_regression",
            "summary": (
                "A recent deployment is the most likely cause of the incident: "
                "deployment evidence aligns with metric or log degradation."
            ),
            "confidence": confidence,
            "evidence_ids": cited_ids,
        },
    )
    recommendation = await record_recommendation(
        session,
        run.id,
        {
            "hypothesis_id": hypothesis.id,
            "action_type": "simulated_rollback",
            "parameters": {"incident_id": str(incident_id)},
            "rationale": "Rollback the implicated deployment after human approval, then verify recovery.",
            "risk_level": RiskLevel.MEDIUM,
        },
    )
    run.status = AgentRunStatus.COMPLETED
    run.finished_at = datetime.now(UTC)
    run.error_message = None
    await session.flush()
    return AnalyzeIncidentResponse(
        incident_id=incident_id,
        agent_run_id=run.id,
        status=run.status,
        summary=hypothesis.summary,
        hypothesis=AnalysisHypothesisRead(
            id=hypothesis.id,
            root_cause=hypothesis.root_cause,
            summary=hypothesis.summary,
            confidence=hypothesis.confidence,
            evidence_ids=cited_ids,
        ),
        recommendation=AnalysisRecommendationRead(
            id=recommendation.id,
            action_type=recommendation.action_type,
            parameters=recommendation.parameters,
            rationale=recommendation.rationale,
            risk_level=recommendation.risk_level,
            requires_approval=recommendation.requires_approval,
            status=recommendation.status,
        ),
        evidence_count=len(evidence),
        analyzed_at=run.finished_at,
    )
