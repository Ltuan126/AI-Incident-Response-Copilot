import re

from fastapi import APIRouter

from apps.api.app.api.deps import SessionDep, SettingsDep
from apps.api.app.models.enums import Severity
from apps.api.app.schemas.alert import AlertIngestRequest
from apps.api.app.schemas.alertmanager import (
    AlertmanagerAlert,
    AlertmanagerWebhook,
    AlertmanagerWebhookResponse,
)
from apps.api.app.services import incident_service

router = APIRouter(prefix="/integrations", tags=["integrations"])

SEVERITY_MAP: dict[str, Severity] = {
    "info": Severity.LOW,
    "warning": Severity.HIGH,
    "critical": Severity.CRITICAL,
}


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _snake_case(value: str) -> str:
    separated = re.sub(r"(?<!^)(?=[A-Z])", "_", value)
    return re.sub(r"[^a-zA-Z0-9]+", "_", separated).strip("_").lower()


def _to_ingest_request(alert: AlertmanagerAlert) -> AlertIngestRequest:
    labels = alert.labels
    annotations = alert.annotations
    service_name = labels.get("service_name") or labels.get("service") or labels.get("job")
    if not service_name:
        service_name = "unknown-service"

    alert_name = labels.get("alert_type") or labels.get("alertname") or "unknown_alert"
    severity = SEVERITY_MAP.get(labels.get("severity", "").lower(), Severity.MEDIUM)
    external_id = (
        f"alertmanager:{alert.fingerprint}:{alert.starts_at.isoformat()}"[:128]
        if alert.fingerprint
        else None
    )

    return AlertIngestRequest(
        service_name=service_name,
        alert_type=_snake_case(alert_name),
        severity=severity,
        started_at=alert.starts_at,
        labels={**labels, "source": "alertmanager"},
        observed_value=_as_float(annotations.get("observed_value")),
        threshold=_as_float(annotations.get("threshold")),
        external_id=external_id,
    )


@router.post("/alertmanager", response_model=AlertmanagerWebhookResponse)
async def receive_alertmanager_webhook(
    payload: AlertmanagerWebhook, session: SessionDep, settings: SettingsDep
) -> AlertmanagerWebhookResponse:
    incident_ids: list[str] = []
    ingested = 0
    duplicates = 0
    ignored = 0

    for alert in payload.alerts:
        if payload.status != "firing" or alert.status != "firing":
            ignored += 1
            continue

        result = await incident_service.ingest_alert(
            session,
            _to_ingest_request(alert),
            settings.correlation_window_seconds,
        )
        incident_id = str(result.incident_id)
        if incident_id not in incident_ids:
            incident_ids.append(incident_id)
        if result.duplicate:
            duplicates += 1
        else:
            ingested += 1

    return AlertmanagerWebhookResponse(
        received=len(payload.alerts),
        ingested=ingested,
        duplicates=duplicates,
        ignored=ignored,
        incident_ids=incident_ids,
    )
