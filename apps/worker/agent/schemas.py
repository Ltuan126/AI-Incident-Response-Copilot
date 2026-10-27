"""Structured output schemas for the incident response investigation agent."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from apps.api.app.models.enums import RiskLevel

ALLOWED_ACTIONS = frozenset(
    {"simulated_restart", "simulated_rollback", "simulated_scale", "create_incident_note"}
)


class HypothesisOutput(BaseModel):
    """Evidence-grounded hypothesis model."""

    model_config = ConfigDict(extra="forbid")

    root_cause: str = Field(min_length=1, max_length=128)
    summary: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[uuid.UUID] = Field(min_length=1)


class RecommendationOutput(BaseModel):
    """Allow-listed remediation recommendation model."""

    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM)
    requires_approval: bool = Field(default=True)


class InvestigationOutput(BaseModel):
    """Complete structured output from an agent investigation run."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "insufficient_evidence", "failed"]
    summary: str = Field(min_length=1)
    hypothesis: HypothesisOutput | None = None
    recommendation: RecommendationOutput | None = None
    evidence_count: int = Field(ge=0)
    cited_evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    runbook_matched: str | None = None
