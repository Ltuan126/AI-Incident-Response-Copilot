from datetime import UTC, datetime

import httpx
from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.api.deps import SessionDep, SettingsDep
from apps.api.app.core.config import Settings
from apps.api.app.core.logging import get_logger
from apps.api.app.schemas.simulator import FaultMode, SimulationResponse
from apps.api.app.services import incident_service

router = APIRouter(prefix="/simulator", tags=["simulator"])
logger = get_logger(__name__)

DEMO_SERVICE_NAME = "checkout-api"
FAULT_MODE_TIMEOUT_SECONDS = 5.0


async def _apply_fault_mode(base_url: str, mode: FaultMode) -> bool:
    try:
        async with httpx.AsyncClient(timeout=FAULT_MODE_TIMEOUT_SECONDS, trust_env=False) as client:
            response = await client.post(
                f"{base_url}/internal/fault-mode", json={"mode": mode.value}
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("fault_mode_not_applied", mode=mode.value, error=str(exc))
        return False
    return True


async def _run_scenario(
    scenario: FaultMode, session: AsyncSession, settings: Settings
) -> SimulationResponse:
    now = datetime.now(UTC)
    applied = await _apply_fault_mode(settings.demo_service_url, scenario)

    if scenario is FaultMode.DEPLOYMENT_REGRESSION and applied:
        service = await incident_service.get_or_create_service(session, DEMO_SERVICE_NAME)
        await incident_service.record_deployment(
            session,
            service=service,
            version="v1.4.2",
            previous_version="v1.4.1",
            deployed_at=now,
            commit_sha="9f2c1ab",
            deployed_by="simulator",
        )
        await session.commit()

    return SimulationResponse(
        scenario=scenario,
        service_name=DEMO_SERVICE_NAME,
        fault_mode_applied=applied,
        detail=(
            "Fault mode activated. Prometheus will open the incident after the alert threshold."
            if applied
            else "The demo service did not accept the fault mode; no incident will be generated."
        ),
    )


@router.post("/incidents/high-latency", response_model=SimulationResponse)
async def simulate_high_latency(session: SessionDep, settings: SettingsDep) -> SimulationResponse:
    return await _run_scenario(FaultMode.HIGH_LATENCY, session, settings)


@router.post("/incidents/error-spike", response_model=SimulationResponse)
async def simulate_error_spike(session: SessionDep, settings: SettingsDep) -> SimulationResponse:
    return await _run_scenario(FaultMode.ERROR_SPIKE, session, settings)


@router.post("/incidents/database-timeout", response_model=SimulationResponse)
async def simulate_database_timeout(
    session: SessionDep, settings: SettingsDep
) -> SimulationResponse:
    return await _run_scenario(FaultMode.DATABASE_TIMEOUT, session, settings)


@router.post("/incidents/deployment-regression", response_model=SimulationResponse)
async def simulate_deployment_regression(
    session: SessionDep, settings: SettingsDep
) -> SimulationResponse:
    return await _run_scenario(FaultMode.DEPLOYMENT_REGRESSION, session, settings)


@router.post("/recover", response_model=SimulationResponse)
async def recover(settings: SettingsDep) -> SimulationResponse:
    applied = await _apply_fault_mode(settings.demo_service_url, FaultMode.NORMAL)
    return SimulationResponse(
        scenario=FaultMode.NORMAL,
        service_name=DEMO_SERVICE_NAME,
        fault_mode_applied=applied,
        detail="Demo service returned to normal." if applied else "Demo service unreachable.",
    )
