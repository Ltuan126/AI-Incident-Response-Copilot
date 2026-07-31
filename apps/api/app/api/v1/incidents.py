import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from apps.api.app.api.deps import SessionDep
from apps.api.app.models import Incident, IncidentEvent, IncidentStatus, Service, Severity
from apps.api.app.schemas.incident import (
    IncidentEventRead,
    IncidentListResponse,
    IncidentRead,
    IncidentTimelineResponse,
)

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.get("", response_model=IncidentListResponse)
async def list_incidents(
    session: SessionDep,
    service_name: str | None = None,
    incident_status: Annotated[IncidentStatus | None, Query(alias="status")] = None,
    severity: Severity | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IncidentListResponse:
    filters = []
    if service_name is not None:
        service_id = await session.scalar(select(Service.id).where(Service.name == service_name))
        if service_id is None:
            return IncidentListResponse(items=[], total=0)
        filters.append(Incident.service_id == service_id)
    if incident_status is not None:
        filters.append(Incident.status == incident_status)
    if severity is not None:
        filters.append(Incident.severity == severity)

    total = await session.scalar(select(func.count()).select_from(Incident).where(*filters)) or 0
    rows = await session.scalars(
        select(Incident)
        .where(*filters)
        .order_by(Incident.started_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return IncidentListResponse(
        items=[IncidentRead.model_validate(row) for row in rows], total=total
    )


@router.get("/{incident_id}", response_model=IncidentRead)
async def get_incident(incident_id: uuid.UUID, session: SessionDep) -> IncidentRead:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    return IncidentRead.model_validate(incident)


@router.get("/{incident_id}/timeline", response_model=IncidentTimelineResponse)
async def get_timeline(incident_id: uuid.UUID, session: SessionDep) -> IncidentTimelineResponse:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found")
    rows = await session.scalars(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.created_at.asc())
    )
    return IncidentTimelineResponse(
        incident_id=incident_id, events=[IncidentEventRead.model_validate(r) for r in rows]
    )
