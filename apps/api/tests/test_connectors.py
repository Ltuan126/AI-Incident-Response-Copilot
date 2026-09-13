import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from httpx import AsyncClient, MockTransport, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import AgentRun, Evidence, Incident, Service, ToolCall, ToolCallStatus
from apps.api.app.services import collection_service
from packages.connectors import ConnectorError, ConnectorResult, LokiConnector, PrometheusConnector
from packages.connectors.deployments import DeploymentConnector
from packages.connectors.loki import checkout_log_query
from packages.connectors.prometheus import checkout_error_rate_query

BASE = datetime(2026, 9, 13, 12, tzinfo=UTC)


async def test_prometheus_range_connector_validates_response_and_preserves_query() -> None:
    requests: list[Request] = []

    def handler(request: Request) -> Response:
        requests.append(request)
        return Response(
            200,
            json={
                "status": "success",
                "data": {"resultType": "matrix", "result": [{"metric": {"job": "api"}}]},
                "warnings": ["fixture warning"],
            },
        )

    query = checkout_error_rate_query("checkout-api")
    result = await PrometheusConnector(
        "http://prometheus", transport=MockTransport(handler)
    ).query_range(query, BASE, BASE + timedelta(minutes=5), step_seconds=30)

    assert result.source_type == "metric"
    assert result.source_name == "prometheus"
    assert result.query == query
    assert cast(Any, result.raw_data["data"])["resultType"] == "matrix"
    assert requests[0].url.path == "/api/v1/query_range"
    assert requests[0].url.params["step"] == "30"
    assert requests[0].url.params["query"] == query


async def test_loki_range_connector_uses_nanosecond_bounds_and_retries() -> None:
    attempts = 0

    def handler(request: Request) -> Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return Response(503, json={"status": "error"})
        return Response(
            200,
            json={
                "status": "success",
                "data": {
                    "resultType": "streams",
                    "result": [
                        {"stream": {"service_name": "checkout-api"}, "values": [["1", "timeout"]]}
                    ],
                },
            },
        )

    start = BASE.replace(microsecond=123456)
    end = BASE + timedelta(minutes=1)
    result = await LokiConnector("http://loki", transport=MockTransport(handler)).query_range(
        checkout_log_query("checkout-api"), start, end, limit=25
    )

    assert attempts == 2
    assert result.summary == "Loki returned 1 log lines across 1 streams."
    assert result.query_params["start"] == str(int(start.timestamp() * 1_000_000_000))
    assert result.query_params["limit"] == 25


async def test_http_connector_returns_safe_structured_failures() -> None:
    def handler(_: Request) -> Response:
        return Response(400, json={"error": "secret details should not escape"})

    with pytest.raises(ConnectorError) as error:
        await PrometheusConnector(
            "http://prometheus", transport=MockTransport(handler)
        ).query_range("up", BASE, BASE + timedelta(minutes=1))
    assert error.value.code == "SOURCE_HTTP_ERROR"
    assert error.value.retryable is False
    assert "secret" not in error.value.message


async def test_deployment_connector_returns_records_for_service_window(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": "checkout-api",
            "alert_type": "high_error_rate",
            "severity": "critical",
            "started_at": BASE.isoformat(),
        },
    )
    incident_id = uuid.UUID(response.json()["incident_id"])
    incident = await session.get(Incident, incident_id)
    assert incident is not None
    service = await session.get(Service, incident.service_id)
    assert service is not None
    from apps.api.app.services.incident_service import record_deployment

    await record_deployment(session, service, "v2", "v1", BASE)
    await session.commit()
    result = await DeploymentConnector().query_range(
        session, service.id, BASE - timedelta(minutes=1), BASE + timedelta(minutes=1)
    )
    assert result.source_name == "postgresql"
    assert cast(Any, result.raw_data["deployments"])[0]["version"] == "v2"


def _fixture_result(source_type: str, source_name: str) -> ConnectorResult:
    return ConnectorResult(
        source_type=source_type,
        source_name=source_name,
        query=f"fixture://{source_name}",
        query_params={"fixture": True},
        summary=f"Collected {source_name} fixture.",
        raw_data={"source": source_name, "lines": ["timeout"]},
        time_range_start=BASE,
        time_range_end=BASE + timedelta(minutes=5),
        collected_at=BASE + timedelta(minutes=5),
    )


async def test_collection_endpoint_persists_three_sources_and_continues_after_failure(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = await client.post(
        "/api/v1/alerts",
        json={
            "service_name": "checkout-api",
            "alert_type": "high_error_rate",
            "severity": "critical",
            "started_at": BASE.isoformat(),
        },
    )
    incident_id = response.json()["incident_id"]

    class FakePrometheus:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def query_range(self, *_: object, **__: object) -> ConnectorResult:
            return _fixture_result("metric", "prometheus")

    class FakeLoki:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        async def query_range(self, *_: object, **__: object) -> ConnectorResult:
            raise ConnectorError(
                "SOURCE_TIMEOUT", "Source did not respond before the timeout.", retryable=True
            )

    class FakeDeployment:
        async def query_range(self, *_: object, **__: object) -> ConnectorResult:
            return _fixture_result("deployment", "postgresql")

    monkeypatch.setattr(collection_service, "PrometheusConnector", FakePrometheus)
    monkeypatch.setattr(collection_service, "LokiConnector", FakeLoki)
    monkeypatch.setattr(collection_service, "DeploymentConnector", FakeDeployment)
    collected = await client.post(f"/api/v1/incidents/{incident_id}/collect-evidence")

    assert collected.status_code == 201, collected.text
    body = collected.json()
    assert body["status"] == "completed"
    assert len(body["evidence_ids"]) == 2
    assert [source["status"] for source in body["sources"]] == ["succeeded", "failed", "succeeded"]
    assert body["sources"][1]["error_code"] == "SOURCE_TIMEOUT"
    run_id = uuid.UUID(body["agent_run_id"])
    evidence_rows = await session.scalars(select(Evidence).where(Evidence.agent_run_id == run_id))
    assert len(list(evidence_rows)) == 2
    calls = list(
        (await session.scalars(select(ToolCall).where(ToolCall.agent_run_id == run_id))).all()
    )
    assert [call.status for call in calls].count(ToolCallStatus.FAILED) == 1
    run = await session.get(AgentRun, run_id)
    assert run is not None and run.finished_at is not None
