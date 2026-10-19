"""Ch9 example — the WebSocket endpoint, implemented with the native
`websockets` library (NOT FastAPI/Starlette's bundled WebSocket support —
see ../README.md and `_docs/09-python-native-websockets.md` for why).

One handler, one channel: `/ws/v1/bookings/{bookingId}/handling-events`
(contracts/asyncapi.yaml `channels.handlingEvents`). The server pushes the
fixture's HandlingEvents, in order, as soon as the WebSocket upgrade
completes, then holds the connection open — matching the contract's
"the server pushes a HandlingEvent each time one is recorded" semantics,
where a real backend would keep sending as events arrive. This fixture-
replay example has nothing further to send, so the connection just idles
until the client disconnects.
"""
from __future__ import annotations

import logging
import re

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from app.feed import sequence_as_json

logger = logging.getLogger("handling-events-python")

# Matches the AsyncAPI channel address `/ws/v1/bookings/{bookingId}/handling-events`.
# bookingId is captured but, for this deterministic fixture-replay example,
# not used to select a different sequence — every connection on this path
# replays the same shared fixture (see app/feed.py).
_CHANNEL_PATH = re.compile(r"^/ws/v1/bookings/(?P<bookingId>[^/]+)/handling-events$")


async def handler(websocket: ServerConnection) -> None:
    path = websocket.request.path
    match = _CHANNEL_PATH.match(path)
    if match is None:
        logger.warning("rejecting connection on unknown path: %s", path)
        await websocket.close(code=1008, reason="unknown channel path")
        return

    booking_id = match.group("bookingId")
    logger.info("handling-events: opening feed for bookingId=%s", booking_id)

    try:
        for frame in sequence_as_json():
            await websocket.send(frame)
        # The fixture sequence is finite; a real feed would keep the loop
        # open and `send` as new handling events are recorded. Here we just
        # hold the connection open so the channel's long-lived-per-booking
        # semantics still hold, until the client disconnects.
        await websocket.wait_closed()
    except ConnectionClosed:
        logger.info("handling-events: client disconnected bookingId=%s", booking_id)


def create_server(host: str, port: int):
    """Returns the `websockets.asyncio.server.serve(...)` context manager;
    callers `async with` it (see app/main.py) to start/stop the listener.

    The contract (contracts/asyncapi.yaml `servers.local.bindings.ws`)
    documents a `handling-events.v1` subprotocol and a `token` query
    parameter for a future auth chapter. Neither is enforced here: passing
    `subprotocols=[...]` to `serve()` makes the library REJECT any client
    that doesn't offer it (a 400 before the upgrade even completes), which
    would break plain WebSocket clients (websocat, browsers without the
    subprotocol wired up yet) for no behavior this example implements. Ch17
    (security) is where token validation lands; until then this endpoint
    accepts any upgrade to the channel path.
    """
    return serve(handler, host, port)
