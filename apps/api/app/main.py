import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from apps.api.app.api.v1 import api_router
from apps.api.app.api.v1 import system as system_routes
from apps.api.app.core.config import get_settings
from apps.api.app.core.logging import configure_logging, get_logger
from apps.api.app.core.metrics import http_request_duration_seconds, http_requests_total

logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="AI Incident Response Copilot",
        version="0.1.0",
        description=(
            "Evidence-grounded incident analysis with mandatory human approval "
            "before any mutating action."
        ),
    )

    @app.middleware("http")
    async def record_request_metrics(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Use the route template, not the raw path, so UUIDs don't explode label cardinality.
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        http_requests_total.labels(
            method=request.method, path=path, status=str(response.status_code)
        ).inc()
        http_request_duration_seconds.labels(method=request.method, path=path).observe(
            time.perf_counter() - started
        )
        return response

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(system_routes.router)
    app.include_router(api_router)

    logger.info("api_started", environment=settings.environment)
    return app


app = create_app()
