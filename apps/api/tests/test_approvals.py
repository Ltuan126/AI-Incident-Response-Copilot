import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import Incident, Recommendation, RiskLevel, Service
from apps.api.app.schemas.investigation import (
    AgentRunCreate,
    EvidenceCreate,
    HypothesisCreate,
    RecommendationCreate,
)
from apps.api.app.services.investigation_service import (
    create_agent_run,
    record_evidence,
    record_hypothesis,
    record_recommendation,
)


async def make_recommendation(session: AsyncSession) -> Recommendation:
    service = Service(name=f"approval-{uuid.uuid4().hex[:8]}", environment="test")
    session.add(service)
    await session.flush()
    incident = Incident(
        service_id=service.id,
        title="Approval test incident",
        severity="critical",
        status="new",
        started_at=datetime(2026, 9, 17, 12, 0, tzinfo=UTC),
    )
    session.add(incident)
    await session.flush()
    run = await create_agent_run(
        session, incident.id, AgentRunCreate(prompt_version="approval-test-v1")
    )
    evidence = await record_evidence(
        session,
        run.id,
        EvidenceCreate(
            source_type="metric",
            source_name="prometheus",
            query="fixture",
            summary="error rate increased",
            raw_data={"fixture": True},
        ),
    )
    hypothesis = await record_hypothesis(
        session,
        run.id,
        HypothesisCreate(
            root_cause="deployment_regression",
            summary="A deployment caused the regression.",
            confidence=0.9,
            evidence_ids=[evidence.id],
        ),
    )
    recommendation = await record_recommendation(
        session,
        run.id,
        RecommendationCreate(
            hypothesis_id=hypothesis.id,
            action_type="simulated_rollback",
            parameters={"incident_id": str(incident.id)},
            rationale="Rollback the deployment after approval.",
            risk_level=RiskLevel.MEDIUM,
        ),
    )
    await session.commit()
    return recommendation


async def test_request_and_approve_recommendation(
    client: AsyncClient, session: AsyncSession
) -> None:
    recommendation = await make_recommendation(session)
    response = await client.post(f"/api/v1/recommendations/{recommendation.id}/approval")
    assert response.status_code == 201
    approval = response.json()
    assert approval["status"] == "pending"
    assert approval["action_type"] == "simulated_rollback"
    assert len(approval["action_hash"]) == 64

    blocked = await client.post(f"/api/v1/approvals/{approval['id']}/execute")
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "Only approved actions can be executed"

    pending = await client.get("/api/v1/approvals/pending")
    assert pending.status_code == 200
    assert pending.json()["total"] == 1

    decision = await client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"decision": "approved", "decided_by": "tuấn", "reason": "Reviewed evidence"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"


async def test_approval_is_idempotent_and_cannot_be_decided_twice(
    client: AsyncClient, session: AsyncSession
) -> None:
    recommendation = await make_recommendation(session)
    first = await client.post(f"/api/v1/recommendations/{recommendation.id}/approval")
    second = await client.post(f"/api/v1/recommendations/{recommendation.id}/approval")
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    approval_id = first.json()["id"]
    approved = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approved", "decided_by": "reviewer"},
    )
    rejected = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "rejected", "decided_by": "reviewer"},
    )
    assert approved.status_code == 200
    assert rejected.status_code == 400


async def test_invalid_recommendation_returns_not_found(client: AsyncClient) -> None:
    response = await client.post(f"/api/v1/recommendations/{uuid.uuid4()}/approval")
    assert response.status_code == 400
    assert response.json()["detail"] == "Recommendation not found"
