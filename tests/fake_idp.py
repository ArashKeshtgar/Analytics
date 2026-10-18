"""A stand-in for ClinicHub's sign-in (OpenIddict), for tests of the dashboard.

Authorization code flow with PKCE (S256 is checked: a wrong verifier is refused), discovery, JWKS,
RS256 access tokens with `typ: at+jwt` and the claims the API reads (`permission`, `clinic_slug`,
`name`). It signs in whoever `current_user` names, without asking: the tests choose the user with
GET /__user?name=... (and GET /__lifetime?seconds=N for the next tokens)
"""

import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

KEY_ID = "idp-key"
# As ClinicHub sends them to the `analytics` client: its own keys without the prefix.
GROUP = "group.view"
DASHBOARD = "dashboard.view"
MODELS = "models.view"

USERS: dict[str, dict[str, Any]] = {
    "group": {"sub": "u-group", "name": "Grace Group", "permission": [GROUP, MODELS]},
    "clinic": {
        "sub": "u-clinic",
        "name": "Casey Clinic",
        "permission": [DASHBOARD],
        "clinic_slug": "harbourview",
    },
    "nobody": {"sub": "u-nobody", "name": "Nobody", "permission": []},
}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class FakeIdP:
    def __init__(self, port: int = 5301, web_origin: str = "http://localhost:5601") -> None:
        self.port = port
        self.issuer = f"http://localhost:{port}/"
        self.web_origin = web_origin
        self.current_user = "group"
        self.token_lifetime = 300
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(RSAAlgorithm.to_jwk(self._key.public_key()))
        jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})
        self._jwks = {"keys": [jwk]}
        self._codes: dict[str, dict[str, Any]] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self.port = self._server.server_port
        self.issuer = f"http://localhost:{self.port}/"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()

    @property
    def jwks_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/.well-known/jwks"

    def _sign(self, claims: dict[str, Any], typ: str) -> str:
        return jwt.encode(claims, self._key, algorithm="RS256", headers={"kid": KEY_ID, "typ": typ})

    def _tokens(self, code: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time())
        user = USERS[code["user"]]
        base = {"iss": self.issuer, "iat": now, "exp": now + self.token_lifetime}
        access = {**base, **user, "aud": "analytics", "client_id": code["client_id"]}
        ident = {
            **base,
            "sub": user["sub"],
            "name": user["name"],
            "aud": code["client_id"],
            "nonce": code["nonce"],
        }
        return {
            "access_token": self._sign(access, "at+jwt"),
            "id_token": self._sign(ident, "JWT"),
            "token_type": "Bearer",
            "expires_in": self.token_lifetime,
            "scope": code["scope"],
        }

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        idp = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(
                self, status: int, body: Any = None, headers: dict[str, str] | None = None
            ) -> None:
                self.send_response(status)
                self.send_header("Access-Control-Allow-Origin", idp.web_origin)
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                payload = b"" if body is None else json.dumps(body).encode()
                if body is not None:
                    self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_OPTIONS(self) -> None:
                self._send(204, headers={"Access-Control-Allow-Methods": "GET, POST"})

            def do_GET(self) -> None:
                url = urlparse(self.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path == "/.well-known/openid-configuration":
                    self._send(
                        200,
                        {
                            "issuer": idp.issuer,
                            "authorization_endpoint": f"{idp.issuer}connect/authorize",
                            "token_endpoint": f"{idp.issuer}connect/token",
                            "jwks_uri": f"{idp.issuer}.well-known/jwks",
                            "response_types_supported": ["code"],
                            "grant_types_supported": ["authorization_code"],
                            "code_challenge_methods_supported": ["S256"],
                            "subject_types_supported": ["public"],
                            "id_token_signing_alg_values_supported": ["RS256"],
                        },
                    )
                elif url.path == "/.well-known/jwks":
                    self._send(200, idp._jwks)
                elif url.path == "/__lifetime":
                    idp.token_lifetime = int(query["seconds"])
                    self._send(204)
                elif url.path == "/__user":
                    idp.current_user = query["name"]
                    self._send(204)
                elif url.path == "/connect/authorize":
                    if (
                        query.get("response_type") != "code"
                        or query.get("code_challenge_method") != "S256"
                    ):
                        self._send(400, {"error": "invalid_request"})
                        return
                    code = secrets.token_urlsafe(24)
                    idp._codes[code] = {
                        "challenge": query["code_challenge"],
                        "redirect_uri": query["redirect_uri"],
                        "client_id": query["client_id"],
                        "nonce": query.get("nonce", ""),
                        "scope": query.get("scope", ""),
                        "user": idp.current_user,
                    }
                    back = {"code": code, "state": query["state"], "iss": idp.issuer.rstrip("/")}
                    self.send_response(302)
                    self.send_header("Location", f"{query['redirect_uri']}?{urlencode(back)}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._send(404, {"error": "not_found"})

            def do_POST(self) -> None:
                if urlparse(self.path).path != "/connect/token":
                    self._send(404, {"error": "not_found"})
                    return
                length = int(self.headers.get("Content-Length", 0))
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
                code = idp._codes.pop(form.get("code", ""), None)
                challenge = _b64url(hashlib.sha256(form.get("code_verifier", "").encode()).digest())
                if (
                    form.get("grant_type") != "authorization_code"
                    or code is None
                    or code["redirect_uri"] != form.get("redirect_uri")
                    or code["client_id"] != form.get("client_id")
                    or code["challenge"] != challenge
                ):
                    self._send(400, {"error": "invalid_grant"})
                    return
                self._send(200, idp._tokens(code), {"Cache-Control": "no-store"})

        return Handler
