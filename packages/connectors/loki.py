"""Loki log-range connector."""

from datetime import UTC, datetime
from typing import Any

from apps.api.app.models.enums import EvidenceSourceType
from packages.connectors.errors import ConnectorError
from packages.connectors.http import HttpConnector
from packages.connectors.models import ConnectorResult


def _nanoseconds(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Connector timestamps must include a timezone")
    return str(int(value.astimezone(UTC).timestamp() * 1_000_000_000))


class LokiConnector(HttpConnector):
    async def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        *,
        limit: int = 100,
    ) -> ConnectorResult:
        if not query.strip():
            raise ValueError("LogQL query must not be blank")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Connector timestamps must include a timezone")
        if end < start:
            raise ValueError("Loki query end must not precede start")
        if limit < 1 or limit > 5000:
            raise ValueError("Loki query limit must be between 1 and 5000")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        query_params: dict[str, Any] = {
            "query": query,
            "start": _nanoseconds(start),
            "end": _nanoseconds(end),
            "limit": limit,
            "direction": "backward",
        }
        payload = await self.get_json("/loki/api/v1/query_range", query_params)
        if payload.get("status") != "success" or not isinstance(payload.get("data"), dict):
            raise ConnectorError(
                "INVALID_SOURCE_RESPONSE", "Loki returned an unsuccessful query.", retryable=False
            )
        data = payload["data"]
        streams = data.get("result")
        if not isinstance(streams, list):
            raise ConnectorError(
                "INVALID_SOURCE_RESPONSE", "Loki response has no result list.", retryable=False
            )
        line_count = sum(
            len(stream.get("values", []))
            for stream in streams
            if isinstance(stream, dict) and isinstance(stream.get("values"), list)
        )
        return ConnectorResult(
            source_type=EvidenceSourceType.LOG,
            source_name="loki",
            query=query,
            query_params=query_params,
            summary=f"Loki returned {line_count} log lines across {len(streams)} streams.",
            raw_data=payload,
            time_range_start=start,
            time_range_end=end,
            collected_at=datetime.now(UTC),
        )


def checkout_log_query(service_name: str) -> str:
    escaped = service_name.replace("\\", "\\\\").replace('"', '\\"')
    return f'{{service_name="{escaped}"}} |~ "(?i)(error|timeout|failed|exception)"'
