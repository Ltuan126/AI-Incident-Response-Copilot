# Connectors — week 2

Data sources the agent reads. Deliberately free of any LLM concept, so the evaluation harness can
replay recorded incidents without a model in the loop.

| Module | Source | Tool it backs |
| --- | --- | --- |
| `prometheus.py` | Prometheus HTTP API | `query_metrics` |
| `loki.py` | Loki HTTP API | `search_logs` |
| `deployments.py` | `deployment_events` table | `get_recent_deployments` |
| `runbooks.py` | pgvector similarity search | `retrieve_runbooks` |

The implemented connectors validate output with Pydantic, enforce a configurable timeout, cap
retries, return structured data and safe errors, and never expose source response details in
transport error messages. `POST /api/v1/incidents/{incident_id}/collect-evidence` writes successful
results as evidence and every attempt as a tool-call audit record. On failure it returns a
structured error so collection continues with the remaining sources:

```json
{
  "success": false,
  "error_code": "SOURCE_UNAVAILABLE",
  "retryable": true,
  "message": "Prometheus did not respond within five seconds."
}
```

`PrometheusConnector.query_range` uses `/api/v1/query_range` with RFC3339 bounds. `LokiConnector`
uses `/loki/api/v1/query_range` with nanosecond bounds and a bounded line limit. `DeploymentConnector`
queries `deployment_events` for the incident's service and collection window. The connectors are
source adapters only; they do not call an LLM or execute remediation.
