---
title: "Scale-Out and Fan-Out"
order: 18
part: "Production Concerns"
description: "Fanning one event out to every connected client across several server instances, with a Kafka or a Redis backplane."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why sticky sessions pin a connection to one instance but do nothing about where an event originates.
- Fan events out across instances with a shared backplane behind one `publish`/`subscribe` interface.
- Give each instance its own Kafka consumer group so the topic acts as a broadcast channel, not a work queue.
- Choose between Kafka's durability and replay and Redis's lower latency and cost.
- Estimate fan-out amplification: one deserialize-and-filter per instance per event, not per client.

## Why this matters

A second instance exists to hold more connections than one process can, or to survive one dying. The moment it exists, a client connected to instance A can wait for an event that originates at instance B. `examples/part4-backplane` runs the `handlingEvents` channel on two instances per stack (`quarkus-a` and `quarkus-b`, `python-a` and `python-b`) and delivers across them over Kafka and over Redis.

## Pattern: Backplane

### The problem

A WebSocket lives on one process for as long as it stays open: the TCP connection and everything the server knows about it. A load balancer handles that with sticky sessions, usually a cookie or a consistent hash, so every frame for a client reaches the same instance. That works, and the setup needs no balancer: each instance is exposed on its own port (`quarkus-a` 8080, `quarkus-b` 8083, `python-a` 8081, `python-b` 8084) and clients connect straight to A.

Sticky sessions say nothing about events. `POST /internal/bookings/{bookingId}/handling-events` can land on any instance, because the service calling it has no reason to know which instance holds the one connection that cares. Inject through B while the client sits on A, and nothing connects B's memory to A's.

The default stateless mode shows it. Each instance fans out through in-process state (an `asyncio.Queue` per subscriber in Python, `LocalDelivery` over `OpenConnections` on Quarkus), scoped to that instance only. An event injected at B never reaches the client on A, no matter how long it waits. Past one instance, stateless delivery gets silently dependent on which instance produced the event: from the client's side, a coin flip.

### The solution

A **backplane** is a channel shared by every instance, keyed by `bookingId`: the instance that receives the inject publishes to it, and the instance holding the connection picks the event up and forwards it to its own sockets.

The forwarding code is the one every mode already uses (`LocalDelivery.deliver` on Quarkus, `_send_event` on Python), so the WebSocket-facing code doesn't know which mode is running. The inject endpoint calls `publish` on the shared `Backplane` interface and returns `202 Accepted` without waiting for any instance to deliver.

{% include excalidraw.html file="18-sticky-vs-backplane" alt="A client connects to instance A through a sticky session while an inject request arrives at instance B. Without a backplane, a dashed arrow from B shows the publish has nowhere local to go and a dashed arrow from A shows the event dropped. With a backplane, instance B publishes to a Kafka topic or a Redis channel and instance A subscribes or consumes from it." caption="Figure 18.1: A sticky load balancer pins the client to instance A while the event enters at instance B. Without a shared backplane the event never crosses between them." %}

### How Quarkus and Python model it

On Kafka, each Quarkus instance derives its consumer group from its own `INSTANCE_ID` (`${INSTANCE_ID:quarkus}-handling-events`). That inverts the usual idiom, where members of one group split a topic's partitions so each record is processed once. A fan-out needs A to consume the record B published, so every instance gets its own group, and one group per instance turns the topic into a broadcast channel. Python gets there by never joining a group: a fresh `AIOKafkaConsumer` per subscription, partitions assigned with `consumer.assign(...)`.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    public void consume(HandlingEvent event) {
        String bookingId = event.bookingId();
        Set<String> seen = seenEventIds.computeIfAbsent(bookingId, ignored -> ConcurrentHashMap.newKeySet());
        if (seen.add(event.eventId())) {
            injected.computeIfAbsent(bookingId, ignored -> new CopyOnWriteArrayList<>()).add(event);
        }
        localDelivery.deliver(bookingId, event);
    }
```
```python
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
```

Redis has no consumer groups to invert. Pub/Sub delivers every message to every current subscriber, and broadcast is its only mode. Quarkus subscribes to the booking's channel the first time a local client connects for it. Python iterates `pubsub.listen()` and skips the control frame that confirms the subscription.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    private void ensureSubscribed(String bookingId) {
        if (!subscribedBookings.add(bookingId)) {
            return;
        }
        redis.pubsub(String.class).subscribe(channel(bookingId))
                .subscribe().with(
                        message -> onMessage(bookingId, message),
                        failure -> Log.errorf(failure, "redis subscription failed bookingId=%s", bookingId));
    }
```
```python
    async def subscribe(self, booking_id: str, after_event_id: str | None) -> AsyncIterator[HandlingEvent]:
        del after_event_id  # unused; see module docstring: no history in Pub/Sub
        if self._client is None:
            raise RuntimeError("RedisBackplane.start() was not called")
        pubsub = self._client.pubsub()
        channel = _channel(booking_id)
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    # The first message on a fresh subscribe() is always a
                    # "subscribe" confirmation, not an app payload; skip it
                    # (and any other non-"message" control event).
                    continue
                yield HandlingEvent.model_validate_json(message["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
```

## Kafka or Redis

Both close the gap, and the choice follows from what each broker is.

