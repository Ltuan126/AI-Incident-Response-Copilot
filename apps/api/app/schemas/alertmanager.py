from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AlertmanagerAlert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: datetime = Field(alias="startsAt")
    ends_at: datetime | None = Field(default=None, alias="endsAt")
    generator_url: str | None = Field(default=None, alias="generatorURL")
    fingerprint: str | None = None


class AlertmanagerWebhook(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str | None = None
    status: str
    receiver: str | None = None
    group_labels: dict[str, str] = Field(default_factory=dict, alias="groupLabels")
    common_labels: dict[str, str] = Field(default_factory=dict, alias="commonLabels")
    common_annotations: dict[str, str] = Field(default_factory=dict, alias="commonAnnotations")
    alerts: list[AlertmanagerAlert] = Field(default_factory=list)


class AlertmanagerWebhookResponse(BaseModel):
    received: int
    ingested: int
    duplicates: int
    ignored: int
    incident_ids: list[str]
