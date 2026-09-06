import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.core.metrics import (
    alerts_correlated_total,
    alerts_ingested_total,
    incidents_created_total,
)
from apps.api.app.models import (
    Alert,
    DeploymentEvent,
    Incident,
    IncidentAlert,
    IncidentEvent,
    IncidentEventType,
    IncidentStatus,
    Service,
    Severity,
)
from apps.api.app.models.enums import SEVERITY_RANK, TERMINAL_INCIDENT_STATUSES
from apps.api.app.schemas.alert import AlertIngestRequest


@dataclass(frozen=True)
class IngestResult:
    alert_id: uuid.UUID
    incident_id: uuid.UUID
    status: IncidentStatus
    correlated: bool
    service_name: str
    duplicate: bool = False


async def get_or_create_service(
    session: AsyncSession, name: str, environment: str = "staging"
) -> Service:
    service = await session.scalar(select(Service).where(Service.name == name))
    if service is None:
        service = Service(name=name, environment=environment)
        session.add(service)
        await session.flush()
    return service


async def find_correlated_incident(
    session: AsyncSession,
    service_id: uuid.UUID,
    alert_type: str,
    started_at: datetime,
    window_seconds: int,
) -> Incident | None:
    """Same service + same alert type + inside the correlation window joins one incident."""
    window = timedelta(seconds=window_seconds)
    stmt = (
        select(Incident)
        .join(IncidentAlert, IncidentAlert.incident_id == Incident.id)
        .join(Alert, Alert.id == IncidentAlert.alert_id)
        .where(
            Incident.service_id == service_id,
            Incident.status.not_in(tuple(TERMINAL_INCIDENT_STATUSES)),
            Alert.alert_type == alert_type,
            Alert.started_at >= started_at - window,
            Alert.started_at <= started_at + window,
        )
        .order_by(Incident.started_at.desc())
        .limit(1)
    )
    incident: Incident | None = await session.scalar(stmt)
    return incident


async def ingest_alert(
    session: AsyncSession, payload: AlertIngestRequest, window_seconds: int
) -> IngestResult:
    if payload.external_id:
        existing = await session.execute(
            select(Alert, Incident, Service)
            .join(IncidentAlert, IncidentAlert.alert_id == Alert.id)
            .join(Incident, Incident.id == IncidentAlert.incident_id)
            .join(Service, Service.id == Alert.service_id)
            .where(Alert.external_id == payload.external_id)
        )
        row = existing.one_or_none()
        if row is not None:
            alert, incident, service = row
            return IngestResult(
                alert_id=alert.id,
                incident_id=incident.id,
                status=IncidentStatus(incident.status),
                correlated=True,
                service_name=service.name,
                duplicate=True,
            )

    service = await get_or_create_service(
        session, payload.service_name, payload.labels.get("environment", "staging")
    )

    alert = Alert(
        external_id=payload.external_id,
        service_id=service.id,
        alert_type=payload.alert_type,
        severity=payload.severity,
        started_at=payload.started_at,
        raw_payload=payload.model_dump(mode="json"),
    )
    session.add(alert)
    await session.flush()

    incident = await find_correlated_incident(
        session, service.id, payload.alert_type, payload.started_at, window_seconds
    )
    correlated = incident is not None

    if incident is None:
        incident = Incident(
            service_id=service.id,
            title=_incident_title(payload),
            description=_incident_description(payload),
            severity=payload.severity,
            status=IncidentStatus.NEW,
            started_at=payload.started_at,
        )
        session.add(incident)
        await session.flush()
        session.add(
            IncidentEvent(
                incident_id=incident.id,
                event_type=IncidentEventType.INCIDENT_CREATED,
                message=f"Incident opened from {payload.alert_type} on {service.name}.",
                event_metadata={"alert_id": str(alert.id), "severity": payload.severity.value},
            )
        )
    else:
        session.add(
            IncidentEvent(
                incident_id=incident.id,
                event_type=IncidentEventType.ALERT_CORRELATED,
                message=(
                    f"Alert {payload.alert_type} correlated into this incident "
                    f"(within {window_seconds}s window)."
                ),
                event_metadata={"alert_id": str(alert.id)},
            )
        )
        _escalate_severity(session, incident, payload.severity)

    session.add(IncidentAlert(incident_id=incident.id, alert_id=alert.id))
    await session.commit()

    # Recorded here rather than in the router, so alerts arriving via the simulator count too.
    alerts_ingested_total.labels(
        service_name=service.name,
        alert_type=payload.alert_type,
        severity=payload.severity.value,
    ).inc()
    if correlated:
        alerts_correlated_total.labels(
            service_name=service.name, alert_type=payload.alert_type
        ).inc()
    else:
        incidents_created_total.labels(
            service_name=service.name, severity=payload.severity.value
        ).inc()

    return IngestResult(
        alert_id=alert.id,
        incident_id=incident.id,
        status=incident.status,
        correlated=correlated,
        service_name=service.name,
    )


def _escalate_severity(session: AsyncSession, incident: Incident, severity: Severity) -> None:
    # The column is a VARCHAR, so a loaded incident carries a plain str rather than the enum.
    previous = Severity(incident.severity)
    if SEVERITY_RANK[severity] <= SEVERITY_RANK[previous]:
        return
    incident.severity = severity
    session.add(
        IncidentEvent(
            incident_id=incident.id,
            event_type=IncidentEventType.SEVERITY_ESCALATED,
            message=f"Severity escalated from {previous.value} to {severity.value}.",
            event_metadata={"from": previous.value, "to": severity.value},
        )
    )


def _incident_title(payload: AlertIngestRequest) -> str:
    return f"{payload.service_name}: {payload.alert_type.replace('_', ' ')}"


def _incident_description(payload: AlertIngestRequest) -> str:
    parts = [f"Alert {payload.alert_type} fired on {payload.service_name}."]
    if payload.observed_value is not None and payload.threshold is not None:
        parts.append(f"Observed {payload.observed_value} against threshold {payload.threshold}.")
    if payload.labels:
        rendered = ", ".join(f"{k}={v}" for k, v in sorted(payload.labels.items()))
        parts.append(f"Labels: {rendered}.")
    return " ".join(parts)


async def record_deployment(
    session: AsyncSession,
    service: Service,
    version: str,
    previous_version: str | None,
    deployed_at: datetime,
    commit_sha: str | None = None,
    deployed_by: str | None = None,
) -> DeploymentEvent:
    deployment = DeploymentEvent(
        service_id=service.id,
        version=version,
        previous_version=previous_version,
        commit_sha=commit_sha,
        deployed_by=deployed_by,
        deployed_at=deployed_at,
    )
    session.add(deployment)
    service.current_version = version
    await session.flush()
    return deployment
