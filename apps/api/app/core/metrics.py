from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "http_requests_total",
    "HTTP requests handled by the Copilot API.",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
)

alerts_ingested_total = Counter(
    "alerts_ingested_total",
    "Alerts accepted by the ingestion endpoint.",
    ["service_name", "alert_type", "severity"],
)

incidents_created_total = Counter(
    "incidents_created_total",
    "Incidents opened from alerts.",
    ["service_name", "severity"],
)

alerts_correlated_total = Counter(
    "alerts_correlated_total",
    "Alerts folded into an existing incident instead of opening a new one.",
    ["service_name", "alert_type"],
)
