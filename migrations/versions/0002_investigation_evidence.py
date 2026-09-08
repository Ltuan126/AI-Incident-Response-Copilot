"""Add evidence-grounded investigation records.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'insufficient_evidence')",
            name="ck_agent_runs_status",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_agent_runs_time_range",
        ),
        sa.CheckConstraint("input_tokens >= 0 AND output_tokens >= 0", name="ck_agent_runs_tokens"),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_agent_runs_incident_id_incidents")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint("id", "incident_id", name="uq_agent_runs_id_incident"),
    )
    op.create_index(
        "ix_agent_runs_incident_created",
        "agent_runs",
        ["incident_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "hypotheses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("root_cause", sa.String(length=128), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_hypotheses_confidence"),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], name=op.f("fk_hypotheses_agent_run_id_agent_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hypotheses")),
        sa.UniqueConstraint("id", "agent_run_id", name="uq_hypotheses_id_run"),
    )
    op.create_index(
        op.f("ix_hypotheses_agent_run_id"), "hypotheses", ["agent_run_id"], unique=False
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("input_payload", sa.JSON(), nullable=False),
        sa.Column("output_payload", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('succeeded', 'failed')", name="ck_tool_calls_status"),
        sa.CheckConstraint("finished_at >= started_at", name="ck_tool_calls_time_range"),
        sa.ForeignKeyConstraint(
            ["agent_run_id"], ["agent_runs.id"], name=op.f("fk_tool_calls_agent_run_id_agent_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tool_calls")),
        sa.UniqueConstraint("id", "agent_run_id", name="uq_tool_calls_id_run"),
    )
    op.create_index(
        "ix_tool_calls_run_started",
        "tool_calls",
        ["agent_run_id", "started_at", "id"],
        unique=False,
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("tool_call_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_name", sa.String(length=128), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_params", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=False),
        sa.Column("time_range_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_range_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "source_type IN ('metric', 'log', 'deployment', 'runbook')",
            name="ck_evidence_source_type",
        ),
        sa.CheckConstraint(
            "(time_range_start IS NULL AND time_range_end IS NULL) OR (time_range_start IS NOT NULL AND time_range_end IS NOT NULL AND time_range_end >= time_range_start)",
            name="ck_evidence_time_range",
        ),
        sa.ForeignKeyConstraint(
            ["agent_run_id", "incident_id"],
            ["agent_runs.id", "agent_runs.incident_id"],
            name="fk_evidence_run_incident",
        ),
        sa.ForeignKeyConstraint(
            ["tool_call_id", "agent_run_id"],
            ["tool_calls.id", "tool_calls.agent_run_id"],
            name="fk_evidence_tool_run",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
        sa.UniqueConstraint("id", "agent_run_id", name="uq_evidence_id_run"),
    )
    op.create_index(
        "ix_evidence_incident_collected",
        "evidence",
        ["incident_id", "collected_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_evidence_run_collected",
        "evidence",
        ["agent_run_id", "collected_at", "id"],
        unique=False,
    )
    op.create_index("ix_evidence_tool_call_id", "evidence", ["tool_call_id"], unique=False)
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("hypothesis_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high')", name="ck_recommendations_risk"
        ),
        sa.CheckConstraint("status = 'proposed'", name="ck_recommendations_proposed_only"),
        sa.CheckConstraint("requires_approval = true", name="ck_recommendations_require_approval"),
        sa.ForeignKeyConstraint(
            ["hypothesis_id", "agent_run_id"],
            ["hypotheses.id", "hypotheses.agent_run_id"],
            name="fk_recommendations_hypothesis_run",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
    )
    op.create_index(
        "ix_recommendations_agent_run_id", "recommendations", ["agent_run_id"], unique=False
    )
    op.create_table(
        "hypothesis_evidence",
        sa.Column("hypothesis_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id", "agent_run_id"],
            ["evidence.id", "evidence.agent_run_id"],
            name="fk_hypothesis_evidence_evidence_run",
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id", "agent_run_id"],
            ["hypotheses.id", "hypotheses.agent_run_id"],
            name="fk_hypothesis_evidence_hypothesis_run",
        ),
        sa.PrimaryKeyConstraint(
            "hypothesis_id", "evidence_id", name=op.f("pk_hypothesis_evidence")
        ),
    )
    op.create_index(
        "ix_hypothesis_evidence_evidence_id", "hypothesis_evidence", ["evidence_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_hypothesis_evidence_evidence_id", table_name="hypothesis_evidence")
    op.drop_table("hypothesis_evidence")
    op.drop_index("ix_recommendations_agent_run_id", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_index("ix_evidence_tool_call_id", table_name="evidence")
    op.drop_index("ix_evidence_run_collected", table_name="evidence")
    op.drop_index("ix_evidence_incident_collected", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_tool_calls_run_started", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index(op.f("ix_hypotheses_agent_run_id"), table_name="hypotheses")
    op.drop_table("hypotheses")
    op.drop_index("ix_agent_runs_incident_created", table_name="agent_runs")
    op.drop_table("agent_runs")
