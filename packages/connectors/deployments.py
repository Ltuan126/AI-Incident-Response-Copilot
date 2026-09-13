"""PostgreSQL deployment-history connector."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.models import DeploymentEvent
from apps.api.app.models.enums import EvidenceSourceType
from packages.connectors.models import ConnectorResult


class DeploymentConnector:
    async def query_range(
        self,
        session: AsyncSession,
        service_id: uuid.UUID,
        start: datetime,
        end: datetime,
    ) -> ConnectorResult:
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Connector timestamps must include a timezone")
        if end < start:
            raise ValueError("Deployment query end must not precede start")
        start = start.astimezone(UTC)
        end = end.astimezone(UTC)
        rows = await session.scalars(
            select(DeploymentEvent)
            .where(
                DeploymentEvent.service_id == service_id,
                DeploymentEvent.deployed_at >= start,
                DeploymentEvent.deployed_at <= end,
            )
            .order_by(DeploymentEvent.deployed_at.asc(), DeploymentEvent.id.asc())
        )
        deployments = [self._serialize(row) for row in rows]
        query_params: dict[str, Any] = {
            "service_id": str(service_id),
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        return ConnectorResult(
            source_type=EvidenceSourceType.DEPLOYMENT,
            source_name="postgresql",
            query="deployment_events by service_id and deployed_at range",
            query_params=query_params,
            summary=(
                f"Deployment history returned {len(deployments)} records."
                if deployments
                else "No deployment records were found in the incident window."
            ),
            raw_data={"deployments": deployments},
            time_range_start=start,
            time_range_end=end,
            collected_at=datetime.now(UTC),
        )

    @staticmethod
    def _serialize(row: DeploymentEvent) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "service_id": str(row.service_id),
            "version": row.version,
            "previous_version": row.previous_version,
            "commit_sha": row.commit_sha,
            "deployed_by": row.deployed_by,
            "status": str(row.status),
            "deployed_at": row.deployed_at.isoformat(),
            "metadata": row.deployment_metadata,
        }
