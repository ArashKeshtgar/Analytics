"""Sign-in: who gets in, and which clinic's numbers they see.

Synthetic warehouse (see tests/synthetic_source.py): Harbourview (code HV, clinic_slug
`harbourview`) and a lab (code LAB, no clinic slug). Tokens are signed by FakeClinicHub.
"""

import socket
import time
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from analytics.api import create_app
from analytics.settings import Settings
from tests.conftest import DASHBOARD, GROUP, ISSUER, MODELS, FakeClinicHub

FINANCE_URLS = [
    "/api/finance/revenue",
    "/api/finance/ohip-collection",
    "/api/finance/aging",
]


@pytest.fixture
def app_client(auth_settings: Settings) -> TestClient:
    return TestClient(create_app(auth_settings))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def clinic_headers(hub: FakeClinicHub, slug: str = "harbourview", **claims: Any) -> dict[str, str]:
    return bearer(hub.token(permission=[DASHBOARD], clinic_slug=slug, **claims))


# ---- who gets in -------------------------------------------------------------------------------


def test_health_and_version_need_no_token(app_client: TestClient) -> None:
    assert app_client.get("/healthz").status_code == 200
    assert app_client.get("/api/version").status_code == 200


@pytest.mark.parametrize("url", [*FINANCE_URLS, "/api/me"])
def test_no_token_is_401(app_client: TestClient, url: str) -> None:
    response = app_client.get(url)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def bad_tokens(hub: FakeClinicHub) -> dict[str, str]:
    now = int(time.time())
    good = {"permission": [GROUP]}
    return {
        "garbage": "abc.def.ghi",
        "wrong issuer": hub.token(iss="http://evil.example/", **good),
        "expired": hub.token(iat=now - 900, exp=now - 600, **good),
        "other key": hub.token(key=hub.other_key, **good),
        "unknown kid": hub.token(kid="not-published", **good),
        "no expiry": jwt.encode(
            {"iss": ISSUER, "sub": "u", "permission": [GROUP]},
            hub.key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        ),
        "hs256": jwt.encode(
            {"iss": ISSUER, "sub": "u", "exp": now + 300, "permission": [GROUP]},
            "a-shared-secret-of-sufficient-length-1234",
            algorithm="HS256",
            headers={"kid": "test-key"},
        ),
        "alg none": jwt.encode(
            {"iss": ISSUER, "sub": "u", "exp": now + 300, "permission": [GROUP]},
            None,
            algorithm="none",
            headers={"kid": "test-key"},
        ),
    }


def test_bad_tokens_are_401(app_client: TestClient, clinichub: FakeClinicHub) -> None:
    for name, token in bad_tokens(clinichub).items():
        response = app_client.get("/api/finance/revenue", headers=bearer(token))
        assert response.status_code == 401, name
        assert response.headers["WWW-Authenticate"] == "Bearer", name
        assert token not in response.text, name


def test_a_basic_header_is_401(app_client: TestClient) -> None:
    response = app_client.get("/api/finance/revenue", headers={"Authorization": "Basic dTpw"})
    assert response.status_code == 401


def test_audience_is_checked_when_configured(
    auth_settings: Settings, clinichub: FakeClinicHub
) -> None:
    client = TestClient(create_app(auth_settings.model_copy(update={"oidc_audience": "analytics"})))
    ok = bearer(clinichub.token(permission=[GROUP], aud="analytics"))
    assert client.get("/api/finance/revenue", headers=ok).status_code == 200
    for aud in ("labflow", None):
        token = clinichub.token(permission=[GROUP], aud=aud)
        assert client.get("/api/finance/revenue", headers=bearer(token)).status_code == 401


