"""Integration tests verifying POST /investigate executes through LangGraph."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import AgentRun, AgentRunStatus
from apps.api.app.services import collection_service, incident_service
from packages.connectors import ConnectorResult


def make_mock_connectors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakePrometheus:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def query_range(self, *_: object, **__: object) -> ConnectorResult:
            return ConnectorResult(
                source_type="metric",
                source_name="prometheus",
                query="checkout_error_rate_query",
                summary="checkout error rate increased to 35% after deployment",
                raw_data={"result": [{"metric": {"job": "checkout-api"}}]},
                collected_at=datetime.now(UTC),
            )

    class FakeLoki:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def query_range(self, *_: object, **__: object) -> ConnectorResult:
            return ConnectorResult(
                source_type="log",
                source_name="loki",
                query="checkout_log_query",
                summary="database connection timeout in checkout-api",
                raw_data={"streams": []},
                collected_at=datetime.now(UTC),
            )

    monkeypatch.setattr(collection_service, "PrometheusConnector", FakePrometheus)
    monkeypatch.setattr(collection_service, "LokiConnector", FakeLoki)


async def test_investigate_runs_langgraph_and_persists_runbook_evidence(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_mock_connectors(monkeypatch)

    # Ingest Alert
    alert_resp = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": "checkout-api",
            "alert_type": "high_error_rate",
            "severity": "critical",
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    assert alert_resp.status_code == 201
    incident_id = alert_resp.json()["incident_id"]

    # Record deployment event in DB
    service = await incident_service.get_or_create_service(session, "checkout-api")
    await incident_service.record_deployment(
        session,
        service=service,
        version="v1.4.2",
        previous_version="v1.4.1",
        deployed_at=datetime.now(UTC),
        commit_sha="a1b2c3d",
        deployed_by="ci-cd",
    )
    await session.commit()

    # Call POST /investigate
    investigate_resp = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate",
        json={"min_confidence": 0.5, "auto_request_approval": True},
    )
    assert investigate_resp.status_code == 200
    data = investigate_resp.json()

    assert data["incident_status"] == "needs_approval"
    assert data["hypothesis"] is not None
    assert data["hypothesis"]["root_cause"] == "deployment_regression"
    assert len(data["hypothesis"]["evidence_ids"]) >= 3
    assert data["recommendation"] is not None
    assert data["recommendation"]["action_type"] == "simulated_rollback"
    assert data["approval"] is not None
    assert data["approval"]["status"] == "pending"

    # Verify agent run metadata recorded "langgraph" provider
    agent_run_id = uuid.UUID(data["agent_run_id"])
    run = await session.get(AgentRun, agent_run_id)
    assert run is not None
    assert run.provider == "langgraph"
    assert run.model_name == "incident-agent-graph-v1"
    assert run.status == AgentRunStatus.COMPLETED

    # Verify runbook evidence was retrieved and persisted into the Evidence table
    evidence_resp = await client.get(f"/api/v1/incidents/{incident_id}/evidence")
    assert evidence_resp.status_code == 200
    sources = [item["source_type"] for item in evidence_resp.json()["items"]]
    assert "metric" in sources
    assert "log" in sources
    assert "deployment" in sources
    assert "runbook" in sources


async def test_investigate_endpoint_insufficient_evidence_returns_null_hypothesis(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_mock_connectors(monkeypatch)

    # Ingest Alert WITHOUT recording any deployment
    alert_resp = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": "checkout-api",
            "alert_type": "high_error_rate",
            "severity": "critical",
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    incident_id = alert_resp.json()["incident_id"]

    investigate_resp = await client.post(
        f"/api/v1/incidents/{incident_id}/investigate",
        json={"min_confidence": 0.5},
    )
    assert investigate_resp.status_code == 200
    data = investigate_resp.json()

    # Hypothesis & recommendation must be null when evidence is insufficient
    assert data["hypothesis"] is None
    assert data["recommendation"] is None
    assert data["approval"] is None

    # AgentRun status should be insufficient_evidence
    run = await session.get(AgentRun, uuid.UUID(data["agent_run_id"]))
    assert run is not None
    assert run.status == AgentRunStatus.INSUFFICIENT_EVIDENCE
    assert "Insufficient evidence" in (run.error_message or "")
