"""Base settings every service inherits.

Values come from environment variables (12-factor style), so the same image
runs locally, in Docker Compose or in tests without code changes.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    service_name: str
    log_level: str = "INFO"
    tracing_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://tempo:4317"


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    database_url: str = "postgresql://f1:f1@postgres:5432/f1"
    database_pool_size: int = 5


class MessagingSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True)

    amqp_url: str = "amqp://guest:guest@rabbitmq:5672/%2F?heartbeat=30"
