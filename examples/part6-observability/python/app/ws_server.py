"""Part 6 example — Ch23 observability ANCHOR (DRQ-028): the WebSocket
endpoint, implemented with the native `websockets` library (forked from
`examples/part3-handling-events/python`'s plain fixture-replay layout — see
that example's README for why `websockets` and not FastAPI/Starlette's
bundled WebSocket support). One handler, one channel:
`/ws/v1/bookings/{bookingId}/handling-events` (contracts/asyncapi.yaml
`channels.handlingEvents`), pushing the fixture's three `HandlingEvent`s in
order, then holding the connection open until the client disconnects.

THE FINDING this chapter exists to demonstrate: the process runs under the
`opentelemetry-instrument` wrapper (see ../Containerfile), which auto-
instruments FastAPI (`app/http_app.py`) via
`opentelemetry-instrumentation-fastapi` with zero code in this repo — but
there is no `opentelemetry-instrumentation-websockets` package, and the
`websockets` library has no OTel hook of its own. A trace that only covers
the HTTP side would never show the WS connection at all. So this module
starts a span BY HAND, with the OTel SDK tracer directly, the same
`tracer.start_as_current_span(...)` call any manual instrumentation uses —
`opentelemetry-instrument` has already configured the global TracerProvider
and OTLP exporter (from `OTEL_EXPORTER_OTLP_ENDPOINT` /
`OTEL_SERVICE_NAME`) before `app/main.py` ever imports this module, so
`trace.get_tracer(__name__)` here picks that configuration up for free —
only the span itself is manual.

One span per connection, `ws.handling-events.connection`, covers the whole
replay (the connection's initial push); `app/metrics.py`'s
`handling_events_delivered_total` counter is incremented once per frame
actually sent, inside that span, and the REQUIRED trace-id log line (see
`_log_trace_id` below — exact format, shared with the Quarkus sibling) is
emitted once, immediately after the span starts, so a log line and a Tempo
trace for the same connection can always be correlated by `otel.trace_id`.
"""
from __future__ import annotations

import logging
import os
import re

from opentelemetry import trace
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from app import mapper
from app.feed import sequence
from app.metrics import HANDLING_EVENTS_DELIVERED_TOTAL

logger = logging.getLogger("handling-events-python")
tracer = trace.get_tracer("part6-observability-python.ws_server")

# Matches the AsyncAPI channel address `/ws/v1/bookings/{bookingId}/handling-events`.
# bookingId is captured but, for this deterministic fixture-replay example,
# not used to select a different sequence — every connection on this path
# replays the same shared fixture (see app/feed.py).
_CHANNEL_PATH = re.compile(r"^/ws/v1/bookings/(?P<bookingId>[^/]+)/handling-events$")

# Identifies this process in the trace-id log line and as the span's
# `service.instance` attribute — falls back to the same value the
# Containerfile bakes into OTEL_SERVICE_NAME, so the log line is correct
# even run outside the container (e.g. under `uv run pytest` or
# `uv run python -m app.main` with no OTel env set at all).
INSTANCE_NAME = os.environ.get("OTEL_SERVICE_NAME", "part6-observability-python")

CONNECTION_SPAN_NAME = "ws.handling-events.connection"


def _log_trace_id(span: trace.Span, booking_id: str) -> None:
    """Emits the ONE required log line correlating this connection's manual
    span with its trace id, in the EXACT shape a human or a log-scraping
    verify.sh step greps for (identical on the Quarkus sibling):

        otel.trace_id=<32-hex-trace-id> span=ws.handling-events.connection bookingId=<bookingId> instance=part6-observability-python

    `format(..., "032x")` is the correct way to render an OTel trace id as
    the 32-hex-digit string Tempo's search expects — `SpanContext.trace_id`
    is a plain Python int (128 bits), and str()/hex() without the explicit
    width and padding would drop leading zero nibbles.
    """
    trace_id = format(span.get_span_context().trace_id, "032x")
    logger.info(
        "otel.trace_id=%s span=%s bookingId=%s instance=%s",
        trace_id,
        CONNECTION_SPAN_NAME,
        booking_id,
        INSTANCE_NAME,
    )


async def _replay(websocket: ServerConnection, booking_id: str) -> None:
    with tracer.start_as_current_span(CONNECTION_SPAN_NAME) as span:
        span.set_attribute("bookingId", booking_id)
        span.set_attribute("service.instance", INSTANCE_NAME)
        _log_trace_id(span, booking_id)

        try:
            for event in sequence():
                frame = mapper.to_wire_frame(event)
                await websocket.send(frame)
                HANDLING_EVENTS_DELIVERED_TOTAL.inc()
                span.add_event("handling-event.delivered", {"eventType": event.eventType.value})
            # The fixture sequence is finite; a real feed would keep the
            # loop open and `send` as new handling events are recorded.
            # Here we just hold the connection open so the channel's
            # long-lived-per-booking semantics still hold, until the client
            # disconnects — matching examples/part3-handling-events.
            await websocket.wait_closed()
        except ConnectionClosed:
            span.set_attribute("ws.disconnect_reason", "client_disconnected")
            raise


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
        await _replay(websocket, booking_id)
    except ConnectionClosed:
        logger.info("handling-events: client disconnected bookingId=%s", booking_id)


def create_server(host: str, port: int):
    """Returns the `websockets.asyncio.server.serve(...)` context manager;
    callers `async with` it (see app/main.py) to start/stop the listener.

    No auth, backpressure policy, or heartbeat tuning here — those are Part
    4's concerns (`examples/part4-connection`). This example forks Part 3's
    plain layout deliberately, so the ONLY new thing on the wire path is the
    manual span + metric this chapter is about.
    """
    return serve(handler, host, port)
