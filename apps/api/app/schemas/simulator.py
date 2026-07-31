import uuid
from enum import StrEnum

from pydantic import BaseModel


class FaultMode(StrEnum):
    NORMAL = "normal"
    HIGH_LATENCY = "high_latency"
    ERROR_SPIKE = "error_spike"
    DATABASE_TIMEOUT = "database_timeout"
    DEPLOYMENT_REGRESSION = "deployment_regression"


class SimulationResponse(BaseModel):
    scenario: FaultMode
    service_name: str
    alert_id: uuid.UUID | None = None
    incident_id: uuid.UUID | None = None
    fault_mode_applied: bool
    detail: str