def test_audience_is_ignored_when_not_configured(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    token = clinichub.token(permission=[GROUP], aud="whatever")
    assert app_client.get("/api/finance/revenue", headers=bearer(token)).status_code == 200


def test_unreachable_keys_are_503_not_401(
    auth_settings: Settings, clinichub: FakeClinicHub
) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    settings = auth_settings.model_copy(update={"oidc_jwks_uri": f"http://127.0.0.1:{port}/jwks"})
    client = TestClient(create_app(settings))
    token = clinichub.token(permission=[GROUP])
    assert client.get("/api/finance/revenue", headers=bearer(token)).status_code == 503


# ---- what they may do --------------------------------------------------------------------------


@pytest.mark.parametrize("url", FINANCE_URLS)
def test_a_valid_token_without_a_finance_permission_is_403(
    app_client: TestClient, clinichub: FakeClinicHub, url: str
) -> None:
    for claims in ({}, {"permission": [MODELS]}, {"permission": ["labflow:results.view"]}):
        response = app_client.get(url, headers=bearer(clinichub.token(**claims)))
        assert response.status_code == 403, claims


def test_clinic_viewer_without_a_clinic_is_403(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    token = clinichub.token(permission=[DASHBOARD])
    assert app_client.get("/api/finance/revenue", headers=bearer(token)).status_code == 403


def test_clinic_viewer_sees_only_their_clinic(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    headers = clinic_headers(clinichub)

    revenue = app_client.get("/api/finance/revenue", headers=headers).json()
    assert {r["month"]: r["revenue"] for r in revenue} == {"2026-09-01": 150.0, "2026-10-01": 160.0}

    by_business = app_client.get(
        "/api/finance/revenue", params={"groupBy": "business"}, headers=headers
    ).json()
    assert by_business == [{"business": "HV", "revenue": 310.0}]

    ohip = app_client.get("/api/finance/ohip-collection", headers=headers).json()
    assert {r["business"] for r in ohip} == {"HV"}

    aging = app_client.get("/api/finance/aging", headers=headers).json()
    assert aging and {r["business"] for r in aging} == {"HV"}
    payables = app_client.get("/api/finance/aging", params={"side": "payable"}, headers=headers)
    assert {r["business"] for r in payables.json()} == {"HV"}


def test_clinic_viewer_asking_for_another_business_gets_nothing(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    headers = clinic_headers(clinichub)
    for url in FINANCE_URLS:
        response = app_client.get(url, params={"business": "LAB"}, headers=headers)
        assert response.status_code == 200
        assert response.json() == [], url


def test_clinic_viewer_may_name_their_own_business_by_code_or_slug(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    headers = clinic_headers(clinichub)
    by_code = app_client.get("/api/finance/revenue", params={"business": "HV"}, headers=headers)
    by_slug = app_client.get(
        "/api/finance/revenue", params={"business": "harbourview"}, headers=headers
    )
    assert by_code.json() == by_slug.json() != []


def test_a_clinic_slug_matches_regardless_of_case(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    response = app_client.get(
        "/api/finance/revenue", headers=clinic_headers(clinichub, slug="HarbourView")
    )
    assert response.json() != []


def test_a_clinic_without_a_business_sees_nothing(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    headers = clinic_headers(clinichub, slug="lakeshore")
    for url in FINANCE_URLS:
        assert app_client.get(url, headers=headers).json() == [], url


def test_group_viewer_sees_every_business(app_client: TestClient, clinichub: FakeClinicHub) -> None:
    headers = bearer(clinichub.token(permission=[GROUP]))
    by_business = app_client.get(
        "/api/finance/revenue", params={"groupBy": "business"}, headers=headers
    ).json()
    assert by_business == [
        {"business": "HV", "revenue": 310.0},
        {"business": "LAB", "revenue": 70.0},
    ]


def test_group_permission_wins_over_a_clinic(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    token = clinichub.token(permission=[DASHBOARD, GROUP], clinic_slug="harbourview")
    by_business = app_client.get(
        "/api/finance/revenue", params={"groupBy": "business"}, headers=bearer(token)
    ).json()
    assert [r["business"] for r in by_business] == ["HV", "LAB"]


def test_permissions_may_be_one_string(app_client: TestClient, clinichub: FakeClinicHub) -> None:
    token = clinichub.token(permission=DASHBOARD, clinic_slug="harbourview")
    assert app_client.get("/api/finance/revenue", headers=bearer(token)).json() != []
    both = clinichub.token(permission=f"{GROUP} {MODELS}")
    assert app_client.get("/api/finance/revenue", headers=bearer(both)).status_code == 200


def test_permissions_as_clinichub_sends_them_without_the_prefix(
    app_client: TestClient, clinichub: FakeClinicHub
) -> None:
    # What ClinicHub puts in a token for the `analytics` client: its own keys, prefix removed.
    token = clinichub.token(permission="dashboard.view", clinic_slug="harbourview")
    me = app_client.get("/api/me", headers=bearer(token)).json()
    assert me["scope"] == "clinic" and me["permissions"] == [DASHBOARD]
    assert app_client.get("/api/finance/revenue", headers=bearer(token)).status_code == 200
    group = clinichub.token(permission=["dashboard.view", "group.view", "models.view"])
    assert app_client.get("/api/me", headers=bearer(group)).json()["scope"] == "group"
    # A key of another application, prefixed or not, is no Analytics permission.
    other = clinichub.token(permission=["labflow:admin", "admin"], clinic_slug="harbourview")
    assert app_client.get("/api/me", headers=bearer(other)).json()["scope"] == "none"


# ---- /api/me and CORS --------------------------------------------------------------------------


def test_me_says_who_and_what(app_client: TestClient, clinichub: FakeClinicHub) -> None:
    clinic = app_client.get("/api/me", headers=clinic_headers(clinichub, name="Dr Synthetic"))
    assert clinic.json() == {
        "name": "Dr Synthetic",
        "clinicSlug": "harbourview",
        "permissions": [DASHBOARD],
        "scope": "clinic",
    }
    group = app_client.get("/api/me", headers=bearer(clinichub.token(permission=[GROUP, MODELS])))
    assert group.json()["scope"] == "group" and group.json()["permissions"] == [GROUP, MODELS]
    none = app_client.get("/api/me", headers=bearer(clinichub.token()))
    assert none.status_code == 200 and none.json()["scope"] == "none"


def test_cors_allows_only_the_dashboard_origin(app_client: TestClient) -> None:
    ask = {
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization",
    }
    allowed = app_client.options(
        "/api/finance/revenue", headers={"Origin": "http://localhost:5601", **ask}
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5601"
    other = app_client.options(
        "/api/finance/revenue", headers={"Origin": "http://evil.example", **ask}
    )
    assert "access-control-allow-origin" not in other.headers
