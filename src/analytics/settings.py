from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Docker secrets: one file per setting, named like its variable
# (ANALYTICS_FINANCE_CONNECTION_STRING). The environment and `.env` win over them; none outside
# a container.
SECRETS_DIR = Path("/run/secrets")


class Settings(BaseSettings):
    """Every setting, read from the environment, `.env` or a secret file. Mirrors `.env.example`."""

    model_config = SettingsConfigDict(
        env_prefix="ANALYTICS_",
        env_file=".env",
        extra="ignore",
        secrets_dir=SECRETS_DIR if SECRETS_DIR.is_dir() else None,
    )

    host: str = "127.0.0.1"
    port: int = 5600
    data_dir: Path = Path("data")
    warehouse_path: Path = Path("data/warehouse.duckdb")
    dbt_project_dir: Path = Path("dbt")
    # Read-only login on FinancePowerApp (phase 1). Empty until configured.
    finance_connection_string: str = ""
    # LabFlow's warehouse through its read-only login (monthly lab volumes). Empty: not read.
    labflow_dw_connection_string: str = ""
    # ClinicHub sign-in (phase 2).
    oidc_issuer: str = "http://localhost:5301/"
    # Empty: {issuer}.well-known/jwks
    oidc_jwks_uri: str = ""
    # Empty: the audience of the token is not checked (not known yet, see docs/sources.md).
    oidc_audience: str = ""
    # The dashboard (phase 3) calls the API from this origin.
    web_origin: str = "http://localhost:5601"
    # RabbitMQ feed from IntegrationHub (phase 4).
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_exchange: str = "clinical.events"
    # The hub declares this durable queue too (both without arguments).
    rabbitmq_queue: str = "analytics.clinical-events"
    # A batch is written, then acknowledged: at most this many events, or this many seconds.
    consume_batch_size: int = 200
    consume_flush_seconds: float = 5.0
    # `analytics schedule` (phase 6): how often `analytics run` runs, e.g. 30m, 6h, 1d.
    run_every: str = "6h"
    # Told when a run fails and when it works again (JSON POST, `text` and details). Empty: nobody.
    alert_webhook_url: str = ""
    # A run that keeps failing is told again after this many hours.
    alert_repeat_hours: int = 24
    # Finance extracts older than this many days keep only the last one of each day (what the
    # open-item history is built from); 0 keeps everything.
    keep_extract_days: int = 14
    # Run reports kept (newest first, and always the last good one); 0 keeps everything.
    keep_reports: int = 200

    @property
    def effective_jwks_uri(self) -> str:
        if self.oidc_jwks_uri:
            return self.oidc_jwks_uri
        return self.oidc_issuer.rstrip("/") + "/.well-known/jwks"


@lru_cache
def get_settings() -> Settings:
    return Settings()
