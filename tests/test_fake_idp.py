"""The fake sign-in must behave like the real one where the dashboard depends on it."""

import base64
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator

import pytest

from analytics.auth import TokenVerifier
from tests.conftest import make_settings
from tests.fake_idp import DASHBOARD, FakeIdP


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


@pytest.fixture(scope="module")
def idp() -> Iterator[FakeIdP]:
    server = FakeIdP(port=0)
    server.start()
    yield server
    server.stop()


def authorize(idp: FakeIdP, verifier: str) -> str:
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    query = urllib.parse.urlencode(
        {
            "client_id": "analytics",
            "redirect_uri": "http://localhost:5601/signin-oidc",
            "response_type": "code",
            "scope": "openid",
            "state": "s1",
            "nonce": "n1",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(f"http://127.0.0.1:{idp.port}/connect/authorize?{query}")
    except urllib.error.HTTPError as e:
        assert e.code == 302
        location = urllib.parse.urlparse(e.headers["Location"])
        return urllib.parse.parse_qs(location.query)["code"][0]
    raise AssertionError("no redirect")


def token(idp: FakeIdP, code: str, verifier: str) -> tuple[int, dict[str, object]]:
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": "analytics",
            "redirect_uri": "http://localhost:5601/signin-oidc",
            "code_verifier": verifier,
        }
    ).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{idp.port}/connect/token", data=body)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_right_verifier_gets_tokens_the_api_accepts(idp: FakeIdP, tmp_path: object) -> None:
    idp.current_user = "clinic"
    code = authorize(idp, "v" * 50)
    status, tokens = token(idp, code, "v" * 50)
    assert status == 200 and tokens["token_type"] == "Bearer"

    settings = make_settings(tmp_path, oidc_issuer=idp.issuer, oidc_jwks_uri=idp.jwks_uri)  # type: ignore[arg-type]
    user = TokenVerifier(settings).verify(str(tokens["access_token"]))
    assert user.clinic_slug == "harbourview" and DASHBOARD in user.permissions


def test_a_wrong_verifier_is_refused_and_a_code_works_once(idp: FakeIdP) -> None:
    code = authorize(idp, "a" * 50)
    assert token(idp, code, "b" * 50)[0] == 400
    # the code is spent by the failed attempt
    assert token(idp, code, "a" * 50)[0] == 400
    code = authorize(idp, "a" * 50)
    assert token(idp, code, "a" * 50)[0] == 200
    assert token(idp, code, "a" * 50)[0] == 400


def test_discovery_names_its_own_issuer(idp: FakeIdP) -> None:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{idp.port}/.well-known/openid-configuration"
    ) as r:
        metadata = json.loads(r.read())
    assert metadata["issuer"] == idp.issuer
    assert metadata["code_challenge_methods_supported"] == ["S256"]
