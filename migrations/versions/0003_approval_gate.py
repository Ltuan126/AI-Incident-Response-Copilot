"""Add human approval records for proposed remediation actions.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("agent_run_id", sa.Uuid(), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("action_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_status", sa.String(length=16), nullable=True),
        sa.Column("execution_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_approvals_status"
        ),
        sa.CheckConstraint(
            "action_type IN ('simulated_restart', 'simulated_rollback', 'simulated_scale', 'create_incident_note')",
            name="ck_approvals_action_type",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"], ["recommendations.id"], name="fk_approvals_recommendation"
        ),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], name="fk_approvals_agent_run"),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
        sa.UniqueConstraint("recommendation_id", name="uq_approvals_recommendation"),
    )
    op.create_index(
        "ix_approvals_status_created", "approvals", ["status", "created_at", "id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_approvals_status_created", table_name="approvals")
    op.drop_table("approvals")
