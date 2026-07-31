# Architecture

## Shape of the system

A modular monolith plus an agent worker. The API owns incident state and the approval gate; the
worker owns the investigation. They share one PostgreSQL database rather than talking over a
queue, because at this scale a queue would add operational surface without buying anything.

```
React dashboard
   │  REST + WebSocket
FastAPI  ── incident controller, approval controller, runbook controller
   │
Agent worker (LangGraph)
   ├── metrics tool      → Prometheus
   ├── logs tool         → Loki
   ├── deployment tool   → PostgreSQL
   ├── runbook tool      → pgvector
   └── remediation tool  → demo service
   │
PostgreSQL + Redis
```

## Why these boundaries

**API and worker are separate processes.** An investigation takes tens of seconds and burns
tokens. Running it inside a request handler would tie up a worker and make timeouts a product
problem. Splitting them also means the approval gate lives in a process the agent cannot bypass.

**Connectors are a package, not agent code.** `packages/connectors/` knows how to talk to
Prometheus and Loki and nothing about LLMs. This is what lets the evaluation harness replay a
recorded incident without a model in the loop.

**The LLM sits behind an adapter.** No graph node imports a vendor SDK. Provider, model and
prompt version are configuration. Every agent run records which model and which prompt version
produced it, so evaluation can compare versions instead of guessing.

## Incident lifecycle

```
NEW → COLLECTING_EVIDENCE → ANALYZING
                               │
                    dangerous remediation?
                     no │              │ yes
                        ↓              ↓
                   COMPLETED     NEEDS_APPROVAL
                                       ↓
                            APPROVED / REJECTED
                                ↓          ↓
                            EXECUTING   REJECTED
                                ↓
                        RESOLVED / FAILED
```

Statuses are defined in `apps/api/app/models/enums.py`. `TERMINAL_INCIDENT_STATUSES` decides
whether a new alert can still be folded into an existing incident.

## Alert correlation

An alert does not always mean a new incident. The rule, implemented in
`apps/api/app/services/incident_service.py`:

> Same service **and** same alert type **and** within `CORRELATION_WINDOW_SECONDS` (default 300)
> of an alert already attached to a non-terminal incident → join that incident.

The window is checked in both directions against `alerts.started_at`, so alerts that arrive out of
order still correlate. When an alert joins an existing incident, severity ratchets upward only —
a later `low` alert never downgrades a `critical` incident.

Every correlation decision writes an `incident_events` row, which is what the timeline endpoint
renders.

## Agent graph

```
normalize_alert → plan_investigation
  → collect_metrics → collect_logs → collect_deployments → retrieve_runbooks
  → correlate_evidence → generate_hypotheses → validate_grounding
  → propose_actions → safety_check
  → requires_approval?
       no  → generate_report → END
       yes → interrupt_for_approval
                approve → execute → verify_recovery → generate_report → END
                edit    → recheck
                reject  → generate_report → END
```

Two nodes carry most of the trust weight:

- `validate_grounding` rejects any hypothesis without at least one evidence ID. A hypothesis that
  cannot cite anything does not reach the user.
- `safety_check` decides whether the proposed action needs approval, and refuses actions outside
  the allowlist regardless of what the model asked for.

The graph exits early — and says so — when the alert self-resolved, when too many tools failed,
or when the evidence does not support any hypothesis. Returning
`Insufficient evidence to determine a reliable root cause` is a success case, not a failure.

## Evidence

Everything the agent fetches becomes an `Evidence` record with a stable ID, a source type
(`metric` / `log` / `deployment` / `runbook`), a time range, a summary and the raw query used to
obtain it. Hypotheses reference those IDs. This makes two things possible: a reviewer can audit
any claim back to its source, and the evaluation harness can score citation precision
mechanically.

## Data model

Week 1 tables (implemented): `services`, `alerts`, `incidents`, `incident_alerts`,
`incident_events`, `deployment_events`.

Later tables (specified, not yet migrated): `agent_runs`, `tool_calls`, `evidence`, `hypotheses`,
`recommendations`, `approvals`, `runbooks`.

Two notes on choices made:

- IDs are UUIDs. The spec's examples show prefixed IDs like `inc_123`; adding a prefix scheme
  would mean a parse/format layer on every lookup, so it was skipped until something needs it.
- `metadata` is a reserved attribute on the SQLAlchemy declarative base, so the Python attributes
  are `event_metadata` and `deployment_metadata` while the columns stay `metadata`.

## Observability

The Copilot instruments itself, not just the services it watches:

- `http_requests_total`, `http_request_duration_seconds` — labelled with the **route template**,
  not the raw path, so UUIDs do not blow up label cardinality
- `alerts_ingested_total`, `incidents_created_total`, `alerts_correlated_total`

Agent, tool-call and token metrics land as those subsystems are built.

Logs are JSON on stdout (structlog), scraped from Docker by promtail into Loki. Traces are not
wired yet; spans will follow the graph node names so a slow investigation can be attributed to a
specific tool. API keys, authorization headers and credentials never enter a span or a log field.

### The `service_name` label is deliberately aligned across both sources

The agent has to correlate a metric spike with the log lines that explain it. That only works if
"which service" means the same thing in both systems, so:

- Prometheus does **not** set `service_name` as a target label. Both apps already emit it, and
  setting it again would push the app's own value to `exported_service_name`.
- Promtail extracts `service` from each JSON log line and promotes it to the `service_name`
  label, rather than labelling by Compose service name. The Compose name is kept separately as
  `compose_service`.

The result is that `{service_name="checkout-api"}` selects the same service in a PromQL query and
a LogQL query. Without this, the demo service would be `checkout-api` in Prometheus and
`demo-checkout-service` in Loki, and every log lookup would need a translation table.

## Testing

Tests run against in-memory SQLite via `aiosqlite` with a `StaticPool`, so the whole suite needs
no running services and finishes in seconds. The tradeoff is real: SQLite does not enforce the
Postgres types, and timezone-aware datetimes come back naive. Anything depending on Postgres
behaviour specifically — pgvector queries, JSONB operators — needs an integration test against
the real database instead.
