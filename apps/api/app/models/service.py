import uuid

from sqlalchemy import String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.app.models.base import Base, TimestampMixin


class Service(TimestampMixin, Base):
    __tablename__ = "services"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    environment: Mapped[str] = mapped_column(String(32), default="staging")
    current_version: Mapped[str | None] = mapped_column(String(64), default=None)
    owner_team: Mapped[str | None] = mapped_column(String(128), default=None)
