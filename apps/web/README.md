# Dashboard — week 4

React + TypeScript + Vite + Tailwind + TanStack Query.

Screens:

- **Dashboard** — active, critical and resolved incident counts, pending approvals, agent success
  rate, average analysis latency
- **Incident list** — severity, service, status, started-at, agent status, confidence; filterable
  by service, severity, status and time range
- **Incident detail** — summary, timeline, metrics charts, relevant logs, deployment history,
  hypotheses with their supporting evidence, recommended actions, approval panel, final report
- **Approval screen** — action, target service, parameters, risk level, reasoning, evidence and
  confidence, with approve / edit / reject

Agent progress streams over WebSocket:

```json
{
  "type": "agent_progress",
  "node": "collect_logs",
  "message": "Searching application logs...",
  "timestamp": "2026-07-30T14:34:10Z"
}
```
