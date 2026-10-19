"""Part 4 example — the `kafka` backplane mode (PROTOCOL.md "Backplane
modes"): instances share a Kafka topic (`handling-events`, keyed by
bookingId), using `aiokafka` (an asyncio-native Kafka client). Durable +
replayable — this is also what powers Ch16's `afterEventId` resume
(PROTOCOL.md "Resume parameter").

Design note — this topic carries ONLY INJECTED events, never the 3 fixture
seed events: every connection, in every backplane mode, gets the seed
sequence delivered directly from `app/feed.py` (see `app/ws_server.py`'s
`_deliver_loop`) — Part 4 is about connection/backplane concerns, not new
message content, so the deterministic baseline stays identical across all
three modes rather than depending on broker state. That keeps
`afterEventId=<the last seed event's id>` meaningful even though that id was
never produced to this topic: `subscribe` below falls back to "treat
everything currently in the topic as after `after_event_id`" when the given
id is never found before the point that was the live tail at subscribe time
(see the `end_offsets` bookkeeping) — which is exactly the PROTOCOL.md
Ch15-gap-then-Ch16-replay scenario: the only thing ever in the topic at that
point IS the gap-era injected event.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from app.backplane.base import Backplane
from app.models_generated import HandlingEvent

logger = logging.getLogger("handling-events-python")


class KafkaBackplane(Backplane):
    def __init__(self, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        admin = AIOKafkaAdminClient(bootstrap_servers=self._bootstrap_servers)
        await admin.start()
        try:
            await admin.create_topics([NewTopic(name=self._topic, num_partitions=1, replication_factor=1)])
            logger.info("kafka backplane: created topic %s", self._topic)
        except TopicAlreadyExistsError:
            logger.info("kafka backplane: topic %s already exists", self._topic)
        finally:
            await admin.close()

        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers)
        await self._producer.start()
        logger.info("kafka backplane: producer connected to %s", self._bootstrap_servers)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def publish(self, booking_id: str, event: HandlingEvent) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaBackplane.start() was not called")
        await self._producer.send_and_wait(
            self._topic,
            key=booking_id.encode("utf-8"),
            value=event.model_dump_json(exclude_none=True).encode("utf-8"),
        )

    async def subscribe(self, booking_id: str, after_event_id: str | None) -> AsyncIterator[HandlingEvent]:
        consumer = AIOKafkaConsumer(
            bootstrap_servers=self._bootstrap_servers,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            partitions = consumer.partitions_for_topic(self._topic) or {0}
            topic_partitions = [TopicPartition(self._topic, p) for p in sorted(partitions)]
            consumer.assign(topic_partitions)

            if after_event_id is not None:
                # Replay-after (Ch16): seek to the beginning and snapshot the
                # CURRENT end offsets, then BUFFER every record that existed
                # at subscribe time (across all partitions, regardless of
                # bookingId — a shared topic can hold other bookings' events
                # too) up to that snapshot. Buffering first — rather than
                # deciding skip-vs-yield while streaming — is what makes the
                # "after_event_id not found" fallback (see module docstring)
                # correct: streaming can't know in advance whether an id
                # will ever show up, so it can't decide in time whether the
                # record it's looking at right now should ultimately be
                # kept. With the whole history buffered, finding
                # after_event_id's index (or not) is a simple list search.
                await consumer.seek_to_beginning(*topic_partitions)
                end_offsets = await consumer.end_offsets(topic_partitions)
                remaining = {tp: end for tp, end in end_offsets.items() if end > 0}
                history: list[HandlingEvent] = []
                while remaining:
                    record = await consumer.getone()
                    tp = TopicPartition(record.topic, record.partition)
                    if record.key is not None and record.key.decode("utf-8") == booking_id:
                        history.append(HandlingEvent.model_validate_json(record.value))
                    if tp in remaining and (record.offset + 1) >= remaining[tp]:
                        del remaining[tp]

                index = next((i for i, e in enumerate(history) if e.eventId == after_event_id), None)
                to_replay = history[index + 1 :] if index is not None else history
                for event in to_replay:
                    yield event
                # Consumer position is now at (or past) the snapshotted end
                # offsets for every partition — equivalent to seek_to_end —
                # so the live loop below picks up exactly where replay left
                # off, with no gap and no re-delivery.
            else:
                # Live-only (no after_event_id): nothing to replay.
                await consumer.seek_to_end(*topic_partitions)

            async for record in consumer:
                if record.key is None or record.key.decode("utf-8") != booking_id:
                    continue
                yield HandlingEvent.model_validate_json(record.value)
        finally:
            await consumer.stop()
