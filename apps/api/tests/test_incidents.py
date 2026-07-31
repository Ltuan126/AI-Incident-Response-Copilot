from datetime import UTC, datetime

from httpx import AsyncClient

BASE = datetime(2026, 7, 30, 14, 32, tzinfo=UTC)


async def _ingest(client: AsyncClient, service: str, alert_type: str, severity: str) -> str:
    response = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": service,
            "alert_type": alert_type,
            "severity": severity,
            "started_at": BASE.isoformat(),
        },
    )
    return str(response.json()["incident_id"])


async def test_list_incidents_filters_by_service(client: AsyncClient) -> None:
    await _ingest(client, "checkout-api", "high_error_rate", "critical")
    await _ingest(client, "payment-api", "high_latency", "high")

    response = await client.get("/api/v1/incidents", params={"service_name": "checkout-api"})

    assert response.json()["total"] == 1
    assert response.json()["items"][0]["title"].startswith("checkout-api")


async def test_list_incidents_filters_by_severity(client: AsyncClient) -> None:
    await _ingest(client, "checkout-api", "high_error_rate", "critical")
    await _ingest(client, "payment-api", "high_latency", "high")

    response = await client.get("/api/v1/incidents", params={"severity": "high"})

    assert response.json()["total"] == 1


async def test_list_incidents_unknown_service_is_empty(client: AsyncClient) -> None:
    response = await client.get("/api/v1/incidents", params={"service_name": "does-not-exist"})

    assert response.json() == {"items": [], "total": 0}


async def test_timeline_starts_with_creation_event(client: AsyncClient) -> None:
    incident_id = await _ingest(client, "checkout-api", "high_error_rate", "critical")

    response = await client.get(f"/api/v1/incidents/{incident_id}/timeline")

    events = response.json()["events"]
    assert events[0]["event_type"] == "incident_created"
    assert "checkout-api" in events[0]["message"]


async def test_unknown_incident_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/incidents/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
