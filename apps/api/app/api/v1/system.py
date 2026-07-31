from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from apps.api.app.api.deps import SessionDep

router = APIRouter(tags=["system"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up. Deliberately does not touch dependencies."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(session: SessionDep) -> dict[str, str]:
    """Readiness: the database is reachable, so the API can actually serve traffic."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - surfaced as a 503, details stay in logs
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="database unavailable"
        ) from exc
    return {"status": "ready"}
