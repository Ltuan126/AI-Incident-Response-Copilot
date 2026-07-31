# Safety model

The premise: an LLM with production access is a liability unless the things it can do are
constrained by code rather than by instructions.

## What the model is allowed to do

1. Read from approved connectors (Prometheus, Loki, deployment history, runbooks).
2. Propose an action from the allowlist.
3. Call a mutating tool **only** after a valid human approval exists.
4. Execute exactly the action that was approved — not a variation of it.

## Action allowlist

```python
ALLOWED_ACTIONS = {
    "simulated_restart",
    "simulated_rollback",
    "simulated_scale",
    "create_incident_note",
}
```

Explicitly not tools, and therefore unreachable regardless of prompt:

`arbitrary_shell`, `delete_database`, `execute_sql`, `modify_secret`, `disable_security`,
`remove_logs`, `run_user_generated_code`.

The model cannot pass a shell command to any tool. Tool inputs are Pydantic models with typed
fields, not free-form strings that get interpolated somewhere.

## Approval integrity

The failure mode this defends against: a human approves "roll back to v1.4.1", and something —
a retry, a re-plan, a tampered request — changes the parameters before execution.

When an approval request is created, the backend hashes:

```
action_type + service_name + parameters + agent_run_id
```

At execution time it recomputes the hash and compares. A mismatch aborts.

## Enforcement lives in the tool layer

Before a mutating tool runs, it checks all of:

- an approval record exists for this recommendation
- the approval belongs to **this** agent run
- the approval has not expired
- the decision was `approve`
- the requested action matches the approved action hash
- the action is in the allowlist

Any failure aborts. The system prompt states the same rules, but the prompt is a hint to the
model, not the control. Prompt injection through a log line or a runbook must not be able to
widen what the agent can execute.

## Actions that always require approval

Rollback, service restart, scaling, configuration change, creating an issue or pull request,
sending an external notification — and any write operation at all.

A reviewer sees the action, target service, parameters, risk level, the agent's reasoning, the
supporting evidence and the confidence score, then chooses **approve**, **edit** or **reject**.
Edit re-runs the safety check against the modified action; it does not inherit the original
approval.

## Blast radius in this MVP

Remediation calls the bundled demo service only. There is no Kubernetes client, no cloud
credential, and no path from an approved action to real infrastructure. That is a deliberate
scope boundary, not an unfinished feature.

## Secrets

- No API key, password, authorization header, database credential or raw personal data is written
  to a log field, a trace span or an evidence record.
- Configuration comes from the environment. `.env` is gitignored; `.env.example` carries no real
  values.
- Tool outputs are structured, and connectors never return raw credentials to the model.

## What the agent must refuse to do

State a technical conclusion without evidence. If the tools return nothing usable, the required
answer is `Insufficient evidence to determine a reliable root cause`. Fabricating a cause to
complete the workflow is the single worst failure this system can have, because it is the one a
tired on-call engineer at 3am is least likely to catch. The evaluation suite scores this
explicitly as insufficient-evidence detection, and the target is not optional.
