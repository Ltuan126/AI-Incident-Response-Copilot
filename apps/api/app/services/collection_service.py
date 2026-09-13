"""Run the bounded connector collection pass for one incident."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.config import Settings
from apps.api.app.models import AgentRun, AgentRunStatus, Incident, Service, ToolCallStatus
from apps.api.app.schemas.collection import (
    CollectEvidenceRequest,
    CollectEvidenceResponse,
    CollectionSourceRead,
)
from apps.api.app.schemas.investigation import AgentRunCreate, EvidenceCreate, ToolCallCreate
from apps.api.app.services import investigation_service
from packages.connectors import (
    ConnectorError,
    DeploymentConnector,
    LokiConnector,
    PrometheusConnector,
    checkout_error_rate_query,
    checkout_log_query,
)


class CollectionNotFoundError(ValueError):
    """The requested incident or its service is missing."""


async def collect_incident_evidence(
    session: AsyncSession,
    incident_id: uuid.UUID,
    request: CollectEvidenceRequest,
    settings: Settings,
) -> CollectEvidenceResponse:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise CollectionNotFoundError("Incident not found")
    service = await session.get(Service, incident.service_id)
    if service is None:  # pragma: no cover - protects corrupted legacy data
        raise CollectionNotFoundError("Incident service not found")

    end = request.end_at or datetime.now(UTC)
    incident_started = incident.started_at
    if incident_started.tzinfo is None:
        # SQLite drops timezone metadata on round-trip; the stored value is UTC by contract.
        incident_started = incident_started.replace(tzinfo=UTC)
    else:
        incident_started = incident_started.astimezone(UTC)
    start = max(incident_started, end - timedelta(seconds=request.lookback_seconds))
    run = await investigation_service.create_agent_run(
        session,
        incident_id,
        AgentRunCreate(prompt_version=settings.prompt_version, provider="connectors"),
    )
    run.status = AgentRunStatus.RUNNING
    run.started_at = datetime.now(UTC)
    await session.commit()

    prometheus = PrometheusConnector(
        settings.prometheus_url,
        timeout_seconds=settings.connector_timeout_seconds,
        max_retries=settings.connector_max_retries,
    )
    loki = LokiConnector(
        settings.loki_url,
        timeout_seconds=settings.connector_timeout_seconds,
        max_retries=settings.connector_max_retries,
    )
    deployment = DeploymentConnector()
    source_results: list[CollectionSourceRead] = []
    evidence_ids: list[uuid.UUID] = []

    metric_query = checkout_error_rate_query(service.name)
    log_query = checkout_log_query(service.name)
    failed_input: dict[str, dict[str, Any]] = {
        "metric": {
            "query": metric_query,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": request.step_seconds,
        },
        "log": {
            "query": log_query,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": request.log_limit,
        },
        "deployment": {
            "service_id": str(service.id),
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
    }
    queries: list[tuple[str, str, Any]] = [
        (
            "metric",
            "prometheus",
            lambda: prometheus.query_range(
                metric_query,
                start,
                end,
                step_seconds=request.step_seconds,
            ),
        ),
        (
            "log",
            "loki",
            lambda: loki.query_range(log_query, start, end, limit=request.log_limit),
        ),
        (
            "deployment",
            "postgresql",
            lambda: deployment.query_range(session, service.id, start, end),
        ),
    ]
    for source_type, source_name, query in queries:
        started_at = datetime.now(UTC)
        try:
            result = await query()
            finished_at = datetime.now(UTC)
            tool_call = await investigation_service.record_tool_call(
                session,
                run.id,
                ToolCallCreate(
                    tool_name=f"query_{source_type}s",
                    status=ToolCallStatus.SUCCEEDED,
                    input_payload=result.query_params,
                    output_payload=result.raw_data,
                    started_at=started_at,
                    finished_at=finished_at,
                ),
            )
            evidence = await investigation_service.record_evidence(
                session,
                run.id,
                EvidenceCreate(
                    tool_call_id=tool_call.id,
                    source_type=result.source_type,
                    source_name=result.source_name,
                    query=result.query,
                    query_params=result.query_params,
                    summary=result.summary,
                    raw_data=result.raw_data,
                    time_range_start=result.time_range_start,
                    time_range_end=result.time_range_end,
                    collected_at=result.collected_at,
                ),
            )
            await session.commit()
            evidence_ids.append(evidence.id)
            source_results.append(
                CollectionSourceRead(
                    source_type=result.source_type,
                    source_name=result.source_name,
                    status=ToolCallStatus.SUCCEEDED,
                    tool_call_id=tool_call.id,
                    evidence_id=evidence.id,
                    message=result.summary,
                )
            )
        except ConnectorError as exc:
            await session.rollback()
            finished_at = datetime.now(UTC)
            failed_call = await investigation_service.record_tool_call(
                session,
                run.id,
                ToolCallCreate(
                    tool_name=f"query_{source_type}s",
                    status=ToolCallStatus.FAILED,
                    input_payload=failed_input[source_type],
                    output_payload={"error_code": exc.code, "retryable": exc.retryable},
                    error_message=exc.message,
                    started_at=started_at,
                    finished_at=finished_at,
                ),
            )
            await session.commit()
            source_results.append(
                CollectionSourceRead(
                    source_type=source_type,
                    source_name=source_name,
                    status=ToolCallStatus.FAILED,
                    tool_call_id=failed_call.id,
                    error_code=exc.code,
                    retryable=exc.retryable,
                    message=exc.message,
                )
            )

    completed_run = await session.get(AgentRun, run.id)
    if completed_run is None:  # pragma: no cover - run was committed above
        raise CollectionNotFoundError("Collection run disappeared")
    completed_run.status = (
        AgentRunStatus.COMPLETED if evidence_ids else AgentRunStatus.INSUFFICIENT_EVIDENCE
    )
    completed_run.finished_at = datetime.now(UTC)
    if not evidence_ids:
        completed_run.error_message = "No connector returned evidence."
    await session.commit()
    return CollectEvidenceResponse(
        incident_id=incident_id,
        agent_run_id=completed_run.id,
        status=completed_run.status,
        time_range_start=start,
        time_range_end=end,
        sources=source_results,
        evidence_ids=evidence_ids,
    )
