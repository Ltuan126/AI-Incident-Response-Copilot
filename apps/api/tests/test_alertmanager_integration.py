from datetime import UTC, datetime

from httpx import AsyncClient

STARTED_AT = datetime(2026, 9, 6, 18, 30, tzinfo=UTC)


def webhook_payload(*, status: str = "firing", fingerprint: str = "abc123") -> dict[str, object]:
    return {
        "version": "4",
        "status": status,
        "receiver": "incident-copilot",
        "groupLabels": {"alertname": "CheckoutHighErrorRate"},
        "commonLabels": {"service_name": "checkout-api"},
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "CheckoutHighErrorRate",
                    "alert_type": "high_error_rate",
                    "service_name": "checkout-api",
                    "severity": "critical",
                    "environment": "staging",
                },
                "annotations": {"observed_value": "0.35", "threshold": "0.20"},
                "startsAt": STARTED_AT.isoformat(),
                "endsAt": "0001-01-01T00:00:00Z",
                "fingerprint": fingerprint,
            }
        ],
    }


async def test_firing_webhook_creates_incident(client: AsyncClient) -> None:
    response = await client.post("/api/v1/integrations/alertmanager", json=webhook_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["received"] == 1
    assert body["ingested"] == 1
    assert body["duplicates"] == 0
    assert len(body["incident_ids"]) == 1

    incidents = await client.get("/api/v1/incidents?service_name=checkout-api")
    assert incidents.json()["total"] == 1
    assert incidents.json()["items"][0]["title"] == "checkout-api: high error rate"


async def test_repeated_fingerprint_is_idempotent(client: AsyncClient) -> None:
    first = await client.post("/api/v1/integrations/alertmanager", json=webhook_payload())
    second = await client.post("/api/v1/integrations/alertmanager", json=webhook_payload())

    assert second.status_code == 200
    assert second.json()["ingested"] == 0
    assert second.json()["duplicates"] == 1
    assert second.json()["incident_ids"] == first.json()["incident_ids"]

    incidents = await client.get("/api/v1/incidents?service_name=checkout-api")
    assert incidents.json()["total"] == 1


async def test_resolved_webhook_is_acknowledged_without_new_incident(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/integrations/alertmanager", json=webhook_payload(status="resolved")
    )

    assert response.status_code == 200
    assert response.json() == {
        "received": 1,
        "ingested": 0,
        "duplicates": 0,
        "ignored": 1,
        "incident_ids": [],
    }
