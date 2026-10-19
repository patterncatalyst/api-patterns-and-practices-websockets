"""Part 4 example — the `stateless` backplane mode (PROTOCOL.md "Backplane
modes"): the DEFAULT profile and the Ch18 motivating contrast case.

No broker, no shared state: an injected event is fanned out via an
in-process `asyncio.Queue` per subscriber, scoped to THIS instance only.
Two instances behind a load balancer therefore do NOT see each other's
injected events — that gap is exactly what Ch18 motivates the backplane
with (see kafka_backplane.py / redis_backplane.py for the modes that close
it). `after_event_id` is accepted (for interface symmetry with the other two
modes) but always ignored: this mode keeps no history at all, so a
gap-era injected event — one published while a given client was
disconnected — is lost for that client, by design (PROTOCOL.md's "visible-
gap proof").
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

from app.backplane.base import Backplane
from app.models_generated import HandlingEvent

logger = logging.getLogger("handling-events-python")


class StatelessBackplane(Backplane):
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[HandlingEvent]]] = defaultdict(set)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish(self, booking_id: str, event: HandlingEvent) -> None:
        queues = self._subscribers.get(booking_id)
        if not queues:
            logger.info(
                "stateless backplane: no local subscribers for bookingId=%s eventId=%s — dropped",
                booking_id,
                event.eventId,
            )
            return
        for queue in list(queues):
            queue.put_nowait(event)

    async def subscribe(self, booking_id: str, after_event_id: str | None) -> AsyncIterator[HandlingEvent]:
        del after_event_id  # unused — see class docstring: no history to replay
        queue: asyncio.Queue[HandlingEvent] = asyncio.Queue()
        self._subscribers[booking_id].add(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self._subscribers[booking_id].discard(queue)
            if not self._subscribers[booking_id]:
                del self._subscribers[booking_id]
