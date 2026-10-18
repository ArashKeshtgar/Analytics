"""ClinicHub access tokens: who is calling and what they may see.

The token is checked (RS256 signature against ClinicHub's JWKS, issuer, expiry, and the audience
when one is configured); nothing from it is logged. Permissions and the clinic come from the
claims `permission` and `clinic_slug`.
"""

from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientConnectionError, PyJWKClientError

from analytics.settings import Settings

DASHBOARD_VIEW = "analytics:dashboard.view"
GROUP_VIEW = "analytics:group.view"
MODELS_VIEW = "analytics:models.view"


class Unauthorized(Exception):
    """The token is missing or not acceptable: answered 401."""


class Unavailable(Exception):
    """ClinicHub's keys could not be fetched: answered 503."""


class Forbidden(Exception):
    """A valid token without the permission for this: answered 403."""


@dataclass(frozen=True)
class User:
    sub: str
    name: str | None
    clinic_slug: str | None
    permissions: frozenset[str]


@dataclass(frozen=True)
class Scope:
    """Which businesses a user's queries may touch."""

    group: bool
    clinic_slug: str | None


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return value.split()
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self._issuer = settings.oidc_issuer
        self._audience = settings.oidc_audience or None
        self._jwks = PyJWKClient(settings.effective_jwks_uri, timeout=5)

    def verify(self, token: str) -> User:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                leeway=60,
                options={
                    "require": ["exp", "iss", "sub"],
                    "verify_aud": self._audience is not None,
                },
            )
        except PyJWKClientConnectionError as exc:
            raise Unavailable from exc
        except (InvalidTokenError, PyJWKClientError) as exc:
            raise Unauthorized(type(exc).__name__) from exc
        name = claims.get("name")
        clinic = claims.get("clinic_slug")
        return User(
            sub=str(claims["sub"]),
            name=name if isinstance(name, str) else None,
            clinic_slug=clinic if isinstance(clinic, str) and clinic else None,
            permissions=frozenset(_as_list(claims.get("permission"))),
        )


def scope_for(user: User) -> Scope:
    """`group.view` sees every business; `dashboard.view` only the clinic in the token."""
    if GROUP_VIEW in user.permissions:
        return Scope(group=True, clinic_slug=None)
    if DASHBOARD_VIEW in user.permissions and user.clinic_slug:
        return Scope(group=False, clinic_slug=user.clinic_slug)
    raise Forbidden
