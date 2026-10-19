"""Part 4 example — the WebSocket endpoint, implemented with the native
`websockets` library (forked from `examples/part3-handling-events/python`;
see that example's README/`_docs/09-python-native-websockets.md` for why
`websockets` and not FastAPI/Starlette's bundled WebSocket support).

One handler, one channel:
`/ws/v1/bookings/{bookingId}/handling-events` (contracts/asyncapi.yaml
`channels.handlingEvents`) — but this example layers FOUR connection
concerns on top of Part 3's plain fixture replay:

  Ch17 auth       — reject an unauthenticated upgrade with close code 1008.
  Ch12 backpressure — bound the outbound path (app/outbound.py) so a slow
                      client gets closed (4290) instead of growing memory
                      without bound.
  Ch13 errors     — an invalid client frame gets an in-band JSON error
                      envelope, then a close (4400); an unexpected server-
                      side exception closes 1011.
  Ch14 heartbeats — delegated entirely to the `websockets` library's own
                      ping/pong (see `create_server` below); a silent/dead
                      peer is detected and closed within the configured
                      window without any code in this module.

Close-code-vs-envelope design choice (Ch13): a close code alone tells the
client THAT something went wrong and roughly what category (standard codes
only have ~15 values; this channel adds 4400/4290 for its own two cases),
but carries no human-readable detail and arrives after the connection is
already gone — too late for the client to log anything but "it closed".
An in-band JSON error envelope, sent BEFORE the close frame, lets the
server explain WHAT was wrong with the specific message (useful for a
client developer debugging their own framing bug) while the close code
still tells automated reconnect logic WHY the socket ended, cheaply,
without parsing a payload. This module always does both for a client-
caused protocol error (envelope then 4400) and relies on the close code
alone for cases that aren't about a specific bad message (auth: 1008,
backpressure: 4290, internal error: 1011) since those don't have a
single offending frame to annotate.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from app import auth
from app.feed import sequence_as_json
from app.outbound import CLOSE_CODE_SLOW_CONSUMER, OutboundQueue, SlowConsumerError

logger = logging.getLogger("handling-events-python")

# Matches the AsyncAPI channel address `/ws/v1/bookings/{bookingId}/handling-events`.
# bookingId is captured but, for this deterministic fixture-replay example,
# not used to select a different sequence — every connection on this path
# replays the same shared fixture (see app/feed.py). Matched against the
# PATH component only — `websocket.request.path` includes the query string
# (`?token=...`), which is split off first (see `_split_path_and_token`).
_CHANNEL_PATH = re.compile(r"^/ws/v1/bookings/(?P<bookingId>[^/]+)/handling-events$")

# Close codes (Part 4 convention, shared with the Quarkus sibling — see
# README.md's "Close codes" table).
CLOSE_CODE_MALFORMED = 4400
CLOSE_CODE_UNEXPECTED_ERROR = 1011
CLOSE_CODE_UNKNOWN_CHANNEL = 1008  # reused for "not this channel" too


def _split_path_and_token(raw_path: str) -> tuple[str, str | None]:
    """`websocket.request.path` is the full request-target, e.g.
    `/ws/v1/bookings/bkg_.../handling-events?token=abc`. Split off the query
    string so the channel-path regex (which has no notion of a query
    string) still matches, and pull out the `token` parameter per
    `contracts/asyncapi.yaml` `servers.local.bindings.ws`.
    """
    split = urlsplit(raw_path)
    token = parse_qs(split.query).get("token", [None])[0]
    return split.path, token


def _error_envelope(message: str) -> dict:
    """The in-band JSON error shape sent before a 4400 close — see the
    "Close-code-vs-envelope" note in this module's docstring. `BAD_REQUEST`
    is the only code this channel emits today (every client-sent frame is
    invalid, since the contract defines no client-to-server operation on
    this channel); a richer channel with multiple failure modes would add
    more `code` values here.
    """
    return {"error": {"code": "BAD_REQUEST", "message": message}}


async def _reject_malformed(websocket: ServerConnection, reason: str) -> None:
    await websocket.send(json.dumps(_error_envelope(reason)))
    await websocket.close(code=CLOSE_CODE_MALFORMED, reason="malformed client message")


async def _receive_loop(websocket: ServerConnection) -> None:
    """Ch13 example — this channel is server-push-only (the contract defines
    no client-to-server operation on `handlingEvents`), so ANY frame a
    client sends here is, by definition, a protocol error: there is no
    valid shape to accept. The first inbound frame — whatever it is — gets
    the error envelope + 4400 treatment. Binary frames are rejected the same
    way (no binary framing is defined on this channel either).
    """
    async for message in websocket:
        if not isinstance(message, str):
            await _reject_malformed(websocket, "binary frames are not supported on this channel")
            return
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as exc:
            await _reject_malformed(websocket, f"invalid JSON: {exc}")
            return
        if not isinstance(parsed, dict):
            await _reject_malformed(websocket, "expected a JSON object")
            return
        await _reject_malformed(
            websocket, "this channel accepts no client-to-server messages"
        )
        return


async def _run_connection(websocket: ServerConnection, booking_id: str) -> None:
    """Runs the outbound replay (Ch12 `OutboundQueue.drain`) and the inbound
    protocol-error check (Ch13 `_receive_loop`) concurrently, for as long as
    the connection stays open. Whichever finishes first (the client
    disconnects, a protocol error closes the socket, or a backpressure
    violation raises) wins; the other side is cancelled.
    """
    outbound = OutboundQueue()
    for frame in sequence_as_json():
        outbound.enqueue(frame)

    drain_task = asyncio.create_task(outbound.drain(websocket), name="outbound-drain")
    receive_task = asyncio.create_task(_receive_loop(websocket), name="inbound-receive")
    tasks = {drain_task, receive_task}

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        logger.info("handling-events: connection loop ended bookingId=%s", booking_id)


async def handler(websocket: ServerConnection) -> None:
    raw_path = websocket.request.path
    path, token = _split_path_and_token(raw_path)

    match = _CHANNEL_PATH.match(path)
    if match is None:
        logger.warning("rejecting connection on unknown path: %s", path)
        await websocket.close(code=CLOSE_CODE_UNKNOWN_CHANNEL, reason="unknown channel path")
        return

    booking_id = match.group("bookingId")

    # Ch17: validate the token BEFORE streaming anything. Rejection happens
    # post-accept (a WebSocket close with an application code) rather than
    # an HTTP-level `process_request` rejection: the `websockets` library's
    # `process_request` hook runs before the opening handshake completes and
    # can only return an HTTP response (no application close code exists
    # yet, since there is no WebSocket connection yet). Closing with 1008
    # immediately after accepting — and before sending a single fixture
    # frame — delivers the same "no data, unambiguous rejection" outcome
    # (see `examples/_lib/lib.sh`'s `assert_ws_rejected`, which treats a
    # non-101 response and an immediate post-upgrade close identically) while
    # keeping the application-level close code the auth failure deserves.
    try:
        auth.validate_token(token)
    except auth.AuthError as exc:
        logger.warning("rejecting connection bookingId=%s: %s", booking_id, exc)
        await websocket.close(code=auth.CLOSE_CODE_AUTH_FAILED, reason="authentication failed")
        return

    logger.info("handling-events: opening feed for bookingId=%s", booking_id)

    try:
        await _run_connection(websocket, booking_id)
    except SlowConsumerError as exc:
        logger.warning("closing slow consumer bookingId=%s: %s", booking_id, exc)
        try:
            await websocket.close(code=CLOSE_CODE_SLOW_CONSUMER, reason="slow consumer")
        except ConnectionClosed:
            pass
    except ConnectionClosed:
        logger.info("handling-events: client disconnected bookingId=%s", booking_id)
    except Exception:
        logger.exception("handling-events: unexpected error bookingId=%s", booking_id)
        try:
            await websocket.close(code=CLOSE_CODE_UNEXPECTED_ERROR, reason="internal error")
        except ConnectionClosed:
            pass


def create_server(host: str, port: int):
    """Returns the `websockets.asyncio.server.serve(...)` context manager;
    callers `async with` it (see app/main.py) to start/stop the listener.

    Ch14 heartbeats: `ping_interval`/`ping_timeout` are handed straight to
    the `websockets` library, which sends a ping every `ping_interval`
    seconds and closes the connection if no pong arrives within
    `ping_timeout` seconds of that ping — no code in this module implements
    liveness detection; it is entirely the library's responsibility. Both
    are env-overridable (`WS_PING_INTERVAL_S` / `WS_PING_TIMEOUT_S`) so a
    verify.sh can shrink the window to something a test can wait out.

    Ch15/Ch16 (reconnect) note: closing the server (`async with` exiting, or
    a graceful shutdown) closes every open connection with code 1001
    ("going away") by default — see `websockets.asyncio.server.Server.close`
    — which is exactly the "server going away, come back later" signal a
    reconnect strategy (Ch15/16) listens for, with no extra code required
    here either.

    The contract (`contracts/asyncapi.yaml` `servers.local.bindings.ws`)
    documents a `handling-events.v1` subprotocol; it is not enforced here
    for the same reason as Part 3's example — requiring it would reject
    plain clients (websocat, browsers without the subprotocol wired up)
    for no behavior this example implements beyond auth.
    """
    ping_interval = float(os.environ.get("WS_PING_INTERVAL_S", "20"))
    ping_timeout = float(os.environ.get("WS_PING_TIMEOUT_S", "20"))
    return serve(handler, host, port, ping_interval=ping_interval, ping_timeout=ping_timeout)
