"""Part 4 example — the `redis` backplane mode (PROTOCOL.md "Backplane
modes"): instances share a Redis Pub/Sub channel per booking
(`handling-events:{bookingId}`), using `redis.asyncio` (redis-py's asyncio
client).

Pub/Sub is live-fan-out ONLY — Redis keeps no history of past publishes, so
a subscriber only ever sees messages published AFTER it subscribes. That
makes this mode's `after_event_id` handling identical to `stateless`'s: it is
accepted (for interface symmetry) and ignored. PROTOCOL.md calls this out
explicitly: "In redis mode, `afterEventId` resume behaves as stateless (no
history)." The contrast this mode demonstrates against `kafka` is
simplicity/latency (no topic/partition/offset bookkeeping) vs Kafka's
durability/replay.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import redis.asyncio as redis

from app.backplane.base import Backplane
from app.models_generated import HandlingEvent

logger = logging.getLogger("handling-events-python")


def _channel(booking_id: str) -> str:
    return f"handling-events:{booking_id}"


class RedisBackplane(Backplane):
    def __init__(self, url: str) -> None:
        self._url = url
        self._client: redis.Redis | None = None

    async def start(self) -> None:
        self._client = redis.from_url(self._url)
        await self._client.ping()
        logger.info("redis backplane: connected to %s", self._url)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def publish(self, booking_id: str, event: HandlingEvent) -> None:
        if self._client is None:
            raise RuntimeError("RedisBackplane.start() was not called")
        await self._client.publish(_channel(booking_id), event.model_dump_json(exclude_none=True))

    async def subscribe(self, booking_id: str, after_event_id: str | None) -> AsyncIterator[HandlingEvent]:
        del after_event_id  # unused — see module docstring: no history in Pub/Sub
        if self._client is None:
            raise RuntimeError("RedisBackplane.start() was not called")
        pubsub = self._client.pubsub()
        channel = _channel(booking_id)
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    # The first message on a fresh subscribe() is always a
                    # "subscribe" confirmation, not an app payload — skip it
                    # (and any other non-"message" control event).
                    continue
                yield HandlingEvent.model_validate_json(message["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
