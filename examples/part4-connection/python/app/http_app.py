"""Part 4 example — the FastAPI app.

FastAPI's job here is HTTP and app lifecycle: a liveness/readiness probe and
a small root endpoint describing the WS channel, run under uvicorn. The
WebSocket endpoint itself is driven by the native `websockets` library
(app/ws_server.py), not Starlette's bundled WebSocket support — see
examples/part3-handling-events/python/README.md for why. The two servers
run side by side in the same process (see app/main.py) on separate ports.
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="connection-concerns-python",
    description=(
        "HTTP/app-lifecycle surface for the Part 4 connection-concerns "
        "example (backpressure, error handling, heartbeats, JWT auth). The "
        "WebSocket feed itself is served by the native `websockets` library "
        "on a separate port — see README.md."
    ),
    version="1.0.0",
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {
        "service": "connection-concerns-python",
        "channel": "/ws/v1/bookings/{bookingId}/handling-events",
        "protocol": "ws",
        "auth": "JWT (HS256) via ?token= query parameter",
    }
