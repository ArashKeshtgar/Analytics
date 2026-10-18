"""Shared fixtures: a warehouse built from the synthetic source, and a stand-in for ClinicHub."""

import json
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from analytics.extract import extract_finance
from analytics.settings import Settings
from analytics.sources import DuckDbSource
from analytics.warehouse import build
from tests import synthetic_source

ISSUER = "http://localhost:5301/"
KEY_ID = "test-key"

GROUP = "analytics:group.view"
DASHBOARD = "analytics:dashboard.view"
MODELS = "analytics:models.view"


def make_settings(root: Path, **extra: Any) -> Settings:
    return Settings(
        data_dir=root / "data",
        warehouse_path=root / "data" / "warehouse.duckdb",
        dbt_project_dir=Path("dbt"),
        _env_file=None,  # type: ignore[call-arg]
        **extra,
    )


class FakeClinicHub:
    """Serves a JWKS on localhost and signs tokens the way ClinicHub (OpenIddict) does."""

    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})
        body = json.dumps({"keys": [jwk]}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args: Any) -> None:
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        self.jwks_uri = f"http://127.0.0.1:{self._server.server_port}/.well-known/jwks"

    def close(self) -> None:
        self._server.shutdown()

    def token(self, *, key: Any = None, kid: str = KEY_ID, **claims: Any) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": ISSUER,
            "sub": "user-1",
            "name": "Test User",
            "iat": now,
            "exp": now + 300,
            **claims,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        return jwt.encode(
            payload,
            key or self.key,
            algorithm="RS256",
            headers={"kid": kid, "typ": "at+jwt"},
        )


@pytest.fixture(scope="session")
def clinichub() -> Iterator[FakeClinicHub]:
    hub = FakeClinicHub()
    yield hub
    hub.close()


@pytest.fixture(scope="session")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Settings]:
    """Warehouse built from the synthetic source, extracted on two days (see test_pipeline)."""
    settings = make_settings(tmp_path_factory.mktemp("pipeline"))
    for day in (datetime(2026, 10, 31, 12, tzinfo=UTC), datetime(2026, 11, 15, 12, tzinfo=UTC)):
        extract_finance(DuckDbSource(synthetic_source.create()), settings, now=day)
    assert build(settings) == 0
    yield settings


@pytest.fixture(scope="session")
def auth_settings(built: Settings, clinichub: FakeClinicHub) -> Settings:
    return built.model_copy(update={"oidc_issuer": ISSUER, "oidc_jwks_uri": clinichub.jwks_uri})


@pytest.fixture
def group_headers(clinichub: FakeClinicHub) -> dict[str, str]:
    return {"Authorization": "Bearer " + clinichub.token(permission=[GROUP])}


Headers = Callable[..., dict[str, str]]
