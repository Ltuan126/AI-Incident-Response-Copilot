# Roadmap

Six weeks, ordered so that data comes before intelligence. The agent is built in week 3, not
week 1, because an agent reasoning over data you have not verified produces confident nonsense.

> Not without good data → the agent cannot analyse well.
> Not without evaluation → you cannot tell whether it analyses well.
> Not without approval enforcement → it is not safe to act.

## Week 1 — Foundation and simulator ✅

Monorepo, FastAPI, PostgreSQL, Alembic. Models for service, alert, incident and deployment. Alert
ingestion with correlation. Demo checkout service with five fault modes. Incident simulator.
Prometheus instrumentation. Unit and integration tests. Docker Compose. CI.

**Deliverable:** POST a simulator scenario → alert created → incident in the database →
Prometheus scraping metrics → logs reaching Loki.

## Week 2 — Data connectors

Completed foundation:

- Step 1: traffic generator → Prometheus alert rules → Alertmanager webhook → incident, without
  the simulator creating an alert directly.
- Step 2: investigation/evidence models and migration, read APIs, tool audit storage, citation
  validation, transaction rollback tests, and a PostgreSQL integration/migration CI job.

**Next:** implement the actual connectors below. The evidence APIs currently return empty lists
until a collector writes data; neither collection nor LLM analysis runs automatically yet.

Prometheus, Loki and deployment connectors. The shared `Evidence` model. Tool timeouts, bounded
retries and the tool-call audit log. Seeded deployment history. Integration tests against real
Postgres. An API to inspect collected evidence.

**Deliverable:** given an incident ID, fetch metrics, logs and deployments and persist them as
evidence rows.

## Week 3 — Agent and RAG

LangGraph state and nodes. System prompt with versioning. Structured output schema. Runbook
ingestion into pgvector. Retrieval tool. Evidence-validation node. Insufficient-evidence
behaviour. Token usage and latency recorded per run.

**Deliverable:** an incident produces hypotheses where every hypothesis cites evidence IDs, plus
a recommended action.

## Week 4 — Human-in-the-loop and frontend

LangGraph checkpointer and interrupt before mutating actions. Approval API with approve / edit /
reject. Action-hash validation. Simulated remediation. React incident list, detail view, approval
panel, WebSocket progress and timeline.

**Deliverable:** agent proposes a rollback → workflow pauses → human approves → workflow resumes →
simulator rolls back → incident resolves.

## Week 5 — Evaluation and observability

Thirty evaluation cases. Rule-based baseline. Scorers for tool selection, root cause, evidence
grounding and safety. MLflow tracing. Grafana dashboards. Cost metrics. At least two prompt
versions compared.

**Deliverable:** an evaluation report covering root-cause accuracy, tool accuracy, hallucination,
safety, latency and token cost.

## Week 6 — Production polish

Health and readiness endpoints, error handling, rate limiting, secret management, README,
architecture diagram, API documentation, demo video, Postman collection, one-command startup.

**Deliverable:**

```bash
git clone ... && cp .env.example .env && docker compose up --build
```

then demo the whole incident workflow.

## Definition of done

- Compose brings up the entire stack
- At least four incident scenarios
- The agent uses at least four tools
- Every hypothesis references evidence
- The agent detects insufficient evidence
- Every mutating action requires approval, with no API path that bypasses it
- Incident timeline and dashboard exist
- Evaluation dataset exists, with a baseline-vs-agent comparison report
- Metrics, logs and traces are emitted
- CI runs the tests automatically
- README covers architecture and demo instructions
- A complete demo video exists
- No API key or secret is committed

## Out of scope for the MVP

Real Kubernetes control, arbitrary shell execution, automatic data deletion, automatic source
edits, auto-merging pull requests, large-scale distributed tracing analysis, fine-tuning, and
remediation without approval.

Deferred to a later phase: real GitHub deployment connector, Kubernetes connector, Slack and
email notifications, multi-agent workflows, model routing, automated postmortems, continuous
evaluation.
