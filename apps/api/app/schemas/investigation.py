import uuid
from datetime import UTC, datetime
from typing import Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from apps.api.app.models.enums import AgentRunStatus, EvidenceSourceType, RiskLevel, ToolCallStatus


class InvestigationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @field_validator(
        "prompt_version",
        "provider",
        "model_name",
        "tool_name",
        "error_message",
        "source_name",
        "query",
        "summary",
        "root_cause",
        "action_type",
        "rationale",
        check_fields=False,
    )
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        # Preserve queries and raw source payloads exactly, including whitespace.
        if value is not None and not value.strip():
            raise ValueError("Text must not be blank")
        return value


class AgentRunCreate(InvestigationInput):
    prompt_version: str = Field(min_length=1, max_length=128)
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    model_name: str | None = Field(default=None, min_length=1, max_length=128)


class ToolCallCreate(InvestigationInput):
    tool_name: str = Field(min_length=1, max_length=128)
    status: ToolCallStatus
    input_payload: dict[str, JsonValue] = Field(default_factory=dict)
    output_payload: dict[str, JsonValue] = Field(default_factory=dict)
    error_message: str | None = Field(default=None, min_length=1)
    started_at: AwareDatetime
    finished_at: AwareDatetime

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        if self.status == ToolCallStatus.FAILED and not self.error_message:
            raise ValueError("A failed tool call needs an error_message")
        if self.status == ToolCallStatus.SUCCEEDED and self.error_message is not None:
            raise ValueError("A successful tool call must not contain an error_message")
        return self


class EvidenceCreate(InvestigationInput):
    tool_call_id: uuid.UUID | None = None
    source_type: EvidenceSourceType
    source_name: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    query_params: dict[str, JsonValue] = Field(default_factory=dict)
    summary: str = Field(min_length=1)
    raw_data: dict[str, JsonValue]
    time_range_start: AwareDatetime | None = None
    time_range_end: AwareDatetime | None = None
    collected_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_time_range(self) -> Self:
        if (self.time_range_start is None) != (self.time_range_end is None):
            raise ValueError("Provide both time range boundaries or neither")
        if (
            self.time_range_start is not None
            and self.time_range_end is not None
            and self.time_range_end < self.time_range_start
        ):
            raise ValueError("time_range_end must not precede time_range_start")
        return self


class HypothesisCreate(InvestigationInput):
    root_cause: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_ids: list[uuid.UUID] = Field(min_length=1)


class RecommendationCreate(InvestigationInput):
    hypothesis_id: uuid.UUID
    action_type: str = Field(min_length=1, max_length=128)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    risk_level: RiskLevel


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    status: AgentRunStatus
    provider: str | None
    model_name: str | None
    prompt_version: str
    started_at: datetime | None
    finished_at: datetime | None
    input_tokens: int
    output_tokens: int
    error_message: str | None
    created_at: datetime


class AgentRunListResponse(BaseModel):
    items: list[AgentRunRead]
    total: int


class ToolCallRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_run_id: uuid.UUID
    tool_name: str
    status: ToolCallStatus
    input_payload: dict[str, JsonValue]
    output_payload: dict[str, JsonValue]
    error_message: str | None
    started_at: datetime
    finished_at: datetime


class ToolCallListResponse(BaseModel):
    items: list[ToolCallRead]
    total: int


class EvidenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    incident_id: uuid.UUID
    agent_run_id: uuid.UUID
    tool_call_id: uuid.UUID | None
    source_type: EvidenceSourceType
    source_name: str
    query: str
    query_params: dict[str, JsonValue]
    summary: str
    raw_data: dict[str, JsonValue]
    time_range_start: datetime | None
    time_range_end: datetime | None
    collected_at: datetime
    created_at: datetime


class EvidenceListResponse(BaseModel):
    items: list[EvidenceRead]
    total: int
