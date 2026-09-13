"""Request and response contracts for the connector collection pass."""

import uuid
from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from apps.api.app.models.enums import AgentRunStatus, EvidenceSourceType, ToolCallStatus


class CollectEvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    lookback_seconds: int = Field(default=300, ge=60, le=86_400)
    end_at: AwareDatetime | None = None
    step_seconds: int = Field(default=15, ge=1, le=300)
    log_limit: int = Field(default=100, ge=1, le=5_000)

    @model_validator(mode="after")
    def validate_end(self) -> "CollectEvidenceRequest":
        if self.end_at is not None and self.end_at > datetime.now(UTC):
            raise ValueError("end_at cannot be in the future")
        return self


class CollectionSourceRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: EvidenceSourceType
    source_name: str
    status: ToolCallStatus
    tool_call_id: uuid.UUID
    evidence_id: uuid.UUID | None = None
    error_code: str | None = None
    retryable: bool | None = None
    message: str | None = None


class CollectEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID
    agent_run_id: uuid.UUID
    status: AgentRunStatus
    time_range_start: datetime
    time_range_end: datetime
    sources: list[CollectionSourceRead]
    evidence_ids: list[uuid.UUID]
