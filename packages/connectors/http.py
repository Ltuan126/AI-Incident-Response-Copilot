"""Small bounded HTTP client shared by Prometheus and Loki connectors."""

from collections.abc import Mapping
from typing import Any

import httpx

from packages.connectors.errors import ConnectorError


class HttpConnector:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("Connector base_url must not be blank")
        if timeout_seconds <= 0:
            raise ValueError("Connector timeout must be positive")
        if not 0 <= max_retries <= 3:
            raise ValueError("Connector max_retries must be between 0 and 3")
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout_seconds)
        self.max_retries = max_retries
        self.transport = transport

    async def get_json(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        last_error: ConnectorError | None = None
        async with httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
            trust_env=False,
        ) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    response = await client.get(path, params=params)
                except httpx.TimeoutException:
                    last_error = ConnectorError(
                        "SOURCE_TIMEOUT",
                        "Source did not respond before the timeout.",
                        retryable=True,
                    )
                except httpx.TransportError:
                    last_error = ConnectorError(
                        "SOURCE_UNAVAILABLE", "Source connection failed.", retryable=True
                    )
                else:
                    if 200 <= response.status_code < 300:
                        try:
                            payload = response.json()
                        except ValueError as exc:
                            raise ConnectorError(
                                "INVALID_SOURCE_RESPONSE",
                                "Source returned invalid JSON.",
                                retryable=False,
                            ) from exc
                        if not isinstance(payload, dict):
                            raise ConnectorError(
                                "INVALID_SOURCE_RESPONSE",
                                "Source returned a JSON value instead of an object.",
                                retryable=False,
                            )
                        return payload
                    retryable = response.status_code >= 500
                    last_error = ConnectorError(
                        "SOURCE_HTTP_ERROR",
                        f"Source returned HTTP {response.status_code}.",
                        retryable=retryable,
                    )
                if last_error is None or not last_error.retryable or attempt >= self.max_retries:
                    break

        if last_error is None:  # pragma: no cover - defensive guard
            raise ConnectorError("SOURCE_UNAVAILABLE", "Source query failed.", retryable=True)
        raise last_error
