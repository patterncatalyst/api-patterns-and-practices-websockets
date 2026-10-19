"""Part 5 example — the WebSocket endpoint, implemented with the native
`websockets` library (forked from `examples/part4-connection/python`).

One channel, TWO wire encodings of the exact same message
(`contracts/asyncapi.yaml` `channels.handlingEvents`,
`contracts/handling-event.proto` — DRQ-025): a client picks between them by
offering a `Sec-WebSocket-Protocol` on the upgrade request (DRQ-026):

  handling-events.v1            JSON text frames (equivalent to +json below)
  handling-events.v1+json       JSON text frames — the default
  handling-events.v1+protobuf   Protobuf binary frames

This example drops Part 4's connection concerns (backpressure, in-band error
envelopes, heartbeats, JWT auth) to isolate the encoding comparison Ch19/20
are about: it replays the shared fixture on open, in whichever encoding was
negotiated, then stays open (no further pushes, no client-to-server
operation — same server-push-only contract as every other example in this
series).
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from app.feed import sequence
from app.mapper import to_proto

logger = logging.getLogger("handling-events-python")

# Matches the AsyncAPI channel address `/ws/v1/bookings/{bookingId}/handling-events`.
# bookingId is captured but, for this deterministic fixture-replay example,
# not used to select a different sequence — every connection on this path
# replays the same shared fixture (see app/feed.py).
_CHANNEL_PATH = re.compile(r"^/ws/v1/bookings/(?P<bookingId>[^/]+)/handling-events$")

CLOSE_CODE_UNKNOWN_CHANNEL = 1008
CLOSE_CODE_UNEXPECTED_ERROR = 1011

# Subprotocol family (contracts/asyncapi.yaml servers.local.bindings.ws,
# DRQ-026). Order here is the server's declared PREFERENCE when a client
# offers more than one — bare v1, then the explicit +json alias, then
# +protobuf LAST — matching the Quarkus sibling's own declared order
# (`quarkus.websockets-next.server.supported-subprotocols` in
# ../quarkus/src/main/resources/application.properties) so both stacks pick
# the same encoding given the same multi-value offer: JSON wins if a client
# offers both, since it's earlier in this list.
SUBPROTOCOL_V1 = "handling-events.v1"
SUBPROTOCOL_JSON = "handling-events.v1+json"
SUBPROTOCOL_PROTOBUF = "handling-events.v1+protobuf"
SUPPORTED_SUBPROTOCOLS = (SUBPROTOCOL_V1, SUBPROTOCOL_JSON, SUBPROTOCOL_PROTOBUF)


def _select_subprotocol(connection: ServerConnection, subprotocols) -> str | None:
    """Reproduces the `websockets` library's own default negotiation
    algorithm (`ServerProtocol.select_subprotocol`: first value in the
    server's declared list — `SUPPORTED_SUBPROTOCOLS` — that the client also
    offered) with ONE change: a client that offers no subprotocol at all
    gets `None` back instead of an aborted handshake (HTTP 400). The
    default algorithm abort-on-nothing-offered is wrong for this channel —
    a client offering no subprotocol (websocat with no `--protocol`, a plain
    browser WebSocket, ...) must still connect and get the JSON encoding,
    the explicit "none -> JSON" case DRQ-026 calls out. Returning `None`
    here accepts the connection with no `Sec-WebSocket-Protocol` response
    header, same as if the server declared no subprotocols at all.
    """
    offered = set(subprotocols)
    for candidate in SUPPORTED_SUBPROTOCOLS:
        if candidate in offered:
            return candidate
    return None


def _is_protobuf(websocket: ServerConnection) -> bool:
    return websocket.subprotocol == SUBPROTOCOL_PROTOBUF


async def _replay(websocket: ServerConnection) -> None:
    """Pushes the fixture's three HandlingEvents, each as either a Protobuf
    BINARY frame (`ws.send(bytes)`) or a JSON TEXT frame (`ws.send(str)`),
    depending on the subprotocol negotiated for this connection
    (`websocket.subprotocol`, set by `_select_subprotocol` during the
    handshake) — never both on the same connection.
    """
    protobuf = _is_protobuf(websocket)
    logger.info(
        "handling-events: replaying fixture subprotocol=%s encoding=%s",
        websocket.subprotocol or "(none)",
        "protobuf" if protobuf else "json",
    )
    for event in sequence():
        if protobuf:
            await websocket.send(to_proto(event).SerializeToString())
        else:
            await websocket.send(event.model_dump_json(exclude_none=True))


async def handler(websocket: ServerConnection) -> None:
    raw_path = websocket.request.path
    path = urlsplit(raw_path).path

    match = _CHANNEL_PATH.match(path)
    if match is None:
        logger.warning("rejecting connection on unknown path: %s", path)
        await websocket.close(code=CLOSE_CODE_UNKNOWN_CHANNEL, reason="unknown channel path")
        return

    booking_id = match.group("bookingId")
    logger.info("handling-events: opening feed for bookingId=%s", booking_id)

    try:
        await _replay(websocket)
        # Server-push-only channel: after the replay, stay open (no further
        # pushes, no client-to-server operation defined on this contract)
        # until the client disconnects or the server shuts down.
        await websocket.wait_closed()
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
    `subprotocols` advertises the three supported values; `select_subprotocol`
    overrides the library's default negotiation to also accept a client that
    offers none at all — see `_select_subprotocol`.
    """
    return serve(
        handler,
        host,
        port,
        subprotocols=SUPPORTED_SUBPROTOCOLS,
        select_subprotocol=_select_subprotocol,
    )
