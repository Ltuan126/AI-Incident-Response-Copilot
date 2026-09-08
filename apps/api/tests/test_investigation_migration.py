"""Exercise the actual Alembic migration, not only metadata.create_all."""

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from apps.api.app.models import (
    AgentRun,
    Evidence,
    EvidenceSourceType,
    HypothesisEvidence,
    Incident,
    Recommendation,
    RiskLevel,
    Service,
    Severity,
    ToolCallStatus,
)
from apps.api.app.schemas.investigation import (
    AgentRunCreate,
    EvidenceCreate,
    HypothesisCreate,
    RecommendationCreate,
    ToolCallCreate,
)
from apps.api.app.services import investigation_service as investigations

ROOT = Path(__file__).resolve().parents[3]
INVESTIGATION_TABLES = {
    "agent_runs",
    "tool_calls",
    "evidence",
    "hypotheses",
    "hypothesis_evidence",
    "recommendations",
}


def config_for(connection: Connection) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    config.attributes["connection"] = connection
    config.attributes["configure_logger"] = False
    return config


async def test_upgrade_and_downgrade_preserve_existing_incidents(
    empty_engine: AsyncEngine,
) -> None:
    async with empty_engine.begin() as connection:
        await connection.run_sync(lambda conn: command.upgrade(config_for(conn), "0001"))

    sessions = async_sessionmaker(empty_engine, expire_on_commit=False)
    timestamp = datetime(2026, 9, 8, 12, tzinfo=UTC)
    async with sessions.begin() as session:
        service = Service(name="legacy-checkout-api", current_version="v1.4.1")
        session.add(service)
        await session.flush()
        incident = Incident(
            service_id=service.id,
            title="Incident from step 1",
            severity=Severity.CRITICAL,
            started_at=timestamp,
        )
        session.add(incident)
        await session.flush()
        incident_id = incident.id

    async with empty_engine.begin() as connection:
        await connection.run_sync(lambda conn: command.upgrade(config_for(conn), "head"))
        # Check for forgotten columns, indexes or FKs after migration.
        await connection.run_sync(lambda conn: command.check(config_for(conn)))

    async with sessions.begin() as session:
        saved_incident = await session.get(Incident, incident_id)
        assert saved_incident is not None and saved_incident.title == "Incident from step 1"
        run = await investigations.create_agent_run(
            session, incident_id, AgentRunCreate(prompt_version="migration-test-v1")
        )
        call = await investigations.record_tool_call(
            session,
            run.id,
            ToolCallCreate(
                tool_name="test_fixture",
                status=ToolCallStatus.SUCCEEDED,
                started_at=timestamp,
                finished_at=timestamp,
            ),
        )
        evidence = await investigations.record_evidence(
            session,
            run.id,
            EvidenceCreate(
                source_type=EvidenceSourceType.DEPLOYMENT,
                source_name="test_fixture",
                tool_call_id=call.id,
                query="fixture://migration-test",
                summary="Synthetic migration test evidence",
                raw_data={"version": "v1.4.1"},
                collected_at=timestamp,
            ),
        )
        hypothesis = await investigations.record_hypothesis(
            session,
            run.id,
            HypothesisCreate(
                root_cause="fixture",
                summary="Synthetic conclusion",
                confidence=0.5,
                evidence_ids=[evidence.id],
            ),
        )
        await investigations.record_recommendation(
            session,
            run.id,
            RecommendationCreate(
                hypothesis_id=hypothesis.id,
                action_type="simulated_rollback",
                rationale="Synthetic proposal",
                risk_level=RiskLevel.MEDIUM,
            ),
        )

    async with sessions() as session:
        saved_evidence = await session.get(Evidence, evidence.id)
        assert saved_evidence is not None and saved_evidence.raw_data == {"version": "v1.4.1"}
        assert saved_evidence.created_at is not None  # Server-side timestamp default works.
        assert await session.scalar(select(func.count()).select_from(HypothesisEvidence)) == 1
        assert await session.scalar(select(func.count()).select_from(Recommendation)) == 1

    async with empty_engine.begin() as connection:
        # This only drops investigation data in the disposable test database/schema.
        await connection.run_sync(lambda conn: command.downgrade(config_for(conn), "0001"))
        tables = await connection.run_sync(lambda conn: set(inspect(conn).get_table_names()))
        assert not INVESTIGATION_TABLES.intersection(tables)
        assert "incidents" in tables and "services" in tables

    async with sessions() as session:
        saved_incident = await session.get(Incident, incident_id)
        saved_service = await session.get(Service, service.id)
        assert saved_incident is not None and saved_incident.title == "Incident from step 1"
        assert saved_service is not None and saved_service.current_version == "v1.4.1"

    async with empty_engine.begin() as connection:
        await connection.run_sync(lambda conn: command.upgrade(config_for(conn), "head"))
        await connection.run_sync(lambda conn: command.check(config_for(conn)))

    async with sessions() as session:
        assert await session.scalar(select(func.count()).select_from(AgentRun)) == 0
        assert await session.scalar(select(func.count()).select_from(Incident)) == 1
