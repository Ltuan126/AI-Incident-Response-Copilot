import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from apps.api.app.api.deps import SessionDep, SettingsDep
from apps.api.app.models import Approval, ApprovalStatus
from apps.api.app.schemas.investigation import (
    ApprovalDecision,
    ApprovalListResponse,
    ApprovalRead,
)
from apps.api.app.services.approval_service import (
    ApprovalError,
    decide_approval,
    request_approval,
)
from apps.api.app.services.remediation_service import RemediationError, execute_approval

router = APIRouter(tags=["approvals"])


@router.post(
    "/recommendations/{recommendation_id}/approval",
    response_model=ApprovalRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_approval(recommendation_id: uuid.UUID, session: SessionDep) -> ApprovalRead:
    try:
        approval = await request_approval(session, recommendation_id)
        await session.commit()
        return ApprovalRead.model_validate(approval)
    except ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/approvals/pending", response_model=ApprovalListResponse)
async def list_pending_approvals(
    session: SessionDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> ApprovalListResponse:
    filters = [Approval.status == ApprovalStatus.PENDING]
    total = await session.scalar(select(func.count()).select_from(Approval).where(*filters)) or 0
    rows = await session.scalars(
        select(Approval)
        .where(*filters)
        .order_by(Approval.created_at.asc(), Approval.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return ApprovalListResponse(
        items=[ApprovalRead.model_validate(row) for row in rows], total=total
    )


@router.post("/approvals/{approval_id}/decision", response_model=ApprovalRead)
async def decide(
    approval_id: uuid.UUID, payload: ApprovalDecision, session: SessionDep
) -> ApprovalRead:
    try:
        approval = await decide_approval(session, approval_id, payload)
        await session.commit()
        return ApprovalRead.model_validate(approval)
    except ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/approvals/{approval_id}/execute", response_model=ApprovalRead)
async def execute(
    approval_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> ApprovalRead:
    try:
        approval = await execute_approval(session, approval_id, settings)
        await session.commit()
        return ApprovalRead.model_validate(approval)
    except RemediationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
