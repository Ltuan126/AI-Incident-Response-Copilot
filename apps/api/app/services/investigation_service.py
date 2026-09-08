"""Internal persistence boundary for the future worker and connectors.

Functions validate ownership and flush, but never commit. The caller owns the transaction;
for example, a tool call and all its evidence can be saved or rolled back together. No public
write endpoint is exposed before authentication and the worker are implemented.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import (
    AgentRun,
    Evidence,
    Hypothesis,
    HypothesisEvidence,
    Incident,
    IncidentEvent,
    IncidentEventType,
    Recommendation,
    ToolCall,
    ToolCallStatus,
)
from apps.api.app.schemas.investigation import (
    AgentRunCreate,
    EvidenceCreate,
    HypothesisCreate,
    RecommendationCreate,
    ToolCallCreate,
)


class InvestigationNotFoundError(ValueError):
    """An incident, run or referenced record is missing."""


class InvalidEvidenceReferenceError(ValueError):
    """A tool/citation is missing, unsuccessful or belongs to another run."""


async def require_agent_run(session: AsyncSession, agent_run_id: uuid.UUID) -> AgentRun:
    run = await session.get(AgentRun, agent_run_id)
    if run is None:
        raise InvestigationNotFoundError("Agent run not found")
    return run


async def create_agent_run(
    session: AsyncSession, incident_id: uuid.UUID, payload: AgentRunCreate
) -> AgentRun:
    if await session.get(Incident, incident_id) is None:
        raise InvestigationNotFoundError("Incident not found")
    run = AgentRun(incident_id=incident_id, **payload.model_dump())
    session.add(run)
    await session.flush()
    session.add(
        IncidentEvent(
            incident_id=incident_id,
            event_type=IncidentEventType.AGENT_RUN_CREATED,
            message="Investigation record created; no analysis has been executed yet.",
            event_metadata={"agent_run_id": str(run.id), "prompt_version": run.prompt_version},
        )
    )
    await session.flush()
    return run


async def record_tool_call(
    session: AsyncSession, agent_run_id: uuid.UUID, payload: ToolCallCreate
) -> ToolCall:
    await require_agent_run(session, agent_run_id)
    call = ToolCall(agent_run_id=agent_run_id, **payload.model_dump())
    session.add(call)
    await session.flush()
    return call


async def record_evidence(
    session: AsyncSession, agent_run_id: uuid.UUID, payload: EvidenceCreate
) -> Evidence:
    run = await require_agent_run(session, agent_run_id)
    if payload.tool_call_id is not None:
        tool_call = await session.get(ToolCall, payload.tool_call_id)
        if (
            tool_call is None
            or tool_call.agent_run_id != agent_run_id
            or tool_call.status != ToolCallStatus.SUCCEEDED
        ):
            raise InvalidEvidenceReferenceError("Evidence needs a successful tool call in this run")
    evidence = Evidence(
        incident_id=run.incident_id, agent_run_id=agent_run_id, **payload.model_dump()
    )
    session.add(evidence)
    await session.flush()
    session.add(
        IncidentEvent(
            incident_id=run.incident_id,
            event_type=IncidentEventType.EVIDENCE_COLLECTED,
            message=f"Stored {payload.source_type.value} evidence from {payload.source_name}.",
            event_metadata={"agent_run_id": str(agent_run_id), "evidence_id": str(evidence.id)},
        )
    )
    await session.flush()
    return evidence


async def record_hypothesis(
    session: AsyncSession, agent_run_id: uuid.UUID, payload: HypothesisCreate
) -> Hypothesis:
    await require_agent_run(session, agent_run_id)
    evidence_ids = set(payload.evidence_ids)
    found_ids = set(
        await session.scalars(
            select(Evidence.id).where(
                Evidence.id.in_(evidence_ids), Evidence.agent_run_id == agent_run_id
            )
        )
    )
    if found_ids != evidence_ids:
        raise InvalidEvidenceReferenceError("Every citation must reference evidence in this run")
    hypothesis = Hypothesis(
        agent_run_id=agent_run_id, **payload.model_dump(exclude={"evidence_ids"})
    )
    session.add(hypothesis)
    await session.flush()
    session.add_all(
        HypothesisEvidence(
            hypothesis_id=hypothesis.id, evidence_id=evidence_id, agent_run_id=agent_run_id
        )
        for evidence_id in evidence_ids
    )
    await session.flush()
    return hypothesis


async def record_recommendation(
    session: AsyncSession, agent_run_id: uuid.UUID, payload: RecommendationCreate
) -> Recommendation:
    await require_agent_run(session, agent_run_id)
    hypothesis = await session.get(Hypothesis, payload.hypothesis_id)
    if hypothesis is None or hypothesis.agent_run_id != agent_run_id:
        raise InvalidEvidenceReferenceError("The hypothesis must belong to this run")
    citation = await session.scalar(
        select(HypothesisEvidence.evidence_id)
        .where(HypothesisEvidence.hypothesis_id == hypothesis.id)
        .limit(1)
    )
    if citation is None:
        raise InvalidEvidenceReferenceError("The hypothesis must have at least one citation")
    recommendation = Recommendation(agent_run_id=agent_run_id, **payload.model_dump())
    session.add(recommendation)
    await session.flush()
    return recommendation
