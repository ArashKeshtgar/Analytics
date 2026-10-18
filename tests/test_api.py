from fastapi.testclient import TestClient

from analytics import __version__
from analytics.api import create_app

client = TestClient(create_app())


def test_healthz() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version() -> None:
    response = client.get("/api/version")
    assert response.status_code == 200
    assert response.json() == {"name": "analytics", "version": __version__}
