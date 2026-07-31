from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

BASE = datetime(2026, 7, 30, 14, 32, tzinfo=UTC)


def alert_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "service_name": "checkout-api",
        "alert_type": "high_error_rate",
        "severity": "critical",
        "started_at": BASE.isoformat(),
        "labels": {"environment": "staging", "region": "ap-southeast-1"},
        "observed_value": 0.35,
        "threshold": 0.05,
    }
    payload.update(overrides)
    return payload


async def test_alert_opens_incident(client: AsyncClient) -> None:
    response = await client.post("/api/v1/alerts", json=alert_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["correlated"] is False
    assert body["status"] == "new"
    assert body["alert_id"] and body["incident_id"]


async def test_alert_within_window_joins_existing_incident(client: AsyncClient) -> None:
    first = await client.post("/api/v1/alerts", json=alert_payload())
    second = await client.post(
        "/api/v1/alerts",
        json=alert_payload(started_at=(BASE + timedelta(minutes=3)).isoformat()),
    )

    assert second.json()["correlated"] is True
    assert second.json()["incident_id"] == first.json()["incident_id"]


async def test_alert_outside_window_opens_new_incident(client: AsyncClient) -> None:
    first = await client.post("/api/v1/alerts", json=alert_payload())
    second = await client.post(
        "/api/v1/alerts",
        json=alert_payload(started_at=(BASE + timedelta(minutes=20)).isoformat()),
    )

    assert second.json()["correlated"] is False
    assert second.json()["incident_id"] != first.json()["incident_id"]


async def test_different_alert_type_opens_new_incident(client: AsyncClient) -> None:
    first = await client.post("/api/v1/alerts", json=alert_payload())
    second = await client.post(
        "/api/v1/alerts",
        json=alert_payload(alert_type="high_latency", severity="high"),
    )

    assert second.json()["correlated"] is False
    assert second.json()["incident_id"] != first.json()["incident_id"]


async def test_correlated_alert_escalates_severity(client: AsyncClient) -> None:
    first = await client.post("/api/v1/alerts", json=alert_payload(severity="medium"))
    incident_id = first.json()["incident_id"]

    await client.post(
        "/api/v1/alerts",
        json=alert_payload(
            severity="critical", started_at=(BASE + timedelta(minutes=1)).isoformat()
        ),
    )

    incident = await client.get(f"/api/v1/incidents/{incident_id}")
    assert incident.json()["severity"] == "critical"

    timeline = await client.get(f"/api/v1/incidents/{incident_id}/timeline")
    event_types = [event["event_type"] for event in timeline.json()["events"]]
    assert event_types == ["incident_created", "alert_correlated", "severity_escalated"]


async def test_lower_severity_does_not_downgrade_incident(client: AsyncClient) -> None:
    first = await client.post("/api/v1/alerts", json=alert_payload(severity="critical"))
    incident_id = first.json()["incident_id"]

    await client.post(
        "/api/v1/alerts",
        json=alert_payload(severity="low", started_at=(BASE + timedelta(minutes=1)).isoformat()),
    )

    incident = await client.get(f"/api/v1/incidents/{incident_id}")
    assert incident.json()["severity"] == "critical"


async def test_alert_can_be_fetched_by_id(client: AsyncClient) -> None:
    alert_id = (await client.post("/api/v1/alerts", json=alert_payload())).json()["alert_id"]

    response = await client.get(f"/api/v1/alerts/{alert_id}")

    assert response.status_code == 200
    assert response.json()["alert_type"] == "high_error_rate"


async def test_unknown_alert_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/alerts/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
