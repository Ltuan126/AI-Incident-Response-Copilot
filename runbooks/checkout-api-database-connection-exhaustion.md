---
service: checkout-api
incident_type: database_connection_exhaustion
owner_team: payments-team
---

# Checkout API — database connection exhaustion

## Symptoms

- `database connection timeout` entries in application logs
- `db_connections_active` approaching `db_connections_max`
- Checkout request latency rising, then 500s
- Error rate climbs within minutes of a deployment

## Likely causes

1. A recent deployment introduced a connection leak (connections opened per request and never
   returned to the pool).
2. Connection pool sized below current traffic.
3. A slow query holding connections open longer than usual.

## Recommended actions

1. Check `deployment_events` for a release in the 30 minutes before the error rate rose.
2. Compare `db_connections_active` before and after that deployment.
3. If the climb starts at the deployment boundary, roll back to the previous version.
4. If there was no recent deployment, look for a slow query and consider raising pool size.

## Rollback

Rolling back `checkout-api` is safe: it is stateless and carries no forward-only migrations.
Rollback requires human approval.
