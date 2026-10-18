from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting, read from the environment or `.env`. Mirrors `.env.example`."""

    model_config = SettingsConfigDict(env_prefix="ANALYTICS_", env_file=".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 5600
    data_dir: Path = Path("data")
    warehouse_path: Path = Path("data/warehouse.duckdb")
    dbt_project_dir: Path = Path("dbt")
    # Read-only login on FinancePowerApp (phase 1). Empty until configured.
    finance_connection_string: str = ""
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

    @property
    def effective_jwks_uri(self) -> str:
        if self.oidc_jwks_uri:
            return self.oidc_jwks_uri
        return self.oidc_issuer.rstrip("/") + "/.well-known/jwks"


@lru_cache
def get_settings() -> Settings:
    return Settings()
