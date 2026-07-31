"""Seed services and deployment history so the agent has something to correlate against.

Idempotent: re-running updates existing services rather than duplicating them.

    python scripts/seed_data.py
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from apps.api.app.core.db import SessionFactory
from apps.api.app.models import DeploymentEvent, DeploymentStatus, Service

SERVICES = [
    ("checkout-api", "staging", "v1.4.1", "payments-team"),
    ("payment-api", "staging", "v2.8.0", "payments-team"),
    ("auth-api", "staging", "v3.1.5", "identity-team"),
]

DEPLOYMENTS = [
    ("checkout-api", "v1.4.1", "v1.4.0", "a91f3c2", "ci-bot", timedelta(days=3)),
    ("checkout-api", "v1.4.0", "v1.3.9", "77bd10e", "ci-bot", timedelta(days=9)),
    ("payment-api", "v2.8.0", "v2.7.4", "3ce8891", "ci-bot", timedelta(days=1)),
    ("auth-api", "v3.1.5", "v3.1.4", "b220af7", "ci-bot", timedelta(days=6)),
]


async def main() -> None:
    now = datetime.now(UTC)
    async with SessionFactory() as session:
        services: dict[str, Service] = {}
        for name, environment, version, team in SERVICES:
            service = await session.scalar(select(Service).where(Service.name == name))
            if service is None:
                service = Service(name=name)
                session.add(service)
            service.environment = environment
            service.current_version = version
            service.owner_team = team
            services[name] = service
        await session.flush()

        for name, version, previous, sha, actor, ago in DEPLOYMENTS:
            service = services[name]
            exists = await session.scalar(
                select(DeploymentEvent).where(
                    DeploymentEvent.service_id == service.id, DeploymentEvent.version == version
                )
            )
            if exists is not None:
                continue
            session.add(
                DeploymentEvent(
                    service_id=service.id,
                    version=version,
                    previous_version=previous,
                    commit_sha=sha,
                    deployed_by=actor,
                    status=DeploymentStatus.SUCCEEDED,
                    deployed_at=now - ago,
                )
            )

        await session.commit()

    print(f"Seeded {len(SERVICES)} services and up to {len(DEPLOYMENTS)} deployment events.")


if __name__ == "__main__":
    asyncio.run(main())
