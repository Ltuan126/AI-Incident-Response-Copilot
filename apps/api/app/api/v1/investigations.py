import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select

from apps.api.app.api.deps import SessionDep
from apps.api.app.models import AgentRun, Evidence, EvidenceSourceType, Incident, ToolCall
from apps.api.app.schemas.investigation import (
    AgentRunListResponse,
    AgentRunRead,
    EvidenceListResponse,
    EvidenceRead,
    ToolCallListResponse,
    ToolCallRead,
)

router = APIRouter(tags=["investigations"])
PageLimit = Annotated[int, Query(ge=1, le=200)]
PageOffset = Annotated[int, Query(ge=0)]


async def _require_incident(session: SessionDep, incident_id: uuid.UUID) -> None:
    if await session.get(Incident, incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")


async def _require_run(session: SessionDep, agent_run_id: uuid.UUID) -> AgentRun:
    run = await session.get(AgentRun, agent_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


async def _evidence_page(
    session: SessionDep,
    incident_id: uuid.UUID,
    agent_run_id: uuid.UUID | None,
    source_type: EvidenceSourceType | None,
    source_name: str | None,
    limit: int,
    offset: int,
) -> EvidenceListResponse:
    filters = [Evidence.incident_id == incident_id]
    if agent_run_id is not None:
        filters.append(Evidence.agent_run_id == agent_run_id)
    if source_type is not None:
        filters.append(Evidence.source_type == source_type)
    if source_name is not None:
        filters.append(Evidence.source_name == source_name)
    total = await session.scalar(select(func.count()).select_from(Evidence).where(*filters)) or 0
    rows = await session.scalars(
        select(Evidence)
        .where(*filters)
        .order_by(Evidence.collected_at.asc(), Evidence.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return EvidenceListResponse(
        items=[EvidenceRead.model_validate(row) for row in rows], total=total
    )


@router.get("/incidents/{incident_id}/evidence", response_model=EvidenceListResponse)
async def list_incident_evidence(
    incident_id: uuid.UUID,
    session: SessionDep,
    agent_run_id: uuid.UUID | None = None,
    source_type: EvidenceSourceType | None = None,
    source_name: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> EvidenceListResponse:
    await _require_incident(session, incident_id)
    return await _evidence_page(
        session, incident_id, agent_run_id, source_type, source_name, limit, offset
    )


@router.get("/incidents/{incident_id}/evidence/{evidence_id}", response_model=EvidenceRead)
async def get_incident_evidence(
    incident_id: uuid.UUID, evidence_id: uuid.UUID, session: SessionDep
) -> EvidenceRead:
    await _require_incident(session, incident_id)
    evidence = await session.scalar(
        select(Evidence).where(Evidence.id == evidence_id, Evidence.incident_id == incident_id)
    )
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence not found in this incident")
    return EvidenceRead.model_validate(evidence)


@router.get("/incidents/{incident_id}/agent-runs", response_model=AgentRunListResponse)
async def list_incident_agent_runs(
    incident_id: uuid.UUID, session: SessionDep, limit: PageLimit = 50, offset: PageOffset = 0
) -> AgentRunListResponse:
    await _require_incident(session, incident_id)
    total = (
        await session.scalar(
            select(func.count()).select_from(AgentRun).where(AgentRun.incident_id == incident_id)
        )
        or 0
    )
    rows = await session.scalars(
        select(AgentRun)
        .where(AgentRun.incident_id == incident_id)
        .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return AgentRunListResponse(
        items=[AgentRunRead.model_validate(row) for row in rows], total=total
    )


@router.get("/agent-runs/{agent_run_id}", response_model=AgentRunRead)
async def get_agent_run(agent_run_id: uuid.UUID, session: SessionDep) -> AgentRunRead:
    return AgentRunRead.model_validate(await _require_run(session, agent_run_id))


@router.get("/agent-runs/{agent_run_id}/evidence", response_model=EvidenceListResponse)
async def list_agent_run_evidence(
    agent_run_id: uuid.UUID,
    session: SessionDep,
    source_type: EvidenceSourceType | None = None,
    source_name: str | None = None,
    limit: PageLimit = 50,
    offset: PageOffset = 0,
) -> EvidenceListResponse:
    run = await _require_run(session, agent_run_id)
    return await _evidence_page(
        session, run.incident_id, run.id, source_type, source_name, limit, offset
    )


@router.get("/agent-runs/{agent_run_id}/tool-calls", response_model=ToolCallListResponse)
async def list_tool_calls(
    agent_run_id: uuid.UUID, session: SessionDep, limit: PageLimit = 50, offset: PageOffset = 0
) -> ToolCallListResponse:
    await _require_run(session, agent_run_id)
    total = (
        await session.scalar(
            select(func.count()).select_from(ToolCall).where(ToolCall.agent_run_id == agent_run_id)
        )
        or 0
    )
    rows = await session.scalars(
        select(ToolCall)
        .where(ToolCall.agent_run_id == agent_run_id)
        .order_by(ToolCall.started_at.asc(), ToolCall.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return ToolCallListResponse(
        items=[ToolCallRead.model_validate(row) for row in rows], total=total
    )
