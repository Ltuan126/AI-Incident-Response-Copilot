import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.models.enums import IncidentStatus, Severity


class IncidentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_id: uuid.UUID
    title: str
    description: str | None
    severity: Severity
    status: IncidentStatus
    started_at: datetime
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IncidentListResponse(BaseModel):
    items: list[IncidentRead]
    total: int


class IncidentEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    event_type: str
    message: str
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class IncidentTimelineResponse(BaseModel):
    incident_id: uuid.UUID
    events: list[IncidentEventRead]
