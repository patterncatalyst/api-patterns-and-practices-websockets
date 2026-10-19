"""Part 4 example — entrypoint. Runs two listeners in one process, on the
same asyncio event loop, sharing one `Backplane` instance:

  - the native `websockets` server (app/ws_server.py) on WS_HOST:WS_PORT
    (default 0.0.0.0:8081 — matches the Part 3/Part 4-connection Python
    examples; 8080 is reserved for the Quarkus sibling), serving
    `/ws/v1/bookings/{bookingId}/handling-events` with `?afterEventId=`
    resume and backplane-fanned-out delivery.
  - a FastAPI app (app/http_app.py) on HTTP_HOST:HTTP_PORT (default
    0.0.0.0:8082) via uvicorn, for HTTP/app lifecycle (`/healthz`, `/`) and
    the `/internal/.../handling-events` inject endpoint.

Run it directly:

    uv run python -m app.main
"""
from __future__ import annotations

import asyncio
import contextlib
import logging

import uvicorn

from app import config
from app.backplane import create_backplane
from app.http_app import app as http_app
from app.ws_server import create_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("handling-events-python")


async def _run_http() -> None:
    uv_config = uvicorn.Config(http_app, host=config.HTTP_HOST, port=config.HTTP_PORT, log_level="info")
    server = uvicorn.Server(uv_config)
    await server.serve()


async def _run_ws(backplane) -> None:
    async with create_server(config.WS_HOST, config.WS_PORT, backplane):
        logger.info(
            "backplane-python: mode=%s instance=%s ws://%s:%s/ws/v1/bookings/{bookingId}/handling-events",
            config.BACKPLANE_MODE,
            config.INSTANCE_ID,
            config.WS_HOST,
            config.WS_PORT,
        )
        await asyncio.get_running_loop().create_future()  # run forever


async def main() -> None:
    backplane = create_backplane()
    await backplane.start()
    http_app.state.backplane = backplane
    http_app.state.instance_id = config.INSTANCE_ID
    try:
        await asyncio.gather(_run_ws(backplane), _run_http())
    finally:
        with contextlib.suppress(Exception):
            await backplane.stop()


if __name__ == "__main__":
    asyncio.run(main())
