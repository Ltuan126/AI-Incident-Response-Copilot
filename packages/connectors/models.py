"""Validated contracts shared by monitoring and deployment connectors."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from apps.api.app.models.enums import EvidenceSourceType


class ConnectorResult(BaseModel):
    """A successful source query ready to be persisted as an Evidence row."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    source_type: EvidenceSourceType
    source_name: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1)
    query_params: dict[str, JsonValue] = Field(default_factory=dict)
    summary: str = Field(min_length=1)
    raw_data: dict[str, JsonValue]
    time_range_start: datetime | None = None
    time_range_end: datetime | None = None
    collected_at: datetime


class ConnectorFailure(BaseModel):
    """Safe, structured error data returned by a failed source query."""

    model_config = ConfigDict(extra="forbid")

    source_type: EvidenceSourceType
    source_name: str = Field(min_length=1, max_length=128)
    error_code: str = Field(min_length=1, max_length=64)
    retryable: bool
    message: str = Field(min_length=1, max_length=512)


ConnectorStatus = Literal["succeeded", "failed"]
