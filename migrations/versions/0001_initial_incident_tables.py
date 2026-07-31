"""Initial incident tables: services, alerts, incidents, timeline and deployments.

Revision ID: 0001
Revises:
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("current_version", sa.String(length=64), nullable=True),
        sa.Column("owner_team", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_services"),
    )
    op.create_index("ix_services_name", "services", ["name"], unique=True)

    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("alert_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.id"], name="fk_alerts_service_id_services"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_alerts"),
        sa.UniqueConstraint("external_id", name="uq_alerts_external_id"),
    )
    op.create_index("ix_alerts_service_id", "alerts", ["service_id"])
    op.create_index("ix_alerts_alert_type", "alerts", ["alert_type"])
    op.create_index("ix_alerts_started_at", "alerts", ["started_at"])

    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.id"], name="fk_incidents_service_id_services"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
    )
    op.create_index("ix_incidents_service_id", "incidents", ["service_id"])
    op.create_index("ix_incidents_status", "incidents", ["status"])
    op.create_index("ix_incidents_started_at", "incidents", ["started_at"])

    op.create_table(
        "incident_alerts",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("alert_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name="fk_incident_alerts_incident_id_incidents"
        ),
        sa.ForeignKeyConstraint(
            ["alert_id"], ["alerts.id"], name="fk_incident_alerts_alert_id_alerts"
        ),
        sa.PrimaryKeyConstraint("incident_id", "alert_id", name="pk_incident_alerts"),
    )

    op.create_table(
        "incident_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name="fk_incident_events_incident_id_incidents"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_incident_events"),
    )
    op.create_index("ix_incident_events_incident_id", "incident_events", ["incident_id"])

    op.create_table(
        "deployment_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("previous_version", sa.String(length=64), nullable=True),
        sa.Column("commit_sha", sa.String(length=64), nullable=True),
        sa.Column("deployed_by", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["service_id"], ["services.id"], name="fk_deployment_events_service_id_services"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_deployment_events"),
    )
    op.create_index("ix_deployment_events_service_id", "deployment_events", ["service_id"])
    op.create_index("ix_deployment_events_deployed_at", "deployment_events", ["deployed_at"])


def downgrade() -> None:
    op.drop_table("deployment_events")
    op.drop_table("incident_events")
    op.drop_table("incident_alerts")
    op.drop_table("incidents")
    op.drop_table("alerts")
    op.drop_table("services")
