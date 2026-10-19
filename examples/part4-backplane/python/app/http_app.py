"""Part 4 example — the FastAPI app.

FastAPI's job here is HTTP and app lifecycle: a liveness/readiness probe, a
small root endpoint describing the WS channel, and the
`/internal/bookings/{bookingId}/handling-events` inject endpoint
(PROTOCOL.md "Inject endpoint") that tests and Ch18 use to publish an event
through the active backplane. The WebSocket endpoint itself is driven by the
native `websockets` library (app/ws_server.py), not Starlette's bundled
WebSocket support — see examples/part3-handling-events/python/README.md for
why. The two servers run side by side in the same process (see app/main.py)
on separate ports, sharing one `Backplane` instance via `app.state.backplane`.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request

from app.models_generated import HandlingEvent

logger = logging.getLogger("handling-events-python")

app = FastAPI(
    title="backplane-python",
    description=(
        "HTTP/app-lifecycle surface for the Part 4 backplane example "
        "(reconnect + scale-out fan-out over Kafka/Redis). The WebSocket "
        "feed itself is served by the native `websockets` library on a "
        "separate port — see README.md."
    ),
    version="1.0.0",
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {
        "service": "backplane-python",
        "channel": "/ws/v1/bookings/{bookingId}/handling-events",
        "protocol": "ws",
        "resume": "?afterEventId=<eventId>",
        "inject": "POST /internal/bookings/{bookingId}/handling-events",
    }


@app.post("/internal/bookings/{bookingId}/handling-events", status_code=202)
async def inject_handling_event(bookingId: str, event: HandlingEvent, request: Request) -> dict:
    """PROTOCOL.md "Inject endpoint" — publishes `event` to the active
    backplane (kafka topic / redis channel) in broker modes, or delivers it
    to this instance's local connections in stateless mode. Internal/demo
    endpoint, not part of the public AsyncAPI contract (no channel/operation
    for it in contracts/asyncapi.yaml).
    """
    backplane = request.app.state.backplane
    await backplane.publish(bookingId, event)
    logger.info("injected eventId=%s bookingId=%s instance=%s", event.eventId, bookingId, request.app.state.instance_id)
    return {"status": "accepted", "eventId": event.eventId, "bookingId": bookingId}
