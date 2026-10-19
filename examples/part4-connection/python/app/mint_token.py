"""Ch17 example — mint a JWT for exercising the auth-gated handling-events
feed locally, without standing up a real identity provider.

Usage (from this directory, python/):

    uv run python -m app.mint_token                        # valid, default TTL
    uv run python -m app.mint_token --mode expired
    uv run python -m app.mint_token --mode bad-sig
    uv run python -m app.mint_token --booking-id bkg_... --ttl 60

Prints the encoded token (and nothing else) to stdout, so it composes
directly into a WebSocket URL:

    TOKEN="$(uv run python -m app.mint_token)"
    websocat "ws://localhost:8081/ws/v1/bookings/bkg_.../handling-events?token=$TOKEN"

Modes:
  valid     — signed with WS_JWT_SECRET, `exp` TTL seconds in the future.
  expired   — signed with WS_JWT_SECRET, `exp` already in the past.
  bad-sig   — signed with a DIFFERENT secret, so `jwt.decode` against the
              real WS_JWT_SECRET fails signature verification.
"""
from __future__ import annotations

import argparse
import time

import jwt

from app.auth import JWT_ALGORITHM, JWT_SECRET

DEFAULT_BOOKING_ID = "bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A"
DEFAULT_TTL_SECONDS = 300


def mint(mode: str, booking_id: str, ttl_seconds: int) -> str:
    now = int(time.time())
    claims = {
        "sub": "test-client",
        "bookingId": booking_id,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    secret = JWT_SECRET

    if mode == "expired":
        claims["iat"] = now - ttl_seconds - 10
        claims["exp"] = now - 10
    elif mode == "bad-sig":
        secret = JWT_SECRET + "-wrong"
    elif mode != "valid":
        raise ValueError(f"unknown mode: {mode!r}")

    return jwt.encode(claims, secret, algorithm=JWT_ALGORITHM)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["valid", "expired", "bad-sig"], default="valid")
    parser.add_argument("--booking-id", default=DEFAULT_BOOKING_ID)
    parser.add_argument("--ttl", type=int, default=DEFAULT_TTL_SECONDS, help="seconds (valid/expired modes)")
    args = parser.parse_args(argv)

    print(mint(args.mode, args.booking_id, args.ttl))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
