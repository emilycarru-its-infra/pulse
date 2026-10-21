"""Who may post health and alerts.

- The health push and the cloud alarm route carry an Entra ID app-only access token for this
  API's application. The token's signature is checked against the tenant's published keys, and
  so are its issuer, audience and expiry, and it must hold the route's own app role: Pulse.Ingest
  for the push, Pulse.Alerts for alarms. A header naming a caller proves nothing, so nothing else
  is trusted.
- Webhooks from monitoring systems that cannot obtain such a token present a shared key in
  X-Pulse-Key, compared in constant time. Each sender has its own key.
"""

from __future__ import annotations

import hmac
from functools import lru_cache

INGEST_ROLE = "Pulse.Ingest"
ALERTS_ROLE = "Pulse.Alerts"


class Unauthorized(Exception):
    pass


@lru_cache(maxsize=4)
def _jwks(tenant: str):
    import jwt

    return jwt.PyJWKClient(
        f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
        cache_keys=True,
        lifespan=3600,
    )


def bearer(header: str | None) -> str:
    if not header or not header.lower().startswith("bearer "):
        raise Unauthorized("missing bearer token")
    token = header[7:].strip()
    if not token:
        raise Unauthorized("missing bearer token")
    return token


def check_ingest_token(
    token: str, tenant: str, audiences: list[str], role: str = INGEST_ROLE, key=None
) -> dict:
    """The token's claims if it is a valid app-only token for one of `audiences` from `tenant`
    holding `role`; raises Unauthorized otherwise. `key` replaces the tenant's keys in tests.
    """
    import jwt

    if not tenant or not audiences:
        raise Unauthorized("ingest is not configured")
    try:
        signing_key = (
            key
            if key is not None
            else _jwks(tenant).get_signing_key_from_jwt(token).key
        )
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=audiences,
            options={"require": ["exp", "iat", "iss", "aud"]},
            leeway=60,
        )
    except Exception as e:  # noqa: BLE001 - every failure is the same answer
        raise Unauthorized("invalid token") from e
    issuers = {
        f"https://login.microsoftonline.com/{tenant}/v2.0",
        f"https://sts.windows.net/{tenant}/",
    }
    if claims.get("iss") not in issuers or claims.get("tid", tenant) != tenant:
        raise Unauthorized("wrong issuer")
    if role not in (claims.get("roles") or []):
        raise Unauthorized("missing role")
    # An app-only token: no user in it.
    if claims.get("idtyp", "app") != "app" or claims.get("scp"):
        raise Unauthorized("not an application token")
    return claims


def check_key(presented: str | None, expected: str | None) -> None:
    """Raises Unauthorized unless both are set and equal, compared in constant time."""
    if not expected or len(expected) < 24:
        raise Unauthorized("webhook is not configured")
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise Unauthorized("wrong key")
