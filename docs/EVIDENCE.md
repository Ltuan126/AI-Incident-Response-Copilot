# Evidence persistence and connector collection — steps 2–3

This is the data contract for the connectors and the agent. The three monitoring/deployment
connectors and the collection endpoint are now implemented; the agent that reasons over their
results is the next step.
Migration `0002` adds six tables without altering or deleting the existing incident tables.

## Stored records

| Table | Responsibility |
| --- | --- |
| `agent_runs` | One investigation of an incident; status, provider/model, required prompt version, timestamps, token counts and errors. |
| `tool_calls` | Completed call audit: name, input/output JSON, success/failure, error, start and finish. |
| `evidence` | Stable UUID; incident/run/tool provenance; source type/name; query/parameters; raw JSON, summary, time range and collection timestamp. |
| `hypotheses` | Candidate root cause, summary and confidence in [0, 1]. |
| `hypothesis_evidence` | Citation links, constrained to evidence in the hypothesis's own run. |
| `recommendations` | A proposal tied to a grounded hypothesis; action, parameters, rationale, risk and approval requirement. |

Evidence supports metrics, logs, deployments and runbooks. `raw_data` must be a JSON object; wrap
a source array in an object such as `{"results": [...]}`. Preserve the source response here and
put the human-readable interpretation in `summary`. Queries and nested JSON strings are not
trimmed or rewritten. `query_params` records the parameters needed to reproduce the request;
source connectors define the specific PromQL, LogQL and deployment-query conventions. A successful
source query becomes one evidence row. A timeout or invalid response is recorded as a failed tool
call while the other sources continue; no fabricated evidence is written for a failed source.

The collected timestamp is required (defaults to UTC now at input creation). Time-range boundaries
are optional, but must be supplied together and be ordered. All input timestamps require timezones.
Empty/whitespace-only descriptions, non-JSON values and non-finite numbers are rejected.

## Internal write boundary

Use `apps.api.app.services.investigation_service` with the Pydantic inputs in
`apps.api.app.schemas.investigation`:

1. `create_agent_run(session, incident_id, AgentRunCreate(...))` creates a `pending` record and
   `agent_run_created` timeline entry. It does not run analysis or change incident status.
2. `record_tool_call(session, run_id, ToolCallCreate(...))` stores a completed attempt. A failed
   call requires an error message; a successful call cannot contain an error message.
3. `record_evidence(session, run_id, EvidenceCreate(...))` derives incident ownership from the run
   and emits `evidence_collected`. An optional tool ID must refer to a successful call in this run.
4. `record_hypothesis(session, run_id, HypothesisCreate(...))` requires at least one existing
   evidence ID from this run. Duplicate IDs collapse to a single citation link.
5. `record_recommendation(session, run_id, RecommendationCreate(...))` requires a hypothesis from
   this run that already has citations. It only stores a proposal; it cannot execute anything.

All helpers **flush but do not commit**. Use a caller-owned `async with session.begin():` transaction
to save or roll back a collection and its timeline together. Missing incidents/runs raise
`InvestigationNotFoundError`; invalid tool/citation/hypothesis references raise
`InvalidEvidenceReferenceError`. Database integrity errors must also cause transaction rollback.
Connectors should finish network calls before opening a short write transaction where possible.

Composite foreign keys enforce incident/run/tool/citation ownership even for direct database
writes. The minimum-one-citation and successful-tool checks are service-level rules, not database
triggers. These records must therefore be written through the service. Citation validity does not
prove semantic support; an agent will still need to validate what the evidence actually says.

Recommendations are constrained to `status="proposed"` and `requires_approval=true`. Those fields
cannot be supplied through the create schema. This is **not** the future human-approval gate:
there is no approval, action execution, agent lifecycle runner or automatic recovery verification.

## Connector collection endpoint

`POST /api/v1/incidents/{incident_id}/collect-evidence` starts a bounded collection pass. The body
is optional; defaults are a five-minute lookback, 15-second Prometheus step and 100 Loki lines.

```bash
curl -X POST \
  "http://localhost:8000/api/v1/incidents/INCIDENT_UUID/collect-evidence" \
  -H 'Content-Type: application/json' \
  -d '{"lookback_seconds":300,"step_seconds":15,"log_limit":100}'
```

The response contains the `agent_run_id`, UTC time range, one status per source and the evidence
IDs that were stored. `status="completed"` means at least one source produced evidence. If all
three sources fail, the run is `insufficient_evidence`, with failure details in the tool-call audit
endpoint. HTTP source calls use `CONNECTOR_TIMEOUT_SECONDS` (default 5) and at most
`CONNECTOR_MAX_RETRIES` (default 2, capped at 3); 4xx responses are not retried. Loki receives
nanosecond Unix bounds, while Prometheus receives RFC3339 bounds and a step.

The endpoint is intentionally synchronous for this MVP and has no authentication. In production,
queue the collection pass behind a worker and protect the endpoint before exposing monitoring
data.

## Inspect records

```bash
curl "http://localhost:8000/api/v1/incidents/INCIDENT_UUID/evidence"
curl "http://localhost:8000/api/v1/incidents/INCIDENT_UUID/evidence?source_type=log&limit=20&offset=0"
curl "http://localhost:8000/api/v1/incidents/INCIDENT_UUID/evidence/EVIDENCE_UUID"
curl "http://localhost:8000/api/v1/incidents/INCIDENT_UUID/agent-runs"
curl "http://localhost:8000/api/v1/agent-runs/RUN_UUID/tool-calls"
```

Replace placeholders with actual UUIDs. Full filters and response fields are in [API.md](API.md).
New incidents legitimately have no evidence until collection is triggered. The synthetic fixtures
in `apps/api/tests/test_evidence.py` and `test_connectors.py` cover the write/read path; they do not
pretend fixtures are live source data.

## Migration and safety

After pulling this change, rebuild the API image and run:

```bash
docker compose up -d --build api
docker compose exec api alembic upgrade head
```

Do not delete the PostgreSQL volume. Back up important data before any schema migration.
Downgrading to `0001` intentionally drops all six investigation tables and their data; only the
older incident/service tables and timeline remain. Downgrade tests run only in disposable schemas.

These are local-demo APIs without authentication/RBAC. Evidence and tool payloads may contain
sensitive source data: do not expose these endpoints publicly. Connectors must redact secrets and
bound payload sizes before persistence. There are currently no retention/deletion
APIs, encryption features or production access controls for investigation records.
