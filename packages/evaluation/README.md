# Evaluation — week 5

```
datasets/    30+ deterministic incident cases (JSON)
scorers/     tool selection, root cause, evidence grounding, safety
run_eval.py  Runner: executes a system against a dataset and emits a report
```

Four systems are scored on the same dataset — rule-based baseline, LLM without tools,
tool-calling agent, and agent + runbook RAG — so the report answers whether the complexity is
worth it rather than assuming it.

Metrics, thresholds and the deployment gate are defined in
[../../docs/EVALUATION.md](../../docs/EVALUATION.md).
