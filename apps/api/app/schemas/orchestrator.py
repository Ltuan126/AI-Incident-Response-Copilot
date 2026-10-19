"""Schemas for full end-to-end incident investigation orchestration."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.models.enums import IncidentStatus
from apps.api.app.schemas.analysis import AnalysisHypothesisRead, AnalysisRecommendationRead
from apps.api.app.schemas.investigation import ApprovalRead


class InvestigateIncidentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    lookback_seconds: int = Field(default=900, ge=60, le=86400)
    step_seconds: int = Field(default=15, ge=1, le=300)
    log_limit: int = Field(default=100, ge=1, le=1000)
    min_confidence: float = Field(default=0.6, ge=0, le=1)
    auto_request_approval: bool = True


class InvestigateIncidentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID
    agent_run_id: uuid.UUID
    incident_status: IncidentStatus
    evidence_count: int
    hypothesis: AnalysisHypothesisRead | None = None
    recommendation: AnalysisRecommendationRead | None = None
    approval: ApprovalRead | None = None
    investigated_at: datetime