| | Kafka | Redis Pub/Sub |
|---|---|---|
| Durability | Retained on disk per the topic's retention policy | None: a message exists only while a subscriber is listening |
| Replay | Yes: `auto.offset.reset=earliest` lets a new instance, or an `afterEventId` resume, read history back | No: nothing to replay from |
| Ordering | Per partition; this topic runs one partition, so ordering is total per `bookingId` | Best effort, none across a disconnect |
| Latency | Higher: produce, then fetch through a log, plus offset bookkeeping | Lower: `PUBLISH` reaches subscribers directly |
| Operating cost | Topics, partitions, offsets, broker storage to size and retain | A channel is a string: no partitions, offsets or retention |

Reach for Kafka when you need replay, resume or at-least-once delivery. Reach for Redis when you need low-latency fan-out and can lose in-flight messages on a disconnect.

Kafka's durability also serves reconnect. The topic that fans events out is the history a reconnecting client replays, and a different instance with no history of its own can pick up what a sibling just published. Redis mode ignores `afterEventId` on both stacks, because there is nothing to resume from. The backplane composes with the rest of the connection's hardening: the upgrade-time auth check still runs once, on whichever instance the client lands on, and only the route an event takes to that instance changes.

{% include excalidraw.html file="18-kafka-vs-redis" alt="Two columns contrasting the same cross-instance delivery. The Kafka column shows a topic keyed by bookingId with a per-instance consumer group, durable and replayable, at the cost of topic, partition and offset bookkeeping. The Redis column shows a pub/sub channel per booking where every subscriber gets every publish, live only with no replay, at the cost that a dropped subscriber loses in-flight messages." caption="Figure 18.2: Kafka and Redis both close the fan-out gap. Kafka gives up operational simplicity for durability and replay, and Redis gives up both for low cost and latency." %}

## Fan-out amplification

Stateless, an instance works only for connections it holds. With a backplane, one event can touch every instance. In Kafka mode every instance's own group receives every record. In Redis mode every instance that has subscribed to a booking's channel receives every publish. An instance with no local connection for that `bookingId` still wakes, deserializes the event, finds nothing in `LocalDelivery.deliver`'s lookup, and discards it.

That cost is small per instance and nonzero, and it grows with the number of instances, not the number of clients watching. N instances do roughly N times the deserialize-and-filter work per event, whoever is waiting. A handful of instances will never show it. Dozens of instances and thousands of bookings with one client each will, which is why the channel is keyed by `bookingId` and why a large deployment partitions or shards it rather than running one broadcast domain. Redis's cheaper per-message path matters more as instance count grows.

> **Decision**
>
> A sticky load balancer keeps a client on one instance. It does nothing to get an event from where it originates to the instance holding the connection. Close that gap with a backplane every instance subscribes to and any instance can publish to: a Kafka topic with a per-instance consumer group, or a Redis Pub/Sub channel. Pick Kafka for replay and resume, Redis for latency and the smallest operating surface. Size instance count and keying for N times the discard work per event.

> **🤖 Explore with your agent**
>
> "In examples/part4-backplane, a client on instance A must receive an event injected through instance B on both brokers. Review the Kafka backplane on Quarkus and Python and tell me whether any instance shares a consumer group with another, and what would break in the fan-out if two did. Then change one thing so the stateless mode fails the same cross-instance check, using POST /internal/bookings/{bookingId}/handling-events on port 8083 and a WebSocket client on port 8080."
>
> Check: `docker logs part4-backplane-quarkus-a` shows `delivered eventId=<id> bookingId=<id> instance=quarkus-a`, and `./verify.sh` still prints `PASS: `.

## Build, run, observe

```bash
cd examples/part4-backplane && ./verify.sh
```

`verify.sh` runs three Docker Compose cycles on four app instances (two Quarkus, two Python): stateless, Kafka and Redis. In the Kafka and Redis stages it connects a client to instance A, injects an event through instance B's HTTP port, and checks two things: the client receives the event, and instance A's own server log shows it delivering. The log line (`delivered eventId=<id> bookingId=<id> instance=quarkus-a`) is written only by `LocalDelivery.deliver` or `_send_event` running inside A, so it separates delivery by A from a frame that arrived some other way. Each check prints `ok, `, and the script ends with `PASS: ` when every stage holds on both stacks.

- Run in stateless mode: an event injected at B never reaches the client on A.
- Switch to `--profile kafka` or `--profile redis`: the same injection arrives on both stacks.
- In Redis mode, reconnect with an `afterEventId`: nothing replays. In Kafka mode, the missed event does.

## For deeper coverage

- Adam Bellemare, *Building Event-Driven Microservices, Second Edition* (O'Reilly, 2025): the broker-as-broadcast-channel reasoning behind giving each instance its own consumer group.
- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026): the durability versus latency trade-off behind Kafka versus Redis.
- Sam Newman, *Building Microservices, 2nd Edition* (O'Reilly, 2021): scaling a service past one instance and the shared-state problems that follow.
- *Cloud Native Design Patterns*, "WebSockets at Scale" chapter: the pub/sub backplane plus resume-don't-restart posture.
- [Apache Kafka documentation](https://kafka.apache.org/documentation/) and [Redis Pub/Sub documentation](https://redis.io/docs/latest/develop/interact/pubsub/): the two broker mechanisms.
