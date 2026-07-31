import uuid

from fastapi import APIRouter, HTTPException, status

from apps.api.app.api.deps import SessionDep, SettingsDep
from apps.api.app.models import Alert
from apps.api.app.schemas.alert import AlertIngestRequest, AlertIngestResponse, AlertRead
from apps.api.app.services import incident_service

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("", response_model=AlertIngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_alert(
    payload: AlertIngestRequest, session: SessionDep, settings: SettingsDep
) -> AlertIngestResponse:
    result = await incident_service.ingest_alert(
        session, payload, settings.correlation_window_seconds
    )
    return AlertIngestResponse(
        alert_id=result.alert_id,
        incident_id=result.incident_id,
        status=result.status,
        correlated=result.correlated,
    )


@router.get("/{alert_id}", response_model=AlertRead)
async def get_alert(alert_id: uuid.UUID, session: SessionDep) -> AlertRead:
    alert = await session.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
    return AlertRead.model_validate(alert)
