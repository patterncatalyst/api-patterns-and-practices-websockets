"""Part 5 example — the FastAPI app.

FastAPI's job here is HTTP and app lifecycle: a liveness/readiness probe and
a small root endpoint describing the WS channel and its two subprotocols,
run under uvicorn. The WebSocket endpoint itself is driven by the native
`websockets` library (app/ws_server.py), not Starlette's bundled WebSocket
support — see examples/part3-handling-events/python/README.md for why. The
two servers run side by side in the same process (see app/main.py) on
separate ports.
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="performance-python",
    description=(
        "HTTP/app-lifecycle surface for the Part 5 performance example "
        "(JSON text vs Protobuf binary encoding, negotiated via "
        "Sec-WebSocket-Protocol). The WebSocket feed itself is served by "
        "the native `websockets` library on a separate port — see README.md."
    ),
    version="1.0.0",
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {
        "service": "performance-python",
        "channel": "/ws/v1/bookings/{bookingId}/handling-events",
        "protocol": "ws",
        "subprotocols": {
            "handling-events.v1": "JSON text frames (equivalent to +json)",
            "handling-events.v1+json": "JSON text frames (default)",
            "handling-events.v1+protobuf": "Protobuf binary frames",
        },
    }
