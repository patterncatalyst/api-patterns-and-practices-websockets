"""Part 3 "Handling It" / Ch10 example — consuming client for the
`handlingEvents` channel (contracts/asyncapi.yaml
`operations.receiveHandlingEvent`), built on the native `websockets` library
(`websockets.asyncio.client.connect` — NOT a framework's bundled WebSocket
client), symmetric with the Quarkus WebSockets Next `@WebSocketClient`
sibling in ../../quarkus/.

Connects to either server this example implements (same contract, either
stack):

    ws://localhost:8080/ws/v1/bookings/{bookingId}/handling-events  (../../quarkus)
    ws://localhost:8081/ws/v1/bookings/{bookingId}/handling-events  (../../python)

This module is schema-agnostic on purpose: received frames are only decoded
far enough to log a one-line summary; nothing here depends on either
server's wire implementation.

Two teaching points for Ch10:

  1. STATELESS reconnect with exponential backoff + jitter on connection
     drop (`_reconnect_loop`). This does NOT replay events recorded while
     disconnected — that requires a durable, replayable event log on the
     server side (Kafka-backed replay is Part 4 Ch16's job, not this
     chapter's). This fixture-replay example always restarts the same
     3-event sequence from the top on a fresh connection, which stands in
     for that gap rather than fixing it.
  2. Backpressure on the incoming-frame buffer (`asyncio.Queue`) with an
     EXPLICIT, configurable policy for what happens when the consumer is
     slower than the server: BLOCK (default — `_producer` awaits room in
     the queue; no frame is lost, but a slow consumer throttles how fast
     this client pulls new frames off the socket) or DROP_OLDEST (never
     blocks the producer; evicts the oldest buffered frame to make room).

Run it directly:

    uv run python -m app.client

Configuration is via environment variables (see the `_Config` fields below
for names/defaults) so the same image/checkout can point at either server
without code changes.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import random
import signal

from websockets.asyncio.client import connect

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("handling-events-client")


@dataclasses.dataclass(frozen=True)
class Config:
    ws_url: str
    reconnect_base_delay_s: float
    reconnect_max_delay_s: float
    reconnect_jitter_ratio: float
    buffer_capacity: int
    buffer_policy: str  # "block" or "drop_oldest"
    consumer_delay_s: float

    @classmethod
    def from_env(cls) -> "Config":
        base_url = os.environ.get("CLIENT_WS_URL")
        if base_url is None:
            host = os.environ.get("CLIENT_WS_HOST", "localhost")
            port = os.environ.get("CLIENT_WS_PORT", "8081")
            booking_id = os.environ.get("CLIENT_BOOKING_ID", "bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A")
            base_url = f"ws://{host}:{port}/ws/v1/bookings/{booking_id}/handling-events"
        return cls(
            ws_url=base_url,
            reconnect_base_delay_s=float(os.environ.get("CLIENT_RECONNECT_BASE_DELAY_S", "0.5")),
            reconnect_max_delay_s=float(os.environ.get("CLIENT_RECONNECT_MAX_DELAY_S", "30")),
            reconnect_jitter_ratio=float(os.environ.get("CLIENT_RECONNECT_JITTER_RATIO", "0.2")),
            buffer_capacity=int(os.environ.get("CLIENT_BUFFER_CAPACITY", "16")),
            buffer_policy=os.environ.get("CLIENT_BUFFER_POLICY", "block").lower(),
            consumer_delay_s=float(os.environ.get("CLIENT_CONSUMER_DELAY_S", "0")),
        )


def _backoff_delay(config: Config, attempt: int) -> float:
    """delay = min(max_delay, base_delay * 2**attempt), then +/- jitter_ratio
    applied as a uniform random multiplier — same formula as the Quarkus
    sibling's ReconnectingClient, so both clients exhibit the same reconnect
    shape against either server."""
    exponential = config.reconnect_base_delay_s * (2 ** min(attempt, 20))
    capped = min(config.reconnect_max_delay_s, exponential)
    jitter_multiplier = 1.0 + random.uniform(-config.reconnect_jitter_ratio, config.reconnect_jitter_ratio)
    return max(0.0, capped * jitter_multiplier)


async def _enqueue(queue: "asyncio.Queue[str]", message: str, policy: str) -> None:
    if policy == "drop_oldest":
        if queue.full():
            dropped = queue.get_nowait()
            logger.warning("buffer full (capacity=%d) — dropped oldest frame: %s", queue.maxsize, dropped)
        queue.put_nowait(message)
    else:
        # BLOCK (default): await room in the queue. This is the safe
        # default — no frame is ever lost — at the cost of throttling how
        # fast we pull new frames off the socket when the consumer is slow.
        await queue.put(message)


async def _consume(queue: "asyncio.Queue[str]", consumer_delay_s: float) -> None:
    """Separate task from the socket reader, so the reader/producer and
    consumer rates are decoupled by the queue — exactly the arrangement the
    backpressure policy above is mediating."""
    while True:
        raw = await queue.get()
        try:
            event = json.loads(raw)
            logger.info(
                "received %s eventId=%s bookingId=%s",
                event.get("eventType"),
                event.get("eventId"),
                event.get("bookingId"),
            )
        except json.JSONDecodeError:
            logger.info("received non-JSON frame: %s", raw)
        if consumer_delay_s > 0:
            await asyncio.sleep(consumer_delay_s)


async def _producer(ws, queue: "asyncio.Queue[str]", policy: str) -> None:
    async for message in ws:
        await _enqueue(queue, message, policy)


async def _reconnect_loop(config: Config, queue: "asyncio.Queue[str]") -> None:
    attempt = 0
    while True:
        try:
            logger.info("connecting to %s", config.ws_url)
            async with connect(config.ws_url) as ws:
                logger.info("connected")
                attempt = 0  # reset backoff on a successful upgrade
                await _producer(ws, queue, config.buffer_policy)
                # The server side of this example never closes the
                # connection on its own once the fixture is replayed — a
                # clean exit from the `async for` above means the server
                # closed normally, which still counts as "disconnected"
                # for reconnect purposes.
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Deliberately broad: a connection can fail in ways that are
            # NOT websockets.exceptions.ConnectionClosed or OSError — e.g. a
            # server mid-restart can accept the TCP connection, then drop it
            # before finishing the HTTP upgrade response, which the
            # `websockets` library surfaces as InvalidMessage/InvalidHandshake
            # (neither a ConnectionClosed nor an OSError subclass). Any
            # failure here — handshake, transport, timeout — should trigger
            # the same backoff-and-retry, so we catch Exception broadly and
            # only exempt CancelledError (caught above) so a real shutdown
            # still propagates.
            logger.info("disconnected: %s", e)
        delay = _backoff_delay(config, attempt)
        logger.info("reconnecting in %.2fs (attempt %d)", delay, attempt + 1)
        attempt += 1
        await asyncio.sleep(delay)


async def main() -> None:
    config = Config.from_env()
    logger.info(
        "starting — target=%s buffer_capacity=%d buffer_policy=%s consumer_delay_s=%.2f",
        config.ws_url,
        config.buffer_capacity,
        config.buffer_policy,
        config.consumer_delay_s,
    )
    queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=config.buffer_capacity)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: stop.done() or stop.set_result(None))

    consumer_task = asyncio.create_task(_consume(queue, config.consumer_delay_s))
    reconnect_task = asyncio.create_task(_reconnect_loop(config, queue))

    await stop
    logger.info("shutting down")
    consumer_task.cancel()
    reconnect_task.cancel()
    await asyncio.gather(consumer_task, reconnect_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
