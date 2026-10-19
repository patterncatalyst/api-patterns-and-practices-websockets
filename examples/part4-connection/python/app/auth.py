"""Ch17 example — JWT auth for the handling-events feed.

HS256, shared-secret tokens (no asymmetric keys / JWKS endpoint — that's a
later, multi-service-audience concern, out of scope here). The secret comes
from `WS_JWT_SECRET` (falls back to a dev-only default so the example runs
out of the box; override it for anything beyond local dev). The token
travels as a `?token=<jwt>` query parameter on the WebSocket upgrade request
— see `contracts/asyncapi.yaml` `servers.local.bindings.ws`.

`validate_token` is called from `app/ws_server.py` right after the opening
handshake completes, before any fixture frame is streamed (see that
module's docstring for why rejection happens post-accept, via a WebSocket
close code, rather than an HTTP-level rejection in `process_request`).
"""
from __future__ import annotations

import os

import jwt

JWT_ALGORITHM = "HS256"
JWT_SECRET = os.environ.get("WS_JWT_SECRET", "dev-secret-change-me")

# Close code used for every auth failure (Ch17 convention, shared with the
# Quarkus sibling): missing token, malformed token, bad signature, and an
# expired token are all indistinguishable to an attacker probing the
# channel, so they all collapse to the same generic rejection rather than
# leaking which specific check failed.
CLOSE_CODE_AUTH_FAILED = 1008


class AuthError(Exception):
    """Raised by `validate_token` for any token that must not be accepted:
    missing, malformed, badly signed, or expired. The caller's job is simply
    to close the connection with `CLOSE_CODE_AUTH_FAILED` — the specific
    reason is logged server-side (via `str(exc)`) but never echoed back to
    the client on the wire, to avoid handing a prober a signature oracle.
    """


def validate_token(token: str | None) -> dict:
    """Validate a bearer token and return its decoded claims, or raise
    `AuthError`. Checks (in PyJWT's own order): signature, then `exp`
    (expiry) — PyJWT's `decode` performs both before returning.
    """
    if not token:
        raise AuthError("missing token")
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("expired token") from exc
    except jwt.InvalidSignatureError as exc:
        raise AuthError("bad signature") from exc
    except jwt.InvalidTokenError as exc:
        # Catch-all for every other PyJWT decode failure (malformed token,
        # wrong algorithm, not-yet-valid `nbf`, missing required claims if
        # configured, ...) — InvalidTokenError is PyJWT's common base class
        # for all of these.
        raise AuthError(f"invalid token: {exc}") from exc
