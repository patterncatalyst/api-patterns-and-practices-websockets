"""Part 6 example — entrypoint. Runs two listeners in one process, on the
same asyncio event loop (forked from examples/part4-connection/python/app/main.py):

  - the native `websockets` server (app/ws_server.py) on WS_HOST:WS_PORT
    (default 0.0.0.0:8081), serving
    `/ws/v1/bookings/{bookingId}/handling-events` with a MANUAL
    `ws.handling-events.connection` OTel span and a
    `handling_events_delivered_total` counter per delivered HandlingEvent
    (see that module's docstring for why the span is manual).
  - a FastAPI app (app/http_app.py) on HTTP_HOST:HTTP_PORT (default
    0.0.0.0:8082) via uvicorn, for HTTP/app lifecycle (`/healthz`, `/`) and
    the Prometheus scrape endpoint (`/metrics`).

Run under the `opentelemetry-instrument` wrapper (see Containerfile) so the
FastAPI side gets zero-code tracing and the global TracerProvider/OTLP
exporter this module's manual WS span (app/ws_server.py) also reads from is
configured before either listener starts:

    uv run opentelemetry-instrument python -m app.main

Plain `uv run python -m app.main` also works — the OTel SDK still runs (an
unconfigured/unreachable OTLP exporter just logs failed exports in the
background; see README.md) — but the FastAPI side then has no auto-
instrumentation.
"""
from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

from app.http_app import app as http_app
from app.ws_server import create_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("handling-events-python")

WS_HOST = os.environ.get("WS_HOST", "0.0.0.0")
WS_PORT = int(os.environ.get("WS_PORT", "8081"))
HTTP_HOST = os.environ.get("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8082"))


async def _run_http() -> None:
    config = uvicorn.Config(http_app, host=HTTP_HOST, port=HTTP_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def _run_ws() -> None:
    async with create_server(WS_HOST, WS_PORT):
        logger.info(
            "observability-python: ws://%s:%s/ws/v1/bookings/{bookingId}/handling-events",
            WS_HOST,
            WS_PORT,
        )
        await asyncio.get_running_loop().create_future()  # run forever


async def main() -> None:
    await asyncio.gather(_run_ws(), _run_http())


if __name__ == "__main__":
    asyncio.run(main())
