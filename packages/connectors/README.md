# Connectors — week 2

Data sources the agent reads. Deliberately free of any LLM concept, so the evaluation harness can
replay recorded incidents without a model in the loop.

| Module | Source | Tool it backs |
| --- | --- | --- |
| `prometheus.py` | Prometheus HTTP API | `query_metrics` |
| `loki.py` | Loki HTTP API | `search_logs` |
| `deployments.py` | `deployment_events` table | `get_recent_deployments` |
| `runbooks.py` | pgvector similarity search | `retrieve_runbooks` |

Every connector must validate input and output with Pydantic, enforce a timeout, cap retries,
return structured data, write a tool-call audit record, and never return secrets. On failure it
returns a structured error so the agent can continue with the remaining sources:

```json
{
  "success": false,
  "error_code": "SOURCE_UNAVAILABLE",
  "retryable": true,
  "message": "Prometheus did not respond within five seconds."
}
```
