import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.api.v1 import simulator
from apps.api.app.models import DeploymentEvent
from apps.api.app.schemas.simulator import FaultMode


async def test_health_does_not_touch_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_reports_database_reachable(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_metrics_endpoint_exposes_prometheus_text(client: AsyncClient) -> None:
    await client.get("/health")

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text


async def test_deployment_regression_waits_for_monitoring_to_create_incident(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fault_applied(base_url: str, mode: FaultMode) -> bool:
        return True

    monkeypatch.setattr(simulator, "_apply_fault_mode", fault_applied)
    response = await client.post("/api/v1/simulator/incidents/deployment-regression")

    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] is None
    assert body["alert_id"] is None
    assert body["fault_mode_applied"] is True
    assert body["service_name"] == "checkout-api"
    assert "Prometheus will open" in body["detail"]

    incidents = await client.get("/api/v1/incidents?service_name=checkout-api")
    assert incidents.json()["total"] == 0

    deployment = await session.scalar(select(DeploymentEvent))
    assert deployment is not None
    assert deployment.previous_version == "v1.4.1"
    assert deployment.version == "v1.4.2"
