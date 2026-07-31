---
service: checkout-api
incident_type: high_latency
owner_team: payments-team
---

# Checkout API — high latency

## Symptoms

- P95 `http_request_duration_seconds` above 1s while error rate stays normal
- Request rate flat or lower than usual
- No spike in 5xx responses

## Likely causes

1. A downstream dependency (payment provider) is slow.
2. CPU saturation on the service.
3. A newly deployed code path doing extra synchronous work.

## Recommended actions

1. Compare latency against request rate — flat traffic with rising latency points downstream.
2. Check CPU and memory before blaming the dependency.
3. Check for a deployment in the preceding 30 minutes.
4. If a deployment lines up with the latency change, propose a rollback.

## Escalation

If latency is downstream and no deployment correlates, page the payments-team on-call rather
than rolling back.
