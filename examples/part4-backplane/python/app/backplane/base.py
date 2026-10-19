"""Part 4 example — the `Backplane` interface every mode implements.

`subscribe` is an async-generator-returning method: it yields `HandlingEvent`
instances to forward to one WebSocket connection, for as long as the caller
keeps iterating (typically until the connection closes and the consuming
task is cancelled — see `app/ws_server.py`'s `_deliver_loop`, which wraps the
iteration in `contextlib.aclosing` so cancellation always runs the
implementation's cleanup, e.g. stopping a Kafka consumer or unsubscribing a
Redis channel).
"""
from __future__ import annotations

import abc
from collections.abc import AsyncIterator

from app.models_generated import HandlingEvent


class Backplane(abc.ABC):
    @abc.abstractmethod
    async def start(self) -> None:
        """Acquire any connections/resources (producer, admin client, Redis
        client, ...). Called once at process startup, before either listener
        (WS or HTTP) starts accepting traffic — see app/main.py.
        """

    @abc.abstractmethod
    async def stop(self) -> None:
        """Release resources acquired in `start()`. Called once at process
        shutdown.
        """

    @abc.abstractmethod
    async def publish(self, booking_id: str, event: HandlingEvent) -> None:
        """Publish `event` for `booking_id` to every subscriber across every
        instance sharing this backplane (kafka/redis), or to this process's
        local subscribers only (stateless). Called by the
        `/internal/bookings/{bookingId}/handling-events` inject endpoint —
        see app/http_app.py.
        """

    @abc.abstractmethod
    def subscribe(self, booking_id: str, after_event_id: str | None) -> AsyncIterator[HandlingEvent]:
        """Return an async generator yielding `HandlingEvent`s for
        `booking_id` as they're published, per PROTOCOL.md's "Resume
        parameter" section:

          - `after_event_id` given: replay-after semantics IF this mode
            supports history (kafka only — see kafka_backplane.py);
            redis/stateless ignore it (no history to replay).
          - `after_event_id` absent: live-only, from the point of
            subscription forward.

        Runs until the caller stops iterating (and, for implementations with
        real resources, until `aclose()` is called on the generator or it is
        garbage-collected after a `GeneratorExit`/cancellation).
        """
