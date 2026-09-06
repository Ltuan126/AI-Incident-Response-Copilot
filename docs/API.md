# API reference

Base URL `http://localhost:8000`. Interactive docs at `/docs`, schema at `/openapi.json`.

Endpoints marked **Planned** are specified but not yet implemented — see
[ROADMAP.md](ROADMAP.md).

## System

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Liveness. Does not touch the database. |
| GET | `/ready` | Readiness. Returns 503 when the database is unreachable. |
| GET | `/metrics` | Prometheus exposition format. |

## Alerts

### POST `/api/v1/alerts`

Ingest an alert. Creates an incident, or joins an existing one when the correlation rule matches.

```json
{
  "service_name": "checkout-api",
  "alert_type": "high_error_rate",
  "severity": "critical",
  "started_at": "2026-07-30T14:32:00Z",
  "labels": { "environment": "staging", "region": "ap-southeast-1" },
  "observed_value": 0.35,
  "threshold": 0.05
}
```

`201 Created`:

```json
{
  "alert_id": "b1f7...",
  "incident_id": "9ac2...",
  "status": "new",
  "correlated": false
}
```

`correlated: true` means the alert joined an existing incident rather than opening a new one.

Optional fields: `labels`, `observed_value`, `threshold`, `external_id` (unique; use the upstream
alert ID to make retries safe). `severity` is one of `low`, `medium`, `high`, `critical`.

### GET `/api/v1/alerts/{alert_id}`

Returns the stored alert. `404` when unknown.

## Integrations

### POST `/api/v1/integrations/alertmanager`

Receives an Alertmanager webhook. Firing alerts are normalized into the alert ingestion model;
resolved notifications are acknowledged and ignored for now. Alertmanager fingerprints are used
as idempotency keys, so retries do not create duplicate alerts or incidents.

```json
{
  "received": 1,
  "ingested": 1,
  "duplicates": 0,
  "ignored": 0,
  "incident_ids": ["9ac2..."]
}
```

## Incidents

### GET `/api/v1/incidents`

Query parameters: `service_name`, `status`, `severity`, `limit` (1–200, default 50), `offset`.

```json
{ "items": [ { "id": "...", "title": "checkout-api: high error rate", "severity": "critical", "status": "new" } ], "total": 1 }
```

An unknown `service_name` returns an empty list rather than a 404 — filtering on something that
does not exist is not a client error.

### GET `/api/v1/incidents/{incident_id}`

Full incident record. `404` when unknown.

### GET `/api/v1/incidents/{incident_id}/timeline`

Ordered `incident_events`, oldest first. Event types currently emitted: `incident_created`,
`alert_correlated`, `severity_escalated`, `deployment_recorded`.

```json
{
  "incident_id": "9ac2...",
  "events": [
    {
      "event_type": "incident_created",
      "message": "Incident opened from high_error_rate on checkout-api.",
      "event_metadata": { "alert_id": "b1f7...", "severity": "critical" },
      "created_at": "2026-07-30T14:32:01Z"
    }
  ]
}
```

### POST `/api/v1/incidents/{incident_id}/analyze` — **Planned (week 3)**

Starts an agent run.

### GET `/api/v1/incidents/{incident_id}/report` — **Planned (week 3)**

## Simulator

Each scenario switches the demo service into a fault mode. The traffic generator produces real
requests, Prometheus evaluates the metrics, and Alertmanager creates the matching incident through
the integration webhook.

| Method | Path | Alert produced |
| --- | --- | --- |
| POST | `/api/v1/simulator/incidents/high-latency` | `high_latency`, high |
| POST | `/api/v1/simulator/incidents/error-spike` | `high_error_rate`, critical |
| POST | `/api/v1/simulator/incidents/database-timeout` | `database_connection_exhaustion`, critical |
| POST | `/api/v1/simulator/incidents/deployment-regression` | `high_error_rate`, critical, plus a `v1.4.1 → v1.4.2` deployment record |
| POST | `/api/v1/simulator/recover` | none — returns the service to `normal` |

```json
{
  "scenario": "deployment_regression",
  "service_name": "checkout-api",
  "alert_id": null,
  "incident_id": null,
  "fault_mode_applied": true,
  "detail": "Fault mode activated. Prometheus will open the incident after the alert threshold."
}
```

`fault_mode_applied: false` means the demo service was unreachable, so no incident will be created.
Successful responses intentionally do not contain an incident ID: the incident appears only after
the monitoring path detects the failure.

## Demo checkout service

Runs separately on `http://localhost:8001`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/checkout` | The endpoint whose behaviour degrades under fault modes. |
| GET | `/health` | Current mode and version. |
| GET | `/metrics` | Prometheus metrics including `db_connections_active`. |
| POST | `/internal/fault-mode` | `{"mode": "deployment_regression"}` |

Modes: `normal`, `high_latency`, `error_spike`, `database_timeout`, `deployment_regression`.
Fault modes only change responses, latency, logs and reported metrics — nothing real is exhausted.

## Planned endpoints

**Agent (week 3–4)**

```
GET  /api/v1/agent-runs/{run_id}
GET  /api/v1/agent-runs/{run_id}/tool-calls
GET  /api/v1/agent-runs/{run_id}/evidence
WS   /api/v1/agent-runs/{run_id}/stream
```

**Approvals (week 4)**

```
GET  /api/v1/approvals/pending
GET  /api/v1/approvals/{approval_id}
POST /api/v1/approvals/{approval_id}/decision
```

**Runbooks (week 3)**

```
POST   /api/v1/runbooks
GET    /api/v1/runbooks
GET    /api/v1/runbooks/{runbook_id}
PUT    /api/v1/runbooks/{runbook_id}
DELETE /api/v1/runbooks/{runbook_id}
```
