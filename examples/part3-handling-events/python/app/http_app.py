"""Ch9 example — the FastAPI app.

FastAPI's job here is HTTP and app lifecycle: a liveness/readiness probe and
a small root endpoint describing the WS channel, run under uvicorn. It is
deliberately NOT where the WebSocket endpoint lives — the raw `websockets`
library (app/ws_server.py) drives that connection, since Starlette's bundled
WebSocket support is exactly what this chapter is contrasting against (see
../README.md). The two servers run side by side in the same process (see
app/main.py) on separate ports.
"""
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(
    title="handling-events-python",
    description=(
        "HTTP/app-lifecycle surface for the Ch9 handling-events example. "
        "The WebSocket feed itself is served by the native `websockets` "
        "library on a separate port — see README.md."
    ),
    version="1.0.0",
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {
        "service": "handling-events-python",
        "channel": "/ws/v1/bookings/{bookingId}/handling-events",
        "protocol": "ws",
    }
