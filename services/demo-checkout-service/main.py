"""Demo checkout service.

The target the Copilot investigates. It never exhausts real resources: fault modes only change
response codes, latency, emitted logs and the metrics it reports.
"""

import asyncio
import json
import logging
import random
import sys
import time
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel

SERVICE_NAME = "checkout-api"
DB_POOL_MAX = 50

logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
_stdlib_logger = logging.getLogger(SERVICE_NAME)


class FaultMode(StrEnum):
    NORMAL = "normal"
    HIGH_LATENCY = "high_latency"
    ERROR_SPIKE = "error_spike"
    DATABASE_TIMEOUT = "database_timeout"
    DEPLOYMENT_REGRESSION = "deployment_regression"


class FaultModeRequest(BaseModel):
    mode: FaultMode


class State:
    def __init__(self) -> None:
        self.mode: FaultMode = FaultMode.NORMAL
        self.version: str = "v1.4.1"


state = State()

http_requests_total = Counter(
    "http_requests_total", "Checkout requests.", ["service_name", "endpoint", "status"]
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Checkout request latency.",
    ["service_name", "endpoint"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
db_connections_active = Gauge(
    "db_connections_active", "Active database connections.", ["service_name"]
)
db_connections_max = Gauge("db_connections_max", "Database connection pool size.", ["service_name"])
service_version_info = Gauge(
    "service_version_info", "Currently deployed version (always 1).", ["service_name", "version"]
)

db_connections_max.labels(service_name=SERVICE_NAME).set(DB_POOL_MAX)
db_connections_active.labels(service_name=SERVICE_NAME).set(4)
service_version_info.labels(service_name=SERVICE_NAME, version=state.version).set(1)

app = FastAPI(title="demo-checkout-service", version="1.0.0")


def log_event(level: str, event: str, **fields: Any) -> None:
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "level": level,
        "service": SERVICE_NAME,
        "version": state.version,
        "event": event,
        **fields,
    }
    _stdlib_logger.info(json.dumps(record))


@app.get("/checkout")
async def checkout() -> Response:
    started = time.perf_counter()
    mode = state.mode

    if mode is FaultMode.HIGH_LATENCY:
        await asyncio.sleep(random.uniform(1.5, 3.0))  # noqa: S311

    failed = False
    detail = "ok"

    if mode is FaultMode.ERROR_SPIKE and random.random() < 0.35:  # noqa: S311
        failed, detail = True, "upstream payment provider returned 502"
    elif mode in (FaultMode.DATABASE_TIMEOUT, FaultMode.DEPLOYMENT_REGRESSION):
        active = random.randint(46, DB_POOL_MAX)  # noqa: S311
        db_connections_active.labels(service_name=SERVICE_NAME).set(active)
        if random.random() < 0.35:  # noqa: S311
            failed, detail = True, "database connection timeout after 5000ms"
    else:
        db_connections_active.labels(service_name=SERVICE_NAME).set(random.randint(3, 8))  # noqa: S311

    elapsed = time.perf_counter() - started
    http_request_duration_seconds.labels(service_name=SERVICE_NAME, endpoint="/checkout").observe(
        elapsed
    )

    if failed:
        http_requests_total.labels(
            service_name=SERVICE_NAME, endpoint="/checkout", status="500"
        ).inc()
        log_event("ERROR", "checkout_failed", error=detail, latency_ms=round(elapsed * 1000))
        return Response(
            content=json.dumps({"error": detail}), status_code=500, media_type="application/json"
        )

    http_requests_total.labels(service_name=SERVICE_NAME, endpoint="/checkout", status="200").inc()
    log_event("INFO", "checkout_completed", latency_ms=round(elapsed * 1000))
    return Response(
        content=json.dumps({"status": "ok", "version": state.version}),
        media_type="application/json",
    )


@app.post("/internal/fault-mode")
async def set_fault_mode(payload: FaultModeRequest) -> dict[str, str]:
    previous_mode, previous_version = state.mode, state.version
    state.mode = payload.mode

    if payload.mode is FaultMode.DEPLOYMENT_REGRESSION:
        state.version = "v1.4.2"
    elif payload.mode is FaultMode.NORMAL:
        state.version = "v1.4.1"
        db_connections_active.labels(service_name=SERVICE_NAME).set(4)

    if state.version != previous_version:
        service_version_info.labels(service_name=SERVICE_NAME, version=previous_version).set(0)
        service_version_info.labels(service_name=SERVICE_NAME, version=state.version).set(1)
        log_event(
            "INFO", "deployment_completed", previous_version=previous_version, version=state.version
        )

    log_event("INFO", "fault_mode_changed", previous=previous_mode.value, current=state.mode.value)
    return {"mode": state.mode.value, "version": state.version}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "mode": state.mode.value, "version": state.version}


@app.get("/metrics")
async def metrics(_: Request) -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
