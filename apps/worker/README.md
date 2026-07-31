# Agent worker — week 3

The LangGraph investigation agent. Empty until week 3; see
[../../docs/ROADMAP.md](../../docs/ROADMAP.md).

```
agent/
  graph.py     Node wiring and conditional edges
  state.py     IncidentAgentState (TypedDict)
  nodes/       One module per node: collect_metrics, generate_hypotheses, safety_check, ...
  prompts/     Versioned system prompts (incident-analysis-v1, -v2, ...)
  policies/    Action allowlist and approval enforcement
main.py        Worker entrypoint
```

Two rules this package exists to enforce:

1. No node imports an LLM vendor SDK — everything goes through the provider adapter.
2. `policies/` is checked by the tool layer, not by the prompt. See
   [../../docs/SAFETY.md](../../docs/SAFETY.md).
