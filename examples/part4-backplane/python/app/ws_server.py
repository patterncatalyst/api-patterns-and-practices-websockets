"""Part 4 example — the WebSocket endpoint, implemented with the native
`websockets` library (forked from `examples/part4-connection/python`; see
that example's README for why `websockets` and not FastAPI/Starlette's
bundled WebSocket support).

One channel, same as every Part 3/4 example:
`/ws/v1/bookings/{bookingId}/handling-events` (contracts/asyncapi.yaml
`channels.handlingEvents`). This example layers reconnect (Ch15/Ch16
`?afterEventId=` resume) and scale-out fan-out (Ch18 backplane) on top of
Part 3's plain fixture replay — see
`examples/part4-backplane/PROTOCOL.md` for the full behavior contract,
which this module (and the Quarkus sibling) implement identically.

Scope note (PROTOCOL.md "Close codes"): this example does NOT re-exercise
Part 4-connection's auth (1008)/backpressure (4290)/heartbeat-tuning
concerns — those are already covered there. This module focuses on the
backplane: 1001 (server shutdown, handled for free by the `websockets`
library's `Server.close()`), 1011 (unexpected server error), 4400
(malformed client message — this channel is still server-push-only, so any
client-sent frame is a protocol error), and 1000 (normal close).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from app import config
from app.backplane.base import Backplane
from app.feed import sequence
from app.models_generated import HandlingEvent

logger = logging.getLogger("handling-events-python")

# Matches the AsyncAPI channel address `/ws/v1/bookings/{bookingId}/handling-events`.
_CHANNEL_PATH = re.compile(r"^/ws/v1/bookings/(?P<bookingId>[^/]+)/handling-events$")

# Close codes (PROTOCOL.md "Close codes" — shared with the Quarkus sibling).
CLOSE_CODE_MALFORMED = 4400
CLOSE_CODE_UNEXPECTED_ERROR = 1011
CLOSE_CODE_UNKNOWN_CHANNEL = 1008


def _split_path_and_after_event_id(raw_path: str) -> tuple[str, str | None]:
    """`websocket.request.path` is the full request-target, e.g.
    `/ws/v1/bookings/bkg_.../handling-events?afterEventId=evt_...`. Split off
    the query string so the channel-path regex (which has no notion of a
    query string) still matches, and pull out `afterEventId`
    (PROTOCOL.md "Resume parameter").
    """
    split = urlsplit(raw_path)
    after_event_id = parse_qs(split.query).get("afterEventId", [None])[0]
    return split.path, after_event_id


def _error_envelope(message: str) -> dict:
    """The in-band JSON error shape sent before a 4400 close — same
    close-code-vs-envelope design as examples/part4-connection/python
    (Ch13): a close code alone tells a reconnect strategy THAT something
    went wrong; the envelope gives a client developer something to log.
    """
    return {"error": {"code": "BAD_REQUEST", "message": message}}


async def _reject_malformed(websocket: ServerConnection, reason: str) -> None:
    await websocket.send(json.dumps(_error_envelope(reason)))
    await websocket.close(code=CLOSE_CODE_MALFORMED, reason="malformed client message")


async def _receive_loop(websocket: ServerConnection) -> None:
    """This channel is server-push-only (the contract defines no
    client-to-server operation on `handlingEvents`), so ANY frame a client
    sends here is, by definition, a protocol error.
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
        await _reject_malformed(websocket, "this channel accepts no client-to-server messages")
        return


async def _send_event(websocket: ServerConnection, event: HandlingEvent, booking_id: str) -> None:
    await websocket.send(event.model_dump_json(exclude_none=True))
    # PROTOCOL.md "Instance identity" — exact log shape both stacks share,
    # so verify.sh can grep instance A's log for an event injected via
    # instance B's inject endpoint.
    logger.info("delivered eventId=%s bookingId=%s instance=%s", event.eventId, booking_id, config.INSTANCE_ID)


async def _deliver_loop(
    websocket: ServerConnection, backplane: Backplane, booking_id: str, after_event_id: str | None
) -> None:
    """Every connection, in every backplane mode, first gets the
    deterministic 3-event seed baseline (PROTOCOL.md "Seed events") —
    delivered directly from the fixture, not through the backplane — then
    switches to whatever `backplane.subscribe` yields for as long as the
    connection stays open. See app/backplane/kafka_backplane.py's module
    docstring for why the seed and the backplane are kept separate.
    """
    for event in sequence():
        await _send_event(websocket, event, booking_id)

    async with contextlib.aclosing(backplane.subscribe(booking_id, after_event_id)) as events:
        async for event in events:
            await _send_event(websocket, event, booking_id)


async def _run_connection(
    websocket: ServerConnection, backplane: Backplane, booking_id: str, after_event_id: str | None
) -> None:
    """Runs the outbound delivery loop and the inbound protocol-error check
    concurrently, for as long as the connection stays open. Whichever
    finishes first (the client disconnects, a protocol error closes the
    socket) wins; the other side is cancelled — same pattern as
    examples/part4-connection/python/app/ws_server.py's `_run_connection`.
    """
    deliver_task = asyncio.create_task(
        _deliver_loop(websocket, backplane, booking_id, after_event_id), name="deliver"
    )
    receive_task = asyncio.create_task(_receive_loop(websocket), name="inbound-receive")
    tasks = {deliver_task, receive_task}

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


def create_server(host: str, port: int, backplane: Backplane):
    """Returns the `websockets.asyncio.server.serve(...)` context manager;
    callers `async with` it (see app/main.py) to start/stop the listener.

    Closing the server (`async with` exiting, or a graceful shutdown) closes
    every open connection with code 1001 ("going away") by default — see
    `websockets.asyncio.server.Server.close` — the "server going away, come
    back later" signal a reconnect strategy (Ch15/16) listens for, with no
    extra code required here.
    """

    async def handler(websocket: ServerConnection) -> None:
        raw_path = websocket.request.path
        path, after_event_id = _split_path_and_after_event_id(raw_path)

        match = _CHANNEL_PATH.match(path)
        if match is None:
            logger.warning("rejecting connection on unknown path: %s", path)
            await websocket.close(code=CLOSE_CODE_UNKNOWN_CHANNEL, reason="unknown channel path")
            return

        booking_id = match.group("bookingId")
        logger.info(
            "handling-events: accepted connection bookingId=%s afterEventId=%s instance=%s",
            booking_id,
            after_event_id,
            config.INSTANCE_ID,
        )

        try:
            await _run_connection(websocket, backplane, booking_id, after_event_id)
        except ConnectionClosed:
            logger.info("handling-events: client disconnected bookingId=%s", booking_id)
        except Exception:
            logger.exception("handling-events: unexpected error bookingId=%s", booking_id)
            try:
                await websocket.close(code=CLOSE_CODE_UNEXPECTED_ERROR, reason="internal error")
            except ConnectionClosed:
                pass

    return serve(handler, host, port, ping_interval=config.WS_PING_INTERVAL_S, ping_timeout=config.WS_PING_TIMEOUT_S)
