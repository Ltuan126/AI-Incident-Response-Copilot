from fastapi import APIRouter

from apps.api.app.api.v1 import alerts, incidents, integrations, investigations, simulator

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(alerts.router)
api_router.include_router(incidents.router)
api_router.include_router(integrations.router)
api_router.include_router(investigations.router)
api_router.include_router(simulator.router)

__all__ = ["api_router"]
