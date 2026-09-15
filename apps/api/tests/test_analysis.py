import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import (
    AgentRun,
    AgentRunStatus,
    Evidence,
    Hypothesis,
    HypothesisEvidence,
    Recommendation,
)
from apps.api.app.schemas.investigation import AgentRunCreate, EvidenceCreate
from apps.api.app.services.investigation_service import (
    create_agent_run,
    record_evidence,
)

STARTED_AT = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


async def make_incident(client: AsyncClient, started_at: datetime = STARTED_AT) -> uuid.UUID:
    response = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": "checkout-api",
            "alert_type": "high_error_rate",
            "severity": "critical",
            "started_at": started_at.isoformat(),
        },
    )
    assert response.status_code == 201
    return uuid.UUID(response.json()["incident_id"])


async def make_run(session: AsyncSession, incident_id: uuid.UUID) -> AgentRun:
    return await create_agent_run(
        session, incident_id, AgentRunCreate(prompt_version="analysis-test-v1")
    )


async def add_evidence(
    session: AsyncSession,
    run: AgentRun,
    source_type: str,
    summary: str,
) -> Evidence:
    payload = EvidenceCreate(
        source_type=source_type,
        source_name={
            "metric": "prometheus",
            "log": "loki",
            "deployment": "postgres",
        }[source_type],
        query=f"fixture query for {source_type}",
        summary=summary,
        raw_data={"fixture": True, "source_type": source_type},
        collected_at=STARTED_AT,
    )
    return await record_evidence(session, run.id, payload)


async def make_complete_evidence(session: AsyncSession, run: AgentRun) -> list[Evidence]:
    records = [
        await add_evidence(
            session, run, "deployment", "v1.4.2 deployed shortly before the incident"
        ),
        await add_evidence(
            session, run, "metric", "checkout error rate increased after deployment"
        ),
        await add_evidence(session, run, "log", "database connection timeout in checkout-api"),
    ]
    await session.commit()
    return records


async def test_analyze_creates_cited_hypothesis_and_proposed_action(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident_id = await make_incident(client)
    run = await make_run(session, incident_id)
    evidence = await make_complete_evidence(session, run)

    response = await client.post(
        f"/api/v1/incidents/{incident_id}/analyze",
        json={"agent_run_id": str(run.id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["evidence_count"] == 3
    assert body["hypothesis"]["root_cause"] == "deployment_regression"
    assert body["hypothesis"]["confidence"] == pytest.approx(0.85)
    assert set(body["hypothesis"]["evidence_ids"]) == {str(item.id) for item in evidence}
    assert body["recommendation"]["action_type"] == "simulated_rollback"
    assert body["recommendation"]["status"] == "proposed"
    assert body["recommendation"]["requires_approval"] is True
    assert await session.scalar(select(func.count()).select_from(Hypothesis)) == 1
    assert await session.scalar(select(func.count()).select_from(HypothesisEvidence)) == 3
    assert await session.scalar(select(func.count()).select_from(Recommendation)) == 1
    await session.refresh(run)
    assert run.status == AgentRunStatus.COMPLETED
    assert run.provider == "deterministic"


async def test_analyze_returns_insufficient_evidence_without_deployment(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident_id = await make_incident(client)
    run = await make_run(session, incident_id)
    await add_evidence(session, run, "metric", "error rate increased")
    await add_evidence(session, run, "log", "database connection timeout")
    await session.commit()

    response = await client.post(
        f"/api/v1/incidents/{incident_id}/analyze",
        json={"agent_run_id": str(run.id)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["hypothesis"] is None
    assert body["recommendation"] is None
    assert body["evidence_count"] == 2
    assert await session.scalar(select(func.count()).select_from(Hypothesis)) == 0
    assert await session.scalar(select(func.count()).select_from(Recommendation)) == 0


async def test_analyze_respects_minimum_confidence(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident_id = await make_incident(client)
    run = await make_run(session, incident_id)
    await make_complete_evidence(session, run)

    response = await client.post(
        f"/api/v1/incidents/{incident_id}/analyze",
        json={"agent_run_id": str(run.id), "min_confidence": 0.9},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["hypothesis"] is None
    assert body["recommendation"] is None
    assert await session.scalar(select(func.count()).select_from(Hypothesis)) == 0


async def test_analyze_rejects_run_from_another_incident(
    client: AsyncClient, session: AsyncSession
) -> None:
    first_incident = await make_incident(client)
    second_incident = await make_incident(client, STARTED_AT + timedelta(minutes=10))
    run = await make_run(session, first_incident)
    await session.commit()

    response = await client.post(
        f"/api/v1/incidents/{second_incident}/analyze",
        json={"agent_run_id": str(run.id)},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Agent run not found for this incident"


async def test_analyze_without_run_or_evidence_returns_insufficient(
    client: AsyncClient, session: AsyncSession
) -> None:
    incident_id = await make_incident(client)
    run = await make_run(session, incident_id)
    await session.commit()

    response = await client.post(
        f"/api/v1/incidents/{incident_id}/analyze",
        json={"agent_run_id": str(run.id)},
    )

    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["evidence_count"] == 0
    assert body["hypothesis"] is None
    assert body["recommendation"] is None


async def test_analyze_requires_an_existing_incident(client: AsyncClient) -> None:
    response = await client.post(f"/api/v1/incidents/{uuid.uuid4()}/analyze")

    assert response.status_code == 404
    assert response.json()["detail"] == "Incident not found"
