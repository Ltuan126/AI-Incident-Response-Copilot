import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.models.enums import AgentRunStatus, RiskLevel


class AnalyzeIncidentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    agent_run_id: uuid.UUID | None = None
    min_confidence: float = Field(default=0.6, ge=0, le=1)


class AnalysisHypothesisRead(BaseModel):
    id: uuid.UUID
    root_cause: str
    summary: str
    confidence: float
    evidence_ids: list[uuid.UUID]


class AnalysisRecommendationRead(BaseModel):
    id: uuid.UUID
    action_type: str
    parameters: dict[str, object]
    rationale: str
    risk_level: RiskLevel
    requires_approval: bool
    status: str


class AnalyzeIncidentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    incident_id: uuid.UUID
    agent_run_id: uuid.UUID
    status: AgentRunStatus
    summary: str
    hypothesis: AnalysisHypothesisRead | None = None
    recommendation: AnalysisRecommendationRead | None = None
    evidence_count: int
    analyzed_at: datetime
