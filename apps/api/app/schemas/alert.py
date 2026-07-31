import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.models.enums import IncidentStatus, Severity


class AlertIngestRequest(BaseModel):
    service_name: str = Field(min_length=1, max_length=128)
    alert_type: str = Field(min_length=1, max_length=64)
    severity: Severity
    started_at: datetime
    labels: dict[str, str] = Field(default_factory=dict)
    observed_value: float | None = None
    threshold: float | None = None
    external_id: str | None = Field(default=None, max_length=128)


class AlertIngestResponse(BaseModel):
    alert_id: uuid.UUID
    incident_id: uuid.UUID
    status: IncidentStatus
    correlated: bool = Field(
        description="True when the alert joined an existing incident instead of opening a new one."
    )


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str | None
    service_id: uuid.UUID
    alert_type: str
    severity: Severity
    started_at: datetime
    resolved_at: datetime | None
    created_at: datetime
