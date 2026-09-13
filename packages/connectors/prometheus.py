"""Prometheus range-query connector."""

from datetime import UTC, datetime
from typing import Any

from apps.api.app.models.enums import EvidenceSourceType
from packages.connectors.errors import ConnectorError
from packages.connectors.http import HttpConnector
from packages.connectors.models import ConnectorResult


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Connector timestamps must include a timezone")
    return value.astimezone(UTC)


class PrometheusConnector(HttpConnector):
    async def query_range(
        self, query: str, start: datetime, end: datetime, *, step_seconds: int = 15
    ) -> ConnectorResult:
        if not query.strip():
            raise ValueError("PromQL query must not be blank")
        if end < start:
            raise ValueError("Prometheus query end must not precede start")
        if step_seconds < 1:
            raise ValueError("Prometheus query step must be positive")
        start = _as_utc(start)
        end = _as_utc(end)
        query_params: dict[str, Any] = {
            "query": query,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "step": step_seconds,
        }
        payload = await self.get_json("/api/v1/query_range", query_params)
        if payload.get("status") != "success" or not isinstance(payload.get("data"), dict):
            raise ConnectorError(
                "INVALID_SOURCE_RESPONSE",
                "Prometheus returned an unsuccessful query.",
                retryable=False,
            )
        data = payload["data"]
        result = data.get("result")
        if not isinstance(result, list):
            raise ConnectorError(
                "INVALID_SOURCE_RESPONSE",
                "Prometheus response has no result list.",
                retryable=False,
            )
        raw_data: dict[str, Any] = {"status": payload["status"], "data": data}
        if "warnings" in payload:
            raw_data["warnings"] = payload["warnings"]
        return ConnectorResult(
            source_type=EvidenceSourceType.METRIC,
            source_name="prometheus",
            query=query,
            query_params=query_params,
            summary=f"Prometheus returned {len(result)} time series.",
            raw_data=raw_data,
            time_range_start=start,
            time_range_end=end,
            collected_at=datetime.now(UTC),
        )


def checkout_error_rate_query(service_name: str) -> str:
    """Return a bounded query for the demo service's HTTP error rate."""
    escaped = service_name.replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'sum(rate(http_requests_total{{service_name="{escaped}",status=~"5.."}}[5m])) '
        f'/ clamp_min(sum(rate(http_requests_total{{service_name="{escaped}"}}[5m])), 0.001)'
    )
