"""Part 6 example — the FastAPI app.

FastAPI's job here is HTTP/app lifecycle — a liveness/readiness probe, a
small root endpoint, and the Prometheus scrape endpoint
(`handling_events_delivered_total`, DRQ-029) — run under uvicorn. The
WebSocket endpoint itself is driven by the native `websockets` library
(app/ws_server.py), not Starlette's bundled WebSocket support — see
examples/part3-handling-events/python/README.md for why. The two servers
run side by side in the same process (see app/main.py) on separate ports.

This FastAPI instance is also the half of this example that gets OTel
instrumentation FOR FREE: `opentelemetry-instrumentation-fastapi` (installed
by the `opentelemetry-instrument` wrapper, see ../Containerfile) patches
`fastapi.FastAPI.__init__` at process start, so every request this app
handles gets its own span with no code here calling an instrumentor. The WS
side has no such auto-instrumentation — see app/ws_server.py's docstring for
the manual span this example's chapter is actually about.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

app = FastAPI(
    title="observability-python",
    description=(
        "HTTP/app-lifecycle surface for the Part 6 observability example "
        "(live OTel traces + metrics into LGTM). The WebSocket feed itself "
        "is served by the native `websockets` library on a separate port "
        "— see README.md."
    ),
    version="1.0.0",
)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    return {
        "service": "observability-python",
        "channel": "/ws/v1/bookings/{bookingId}/handling-events",
        "protocol": "ws",
        "metrics": "/metrics",
    }


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
