import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base
from apps.api.app.models.enums import DeploymentStatus


class DeploymentEvent(Base):
    __tablename__ = "deployment_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("services.id"), index=True)
    version: Mapped[str] = mapped_column(String(64))
    previous_version: Mapped[str | None] = mapped_column(String(64), default=None)
    commit_sha: Mapped[str | None] = mapped_column(String(64), default=None)
    deployed_by: Mapped[str | None] = mapped_column(String(128), default=None)
    status: Mapped[DeploymentStatus] = mapped_column(String(32), default=DeploymentStatus.SUCCEEDED)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    deployment_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
