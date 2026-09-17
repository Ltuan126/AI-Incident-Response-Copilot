"""Persistence for investigations; these records do not execute tools or remediation."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base
from apps.api.app.models.enums import (
    AgentRunStatus,
    ApprovalStatus,
    EvidenceSourceType,
    RiskLevel,
    ToolCallStatus,
)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        UniqueConstraint("id", "incident_id", name="uq_agent_runs_id_incident"),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'insufficient_evidence')",
            name="ck_agent_runs_status",
        ),
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_agent_runs_tokens"),
        CheckConstraint(
            "finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_agent_runs_time_range",
        ),
        Index("ix_agent_runs_incident_created", "incident_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"))
    status: Mapped[AgentRunStatus] = mapped_column(String(32), default=AgentRunStatus.PENDING)
    provider: Mapped[str | None] = mapped_column(String(64), default=None)
    model_name: Mapped[str | None] = mapped_column(String(128), default=None)
    prompt_version: Mapped[str] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint("id", "agent_run_id", name="uq_tool_calls_id_run"),
        CheckConstraint("status IN ('succeeded', 'failed')", name="ck_tool_calls_status"),
        CheckConstraint("finished_at >= started_at", name="ck_tool_calls_time_range"),
        Index("ix_tool_calls_run_started", "agent_run_id", "started_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"))
    tool_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[ToolCallStatus] = mapped_column(String(16))
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["agent_run_id", "incident_id"],
            ["agent_runs.id", "agent_runs.incident_id"],
            name="fk_evidence_run_incident",
        ),
        ForeignKeyConstraint(
            ["tool_call_id", "agent_run_id"],
            ["tool_calls.id", "tool_calls.agent_run_id"],
            name="fk_evidence_tool_run",
        ),
        UniqueConstraint("id", "agent_run_id", name="uq_evidence_id_run"),
        CheckConstraint(
            "source_type IN ('metric', 'log', 'deployment', 'runbook')",
            name="ck_evidence_source_type",
        ),
        CheckConstraint(
            "(time_range_start IS NULL AND time_range_end IS NULL) OR "
            "(time_range_start IS NOT NULL AND time_range_end IS NOT NULL "
            "AND time_range_end >= time_range_start)",
            name="ck_evidence_time_range",
        ),
        Index("ix_evidence_incident_collected", "incident_id", "collected_at", "id"),
        Index("ix_evidence_run_collected", "agent_run_id", "collected_at", "id"),
        Index("ix_evidence_tool_call_id", "tool_call_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    incident_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    tool_call_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    source_type: Mapped[EvidenceSourceType] = mapped_column(String(16))
    source_name: Mapped[str] = mapped_column(String(128))
    query: Mapped[str] = mapped_column(Text)
    query_params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[str] = mapped_column(Text)
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    time_range_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    time_range_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Hypothesis(Base):
    __tablename__ = "hypotheses"
    __table_args__ = (
        UniqueConstraint("id", "agent_run_id", name="uq_hypotheses_id_run"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_hypotheses_confidence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    root_cause: Mapped[str] = mapped_column(String(128))
    summary: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class HypothesisEvidence(Base):
    """Real foreign keys keep citations inside the same investigation run."""

    __tablename__ = "hypothesis_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["hypothesis_id", "agent_run_id"],
            ["hypotheses.id", "hypotheses.agent_run_id"],
            name="fk_hypothesis_evidence_hypothesis_run",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "agent_run_id"],
            ["evidence.id", "evidence.agent_run_id"],
            name="fk_hypothesis_evidence_evidence_run",
        ),
        Index("ix_hypothesis_evidence_evidence_id", "evidence_id"),
    )

    hypothesis_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    evidence_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["hypothesis_id", "agent_run_id"],
            ["hypotheses.id", "hypotheses.agent_run_id"],
            name="fk_recommendations_hypothesis_run",
        ),
        CheckConstraint("risk_level IN ('low', 'medium', 'high')", name="ck_recommendations_risk"),
        CheckConstraint("status = 'proposed'", name="ck_recommendations_proposed_only"),
        CheckConstraint("requires_approval = true", name="ck_recommendations_require_approval"),
        Index("ix_recommendations_agent_run_id", "agent_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    agent_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    hypothesis_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action_type: Mapped[str] = mapped_column(String(128))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(Text)
    risk_level: Mapped[RiskLevel] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="proposed")
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Approval(Base):
    """Human decision for one immutable recommendation action."""

    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_approvals_status"
        ),
        CheckConstraint(
            "action_type IN ('simulated_restart', 'simulated_rollback', 'simulated_scale', "
            "'create_incident_note')",
            name="ck_approvals_action_type",
        ),
        UniqueConstraint("recommendation_id", name="uq_approvals_recommendation"),
        Index("ix_approvals_status_created", "status", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("recommendations.id"))
    agent_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_runs.id"))
    action_type: Mapped[str] = mapped_column(String(128))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[ApprovalStatus] = mapped_column(String(16), default=ApprovalStatus.PENDING)
    decided_by: Mapped[str | None] = mapped_column(String(128), default=None)
    decision_reason: Mapped[str | None] = mapped_column(Text, default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    execution_status: Mapped[str | None] = mapped_column(String(16), default=None)
    execution_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
