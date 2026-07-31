from httpx import AsyncClient


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


async def test_deployment_regression_scenario_creates_incident(client: AsyncClient) -> None:
    # Whether the demo service is reachable is an environment detail, so it is not asserted here.
    # What must hold either way: the scenario produces a usable incident.
    response = await client.post("/api/v1/simulator/incidents/deployment-regression")

    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] is not None
    assert body["service_name"] == "checkout-api"

    timeline = await client.get(f"/api/v1/incidents/{body['incident_id']}/timeline")
    event_types = [event["event_type"] for event in timeline.json()["events"]]
    assert "deployment_recorded" in event_types


async def test_simulator_incidents_are_counted_in_metrics(client: AsyncClient) -> None:
    # Ingestion metrics live in the service layer precisely so simulator-created incidents,
    # which never touch the alerts router, still show up.
    await client.post("/api/v1/simulator/incidents/error-spike")

    metrics = (await client.get("/metrics")).text

    assert 'incidents_created_total{service_name="checkout-api",severity="critical"}' in metrics
    assert 'alerts_ingested_total{alert_type="high_error_rate"' in metrics
