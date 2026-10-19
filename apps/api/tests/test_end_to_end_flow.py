"""End-to-end integration tests for the incident response copilot flow.

Alert → Evidence Collection → Analysis → Approval Gate →
Simulated Remediation → Recovery Verification → Closure
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import Incident, IncidentStatus
from apps.api.app.services import collection_service, incident_service
from packages.connectors import ConnectorResult


async def get_incident_status(session: AsyncSession, incident_id: uuid.UUID) -> str:
    session.expire_all()
    incident = await session.get(Incident, incident_id)
    assert incident is not None
    return str(incident.status)


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


def make_mock_demo_service(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/fault-mode":
            return httpx.Response(200, json={"status": "ok", "mode": "normal"})
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok", "mode": "normal"})
        return httpx.Response(404)

    real_async_client = httpx.AsyncClient

    def fake_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("apps.api.app.services.remediation_service.httpx.AsyncClient", fake_client)


async def test_step_by_step_end_to_end_incident_flow(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_mock_connectors(monkeypatch)
    make_mock_demo_service(monkeypatch)

    # 1. Alert Ingestion: Alertmanager or simulator sends alert
    alert_response = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": "checkout-api",
            "alert_type": "high_error_rate",
            "severity": "critical",
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    assert alert_response.status_code == 201
    incident_id = uuid.UUID(alert_response.json()["incident_id"])

    # Verify initial incident state
    incident = await session.get(Incident, incident_id)
    assert incident is not None
    assert await get_incident_status(session, incident_id) == IncidentStatus.NEW
    assert incident.resolved_at is None

    # Simulate deployment event in database
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

    # 2. Evidence Collection
    collect_response = await client.post(f"/api/v1/incidents/{incident_id}/collect-evidence")
    assert collect_response.status_code == 201
    collect_data = collect_response.json()
    assert collect_data["status"] == "completed"
    assert len(collect_data["evidence_ids"]) == 3
    run_id = collect_data["agent_run_id"]

    assert await get_incident_status(session, incident_id) == IncidentStatus.COLLECTING_EVIDENCE

    # 3. Evidence-Grounded Analysis
    analyze_response = await client.post(
        f"/api/v1/incidents/{incident_id}/analyze",
        json={"agent_run_id": run_id},
    )
    assert analyze_response.status_code == 200
    analysis_data = analyze_response.json()
    assert analysis_data["status"] == "completed"
    assert analysis_data["hypothesis"]["root_cause"] == "deployment_regression"
    assert len(analysis_data["hypothesis"]["evidence_ids"]) == 3
    assert analysis_data["recommendation"]["action_type"] == "simulated_rollback"
    assert analysis_data["recommendation"]["requires_approval"] is True
    recommendation_id = analysis_data["recommendation"]["id"]

    # 4. Propose Remediation & Human Approval Request
    approval_resp = await client.post(f"/api/v1/recommendations/{recommendation_id}/approval")
    assert approval_resp.status_code == 201
    approval_data = approval_resp.json()
    approval_id = approval_data["id"]
    assert approval_data["status"] == "pending"

    assert await get_incident_status(session, incident_id) == IncidentStatus.NEEDS_APPROVAL

    # Verify pending approvals list
    pending_resp = await client.get("/api/v1/approvals/pending")
    assert pending_resp.status_code == 200
    assert any(item["id"] == approval_id for item in pending_resp.json()["items"])

    # 5. Human Decision: SRE reviews and approves
    decide_resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={
            "decision": "approved",
            "decided_by": "oncall-sre",
            "reason": "Confirmed deployment regression v1.4.2",
        },
    )
    assert decide_resp.status_code == 200
    assert decide_resp.json()["status"] == "approved"

    assert await get_incident_status(session, incident_id) == IncidentStatus.APPROVED

    # 6. Execution of Remediation & Recovery Verification
    execute_resp = await client.post(f"/api/v1/approvals/{approval_id}/execute")
    assert execute_resp.status_code == 200
    assert execute_resp.json()["execution_status"] == "succeeded"

    # 7. Incident Closure & Audit Trail
    await session.refresh(incident)
    assert await get_incident_status(session, incident_id) == IncidentStatus.RESOLVED
    assert incident.resolved_at is not None

    # Verify Timeline Events
    timeline_resp = await client.get(f"/api/v1/incidents/{incident_id}/timeline")
    assert timeline_resp.status_code == 200
    events = timeline_resp.json()["events"]
    event_types = [event["event_type"] for event in events]
    assert "incident_created" in event_types
    assert "evidence_collected" in event_types
    assert "approval_requested" in event_types
    assert "approval_decided" in event_types
    assert "remediation_executed" in event_types


async def test_unified_investigate_pipeline_and_rejection(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_mock_connectors(monkeypatch)
    make_mock_demo_service(monkeypatch)

    # Ingest Alert
    alert_response = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": "checkout-api",
            "alert_type": "high_error_rate",
            "severity": "critical",
            "started_at": datetime.now(UTC).isoformat(),
        },
    )
    incident_id = alert_response.json()["incident_id"]

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

    # Call unified investigate endpoint
    investigate_resp = await client.post(f"/api/v1/incidents/{incident_id}/investigate")
    assert investigate_resp.status_code == 200
    data = investigate_resp.json()
    assert data["incident_status"] == "needs_approval"
    assert data["hypothesis"]["root_cause"] == "deployment_regression"
    assert data["recommendation"]["action_type"] == "simulated_rollback"
    assert data["approval"] is not None
    assert data["approval"]["status"] == "pending"
    approval_id = data["approval"]["id"]

    # Rejection branch: Operator rejects the action
    reject_resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={
            "decision": "rejected",
            "decided_by": "lead-architect",
            "reason": "Fix-forward preferred over rollback",
        },
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    # Execution is blocked
    blocked = await client.post(f"/api/v1/approvals/{approval_id}/execute")
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "Only approved actions can be executed"

    # Incident state is REJECTED
    assert await get_incident_status(session, uuid.UUID(incident_id)) == IncidentStatus.REJECTED
