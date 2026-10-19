"""Part 4 example — entrypoint. Runs two listeners in one process, on the
same asyncio event loop:

  - the native `websockets` server (app/ws_server.py) on WS_HOST:WS_PORT
    (default 0.0.0.0:8081 — matches the Part 3 Python example's port; 8080
    is reserved for the Quarkus sibling), serving
    `/ws/v1/bookings/{bookingId}/handling-events` with backpressure, error
    handling, heartbeats, and JWT auth layered on top of Part 3's plain
    fixture replay.
  - a FastAPI app (app/http_app.py) on HTTP_HOST:HTTP_PORT (default
    0.0.0.0:8082) via uvicorn, for HTTP/app lifecycle (`/healthz`, `/`).

Run it directly:

    uv run python -m app.main

or via `uv run uvicorn app.main:http_app --host 0.0.0.0 --port 8082` if you
only want the HTTP side up (e.g. for a readiness probe) — but the WS feed
requires running this module so the `websockets` listener starts too.
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
            "connection-concerns-python: ws://%s:%s/ws/v1/bookings/{bookingId}/handling-events",
            WS_HOST,
            WS_PORT,
        )
        await asyncio.get_running_loop().create_future()  # run forever


async def main() -> None:
    await asyncio.gather(_run_ws(), _run_http())


if __name__ == "__main__":
    asyncio.run(main())
