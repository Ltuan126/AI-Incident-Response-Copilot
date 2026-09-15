import uuid

from fastapi import APIRouter, HTTPException, status

from apps.api.app.api.deps import SessionDep
from apps.api.app.schemas.analysis import AnalyzeIncidentRequest, AnalyzeIncidentResponse
from apps.api.app.services.analysis_service import analyze_incident
from apps.api.app.services.investigation_service import InvestigationNotFoundError

router = APIRouter(tags=["analysis"])


@router.post(
    "/incidents/{incident_id}/analyze",
    response_model=AnalyzeIncidentResponse,
    status_code=status.HTTP_200_OK,
)
async def analyze(
    incident_id: uuid.UUID,
    session: SessionDep,
    payload: AnalyzeIncidentRequest | None = None,
) -> AnalyzeIncidentResponse:
    try:
        response = await analyze_incident(session, incident_id, payload or AnalyzeIncidentRequest())
        await session.commit()
        return response
    except InvestigationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
