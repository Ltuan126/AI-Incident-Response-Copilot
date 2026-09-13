from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://copilot:copilot@localhost:5432/copilot"
    redis_url: str = "redis://localhost:6379/0"

    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"
    demo_service_url: str = "http://localhost:8001"
    connector_timeout_seconds: float = 5.0
    connector_max_retries: int = 2

    correlation_window_seconds: int = 300
    prompt_version: str = "incident-analysis-v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
