---
title: "Scale-Out and Fan-Out"
order: 18
part: "Production Concerns"
description: "Fanning one event out to many connected clients across multiple server instances, contrasted on Kafka and on Redis."
duration: "20 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why sticky sessions pin a client's connection to one instance but do nothing for where an injected event originates, and why closing that gap needs a shared backplane.
- Compare `KafkaBackplane`'s per-instance, non-shared consumer group against `RedisBackplane`'s pure pub/sub, and explain why each turns its broker into a broadcast channel rather than a work queue.
- Trace the shared `publish`/`subscribe` interface (`Backplane.java` / `backplane/base.py`) that lets the inject endpoint and the WebSocket handler stay ignorant of which backplane mode is running.
- Weigh Kafka's durability-and-replay trade-off against Redis's lower-latency, lower-operational-cost trade-off (DRQ-005), and state which deployment requirement should drive the choice.
- Estimate fan-out amplification — roughly N times the deserialize-and-filter cost per injected event across N instances — and explain why it scales with instance count, not connected-client count.

## Why this matters

Every example through Chapter 17 ran one server instance. A load balancer never entered the picture because there was nothing to balance across. That assumption breaks the moment a second instance exists for the same reason any stateless-looking service gets a second instance: to handle more connections than one process can hold open, or to survive one instance dying without taking every client with it. `examples/part4-backplane` forks `part4-connection`'s `handlingEvents` channel (same `contracts/asyncapi.yaml` operation, same wire shape) and runs **two instances per stack** — `quarkus-a`/`quarkus-b` on WebSockets Next, `python-a`/`python-b` on native `websockets` — specifically to expose the problem a single-instance example can never show: a client connected to instance A, and an event that originates at instance B. `examples/part4-backplane/PROTOCOL.md`'s "Backplane modes" section names three interchangeable delivery strategies behind that one channel, and `verify.sh`'s Stage B/Stage C prove the cross-instance case live, on both brokers, on both stacks. This chapter teaches fan-out on Kafka and on Redis side by side: the trade-off between them, not a single recommended answer, is the point (DRQ-005).

## Why sticky sessions alone don't solve this

A WebSocket connection is stateful in a way an HTTP request isn't: once the upgrade completes, the TCP connection — and everything a server has in memory about it (which booking it's watching, what it's already been sent) — lives on one specific process for as long as the socket stays open. A load balancer in front of multiple instances handles this the obvious way: sticky sessions, usually a cookie or a consistent hash on some connection-identifying value, routes every frame for a given client to the same backend instance for the life of that connection. That part works fine and this example doesn't even model it explicitly — `compose.yaml` just exposes each instance on its own port (`quarkus-a` 8080, `quarkus-b` 8083, `python-a` 8081, `python-b` 8084) and `verify.sh` connects directly to instance A's port, which is what a sticky-session load balancer would have routed it to anyway.

The part sticky sessions say nothing about is where an event comes from. `examples/part4-backplane/PROTOCOL.md`'s "Inject endpoint" section describes `POST /internal/bookings/{bookingId}/handling-events` — the test harness's (and, in a real system, some other service's) way of pushing a new `HandlingEvent` into the system. That POST can land on any instance: a REST call from an upstream service has no sticky session to honor, and even if it did, the thing producing the event has no reason to know which WebSocket instance happens to be holding the one open connection that cares about it. `verify.sh`'s Ch18 scenario makes this concrete by injecting through instance B's HTTP port while the client sits on instance A's WebSocket port — the same split a production deployment would see any time an event source (an order-processing worker, a customs-clearance webhook, a batch job) isn't the same process, let alone the same instance, as whichever WebSocket server happens to be holding a given client's socket. Sticky sessions solve "keep a client's requests on one instance." They do nothing for "get an event from wherever it originates to whichever instance is holding the connection that wants it." That second problem needs something all the instances share — a backplane — and nothing about load-balancer configuration provides one.

## The baseline: stateless mode, and why it drops the event

`examples/part4-backplane/python/app/backplane/stateless_backplane.py` is the default mode (`BACKPLANE_MODE=stateless`, no broker) and it doubles as this chapter's motivating failure case. Its `publish` method fans an event out via an in-process `asyncio.Queue` per subscriber — scoped, as its own module docstring says, "to THIS instance only." Two instances behind a load balancer therefore do not see each other's injected events: an event published on instance B's `StatelessBackplane` only ever reaches queues that instance B itself created, because there is no mechanism connecting B's in-memory queues to A's. The Quarkus sibling, `StatelessBackplane.java`, expresses the identical boundary through `LocalDelivery`, which iterates `OpenConnections` — WebSockets Next's registry of connections *on this JVM* — and nothing else.

This mode exists in the example for exactly one reason: so Ch18 has a visible "before" to contrast its "after" against. An event injected through instance B's inject endpoint while a client sits on instance A's socket simply never arrives, in stateless mode, no matter how long the test waits — there is no live producer left that will ever deliver it, which is why `verify.sh`'s Ch15 stateless-gap proof can assert "not delivered" with a short grace window rather than guessing at a timeout. That's a single-instance scenario (Ch15 exercises reconnect, not cross-instance delivery), but the underlying mechanism is the same one Ch18 needs closed: stateless mode's fan-out stops at the process boundary. Scale a stateless design past one instance and you don't get slower delivery — you get silent, instance-dependent delivery, where whether a client sees an event depends on which instance produced it versus which instance is holding that client's socket, a coin flip from the client's point of view.

{% include excalidraw.html file="18-sticky-vs-backplane" alt="A client box connects to Instance A with a sticky session label; a test harness box sends an inject request to Instance B. Below, a dashed ghost box labeled NO BACKPLANE stateless Ch15 shows a dashed arrow from Instance A reading dropped -- same instance only, and a dashed arrow from Instance B reading publish has nowhere local to go. Below that, an ink emphasis box labeled BACKPLANE Ch18 DRQ-005 lists a Kafka topic handling-events with a per-instance consumer group for fan-out not load-balanced, and a Redis channel handling-events colon bookingId for pub/sub, with an amber arrow from Instance A labeled subscribe/consume and a plain arrow from Instance B labeled publish. A caption states that sticky sessions keep a client on one instance and say nothing about where an event is produced, and only a shared backplane crosses that gap." caption="Figure 18.1 -- a sticky load balancer pins the client to instance A, but the event enters at instance B; without a shared backplane the event never crosses the gap between them." %}

## The backplane pattern: a shared channel every instance subscribes to

The fix is the same shape on both brokers even though the mechanics differ: every instance subscribes to one shared channel keyed by `bookingId`, and the instance that receives the `POST /internal/.../handling-events` call publishes to that channel instead of (or in addition to) delivering locally. Whichever instance is actually holding the connection for that booking picks the event up off the shared channel and forwards it to its own local WebSocket connections — the same `LocalDelivery.deliver` / `_send_event` call path every mode already uses for same-instance delivery, so the WebSocket-facing code never has to know or care which backplane mode produced the event it's about to push.

On the Kafka side, `KafkaBackplane.java`'s class Javadoc calls out a detail easy to get backwards: each instance's `mp.messaging.incoming.handling-events-in.group.id` is derived from its own `INSTANCE_ID` (`application.properties`: `${INSTANCE_ID:quarkus}-handling-events`), giving every instance its **own** consumer group rather than sharing one. That inverts the usual Kafka consumer-group idiom, where members of one group split a topic's partitions between them so each record is processed exactly once across the group. Ch18's proof needs the opposite: instance A's client has to see an event injected through instance B, which requires A to consume that record too, not have Kafka load-balance it away to some other member of a shared group. One consumer group per instance is what turns a Kafka topic into a broadcast channel instead of a work queue. The Python sibling's `KafkaBackplane.subscribe` in `kafka_backplane.py` reaches the same outcome a different way — a fresh, unshared `AIOKafkaConsumer` per subscription, manually assigned to the topic's partitions with `consumer.assign(...)` rather than joining any named group at all, which sidesteps the group-sharing question entirely by never forming a group in the first place.

On the Redis side there's no consumer-group concept to invert: `RedisBackplane.java`'s `ensureSubscribed` calls `redis.pubsub(String.class).subscribe(channel(bookingId))` the first time a local client connects for a given booking, and Redis Pub/Sub delivers every message on a channel to every current subscriber — broadcast is the only mode it has. The Python sibling's `redis_backplane.py` does the equivalent with `redis.asyncio`'s `pubsub()` object, iterating `pubsub.listen()` and skipping the non-`"message"` control frames (the subscribe confirmation that always arrives first). Both backplanes end up solving the same fan-out requirement — every instance holding a relevant connection gets the event — through mechanisms native to their respective brokers rather than through anything this example built by hand.

{% include codetabs.html langs="Quarkus|Python" %}

```java
@Incoming("handling-events-in")
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
        # ... replay-after bookkeeping for after_event_id omitted; see
        # kafka_backplane.py in full ...
        async for record in consumer:
            if record.key is None or record.key.decode("utf-8") != booking_id:
                continue
            yield HandlingEvent.model_validate_json(record.value)
    finally:
        await consumer.stop()
```

And the Redis side of the same subscribe/forward boundary — no consumer group, no offsets, just a channel name and a listen loop:

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
    del after_event_id  # unused — see module docstring: no history in Pub/Sub
    pubsub = self._client.pubsub()
    channel = _channel(booking_id)
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue  # the first message on a fresh subscribe() is a control frame
            yield HandlingEvent.model_validate_json(message["data"])
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
```

Both backplanes route through the same `publish` call at the inject endpoint, too — `HandlingEventInjectResource.inject` on the Quarkus side and `inject_handling_event` in `python/app/http_app.py` both just call `router.publish(bookingId, event)` / `await backplane.publish(bookingId, event)` and return `202 Accepted` without waiting for any instance to actually deliver anything. The inject call doesn't know, and doesn't need to know, how many instances are subscribed or which one is about to forward the event to a live client — that's the whole point of routing through a shared interface (`Backplane.java` / `backplane/base.py`'s `publish`/`subscribe` abstract methods) instead of letting the inject endpoint reach into a specific instance's connection registry.

## Kafka vs. Redis: durability and replay against simplicity and latency (DRQ-005)

Both backplanes solve the fan-out problem this chapter opened with. They do not solve it the same way, and `_plans/decisions.md`'s DRQ-005 is explicit that this site teaches both rather than picking a winner: "the chapter's point is the trade-off between them... not a single recommended answer." The shape of that trade-off comes straight out of what each broker fundamentally is.

| | Kafka | Redis (Pub/Sub) |
|---|---|---|
| **Durability** | Retained on disk per the topic's retention policy; survives a consumer restart | None — a message exists only as long as a subscriber is actively listening |
| **Replay** | Yes — `auto.offset.reset=earliest` lets a freshly started instance (or `afterEventId` resume, Ch16) read history back | No — Pub/Sub delivers only to currently-subscribed listeners; nothing to replay from |
| **Ordering** | Per-partition, guaranteed; this topic runs one partition so ordering is total for a given `bookingId`'s key | Best-effort, no ordering guarantee across a disconnect/reconnect |
| **Latency** | Higher — a produce-then-fetch round trip through a log, plus consumer poll/commit bookkeeping | Lower — a `PUBLISH` reaches every subscriber directly, no log to write through |
| **Operational cost** | Higher — topics, partitions, consumer-group/offset management, broker storage to size and retain | Lower — a channel is just a string; no partitions, no offsets, no retention to configure |

`examples/part4-backplane/README.md`'s own comparison table draws the same line and adds the practical corollary each cell above implies: Kafka is the right reach "when you need replay/resume or at-least-once delivery guarantees," Redis when you "need low-latency fan-out and can tolerate losing in-flight messages on disconnect." Neither cell is free — Kafka's durability is bought with the topic/partition/offset bookkeeping `KafkaBackplane`'s `subscribe` method visibly carries (the buffer-then-search replay logic earlier in this chapter's code excerpt exists *because* Kafka durability makes it possible, not despite it); Redis's simplicity is bought by accepting that a subscriber that wasn't listening at publish time has permanently missed that message, with no log anywhere to ask for it again. This chapter's example demonstrates both buying the *same* fan-out correctness property — an event injected at B reaches a client on A — for two different prices, which is why DRQ-005 calls for teaching both rather than one.

{% include excalidraw.html file="18-kafka-vs-redis" alt="Two columns under a shared band captioned same fan-out outcome different trade-off, no single winner, DRQ-005. The left column labeled KAFKA durability plus replay shows a topic handling-events keyed by bookingId with a per-instance consumer group for fan-out not load-balanced, then an ink emphasis box reading durable retained on disk replayable powers Ch16 afterEventId resume too, then a box reading cost topic slash partition slash offset bookkeeping a consumer per instance per booking. The right column labeled REDIS simplicity plus latency shows a channel handling-events colon bookingId pub slash sub where every subscriber gets every publish, then an ink emphasis box reading live only no history no replay afterEventId behaves as stateless, then a box reading cost a dropped subscriber loses in-flight messages nothing to catch it back up. An amber arrow runs between the two column headers labeled DRQ-005 contrasted not ranked. A caption states that verify.sh proves the same cross-instance delivery on both brokers for both stacks, and the trade-off is durability slash replay versus operational surface, not correctness." caption="Figure 18.2 -- Kafka and Redis both close the fan-out gap; the difference is what each one gives up to do it cheaply (Redis) or durably (Kafka), not whether the client gets the event." %}

## Connection count and fan-out amplification

Scaling out buys connection capacity, but it changes the shape of the delivery cost: it's tempting to assume "N instances" divides the work by N. In stateless mode that's roughly true: an instance only ever does work for connections it's physically holding. The moment a backplane is in the picture, a single injected event can touch every instance, not just the one holding the relevant connection — in Kafka mode, every instance's own consumer group receives every record on the topic (that's the deliberate per-instance-group choice from earlier in this chapter), and in Redis mode every instance that has ever subscribed to a given booking's channel receives every publish to it. If a booking has exactly one connected client on instance A, injecting one event still means every other instance's backplane consumer wakes up, deserializes the record, checks whether it has any local connections for that `bookingId` (it doesn't), and discards it — `LocalDelivery.deliver`'s loop over `openConnections.findByEndpointId(...)` simply finds nothing to iterate and returns. That's cheap per instance, but it's not zero, and it scales with the number of instances subscribed to the backplane, not with the number of clients actually watching that booking.

This is the amplification worth sizing before it surprises you in production: a backplane with instance count N delivers roughly N times the deserialize-and-filter work per injected event compared to a single-instance deployment, regardless of how many of those N instances actually have a client waiting. For this example's scale — a handful of instances, a handful of test bookings — that cost is invisible. For a deployment with dozens of instances and thousands of distinct bookings each with exactly one connected client, it's the reason a backplane topic/channel is usually partitioned or sharded by some key (this example already keys by `bookingId` for exactly this reason, even though it runs on one partition) rather than treated as one unbounded broadcast domain, and it's part of why Redis's lower per-message cost compared to Kafka's log-structured path matters more as instance count grows — the "N times the work" multiplier lands on a cheaper base operation.

## Where sticky load balancing and the backplane meet

Put the two halves of this chapter back together and the full picture looks like this: sticky sessions are still doing real work — a client's socket still lives on exactly one instance for its entire connection lifetime, and nothing in this chapter asks a load balancer to do anything differently. What changes is what happens on the *server* side of that pinned connection. Before the backplane, an instance's only source of events for a connection it holds was its own local code path — a direct function call, nothing crossing a process boundary. After the backplane, that same instance also has a second source: whatever its Kafka consumer or Redis subscription hands it, originating from any instance, including itself. `LocalDelivery.deliver` (Quarkus) and `_send_event` (Python) don't know or care which source produced the event they're about to push to a WebSocket — the backplane's whole contribution is making sure *an* event produced anywhere ends up calling that same local-delivery path on *every* instance that might have a client waiting for it, so the one instance that actually does gets it.

That's also why this chapter's fix composes with everything Part 4 built before it rather than replacing any of it. Chapter 17's auth check still runs once, at the upgrade, on whichever instance the sticky session happens to route a given client to — the backplane doesn't change who's allowed to connect, only how an event reaches whoever already did. Chapters 15 and 16's reconnect logic still runs per-connection, per-instance — and Chapter 16's Kafka-mode replay is, not coincidentally, implemented against the exact same topic this chapter's fan-out uses, which is why `KafkaBackplane`'s `subscribe` method does double duty: the same durable, replayable history that lets a reconnecting client catch up on what it missed (Ch16) is what lets a *different* instance, with no connection history of its own, pick up a record a sibling instance just published (Ch18). Redis mode gets no such synergy — its `afterEventId` handling is `del after_event_id` on both stacks, accepted for interface symmetry and then ignored, because Pub/Sub keeps nothing to replay from either for a reconnecting client or for an instance that just now subscribed. Durability is a single property that pays for two different chapters' guarantees at once; its absence in Redis mode costs both the same way.

## On the wire

`examples/part4-backplane/verify.sh` runs three sequential `docker compose up`/`down` cycles — stateless (Ch15), Kafka (Ch16 + Ch18), Redis (Ch18) — and its Stage B and Stage C are this chapter's live proof. Each stage connects a client to instance A, injects an event through instance B's HTTP endpoint, and asserts two separate things: that A's *client* received B's event, and that A's own *server log* shows it doing the delivering — `wait_for_docker_log_pattern` greps `docker logs` for the exact line `PROTOCOL.md`'s "Instance identity" section specifies:

```bash
cd examples/part4-backplane
./verify.sh
```

Stage B (`--profile kafka`), after Ch16's replay proof, runs Ch18's fan-out check on both stacks:

```
=== Stage B: --profile kafka — Ch16 replay + Ch18 fan-out (kafka) ===
--- quarkus/kafka Ch18 fan-out: instance A (localhost:8080) <- instance B (localhost:8083) (bookingId={% raw %}bkg_...{% endraw %}) ---
lib.sh: inject eventId={% raw %}evt_...{% endraw %} bookingId={% raw %}bkg_...{% endraw %} via localhost:8083 -> HTTP 202
lib.sh: ok — quarkus/kafka: instance A's CLIENT received instance B's injected event {% raw %}evt_...{% endraw %}
lib.sh: ok — quarkus/kafka: instance A's own SERVER LOG shows it delivering (instance=quarkus-a)
--- python/kafka Ch18 fan-out: instance A (localhost:8081) <- instance B (localhost:8084) (bookingId={% raw %}bkg_...{% endraw %}) ---
lib.sh: ok — python/kafka: instance A's CLIENT received instance B's injected event {% raw %}evt_...{% endraw %}
lib.sh: ok — python/kafka: instance A's own SERVER LOG shows it delivering (instance=python-a)

=== Stage B complete: Ch18 fan-out PROVEN LIVE on both stacks over Kafka ===
```

Stage C (`--profile redis`) runs the identical assertion against the Redis backplane instead — same client-on-A, inject-via-B shape, same two-part proof:

```
=== Stage C: --profile redis — Ch18 fan-out (redis) ===
--- quarkus/redis Ch18 fan-out: instance A (localhost:8080) <- instance B (localhost:8083) (bookingId={% raw %}bkg_...{% endraw %}) ---
lib.sh: ok — quarkus/redis: instance A's CLIENT received instance B's injected event {% raw %}evt_...{% endraw %}
lib.sh: ok — quarkus/redis: instance A's own SERVER LOG shows it delivering (instance=quarkus-a)
--- python/redis Ch18 fan-out: instance A (localhost:8081) <- instance B (localhost:8084) (bookingId={% raw %}bkg_...{% endraw %}) ---
lib.sh: ok — python/redis: instance A's CLIENT received instance B's injected event {% raw %}evt_...{% endraw %}
lib.sh: ok — python/redis: instance A's own SERVER LOG shows it delivering (instance=python-a)

=== Stage C complete: Ch18 fan-out PROVEN LIVE on both stacks over Redis ===
```

The server-log assertion is the part worth not skating past: a client-observed frame alone would prove *something* delivered the event, but not that instance A's own process is the one that did it — `wait_for_docker_log_pattern` checks `docker logs part4-backplane-quarkus-a` (and its Python/instance-B equivalents) for the literal string `delivered eventId=<id> bookingId=<id> instance=quarkus-a`, which only ever gets written by `LocalDelivery.deliver`/`_send_event` running inside instance A's own process. That closes the loop this chapter opened with: the event entered through B, crossed a shared Kafka topic or Redis channel, and a different process — A — picked it up and pushed it to the client A itself is holding, on both brokers, on both stacks. The run finishes with one combined `PASS` covering all three stages:

```
PASS — Part 4 backplane: Quarkus and Python both implement the SAME
reconnect + scale-out behavior (PROTOCOL.md) — Ch15 stateless mode
loses a gap-era event, Ch16 kafka mode replays it after reconnect
(dedup by eventId, no more than the documented benign duplicate),
and Ch18 an event injected through instance B reaches a client
connected to instance A over BOTH the Kafka and the Redis backplane,
with instance A's own log confirming it did the delivering.
```

## Where this goes next

This chapter closes Part 4. Chapters 12 through 17 hardened a single connection — backpressure, error envelopes, heartbeats, reconnect with and without replay, authentication at the upgrade — and this chapter took the last step those chapters all implicitly deferred: what happens once more than one instance exists behind that hardened connection. The answer turned out to need nothing new from any earlier chapter, only something shared between instances that none of them required on their own — a backplane that every instance subscribes to and any instance can publish to, closing the gap a sticky load balancer was never going to close by itself. Kafka and Redis both close it; DRQ-005's contrast is the chapter's real content, not a detail to skim past, because choosing between them in a real deployment means choosing between a replay guarantee you may never use and an operational surface you'd rather not run, or a simpler channel that quietly drops anything published while a subscriber wasn't listening.

Part 5, Performance & Optimization, picks up from here with a different kind of scaling question: not "can an event reach the right instance" but "how much data can one connection carry, and how fast." Chapter 19 moves the wire format itself from JSON to binary Protobuf frames — a change orthogonal to everything in this chapter (a backplane doesn't care what bytes it's forwarding) but one that compounds with it: a fan-out system paying the per-instance amplification cost this chapter described benefits doubly from a smaller, faster-to-serialize payload on every hop. Chapter 20 picks up throughput optimization from there. Neither chapter revisits the backplane directly, but every later example still runs on top of the same two-instance, dual-broker topology this chapter introduced — the default production shape assumed from here forward, not a special case to leave behind.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>A sticky load balancer solves one problem — keeping a client's connection on the same instance — and does nothing for a different problem it's easy to conflate with it: getting an event from wherever it originates to whichever instance happens to be holding the connection that wants it. Close that second gap with a backplane every instance subscribes to and any instance can publish to (a Kafka topic with a per-instance, non-shared consumer group, or a Redis Pub/Sub channel), never by trying to route events through the load balancer or by reaching across instances directly. Teach Kafka and Redis as a contrasted pair, not a recommendation: Kafka buys durability and replay (it also powers resume-after-reconnect at no extra cost) against topic/partition/offset bookkeeping and a consumer per instance per booking; Redis buys near-zero operational surface and lower latency at the cost of losing anything published while a subscriber wasn't listening, with no log anywhere to ask for it again. Expect fan-out to cost roughly one deserialize-and-filter per instance per event, not per connected client — a backplane with N instances subscribed does N times the discard work of a single instance, regardless of how many of those instances actually have someone watching, so size the instance count and the partitioning/keying strategy with that multiplier in mind rather than assuming scale-out divides cost evenly.</p></div>

## For deeper coverage

- Adam Bellemare, *Building Event-Driven Microservices, Second Edition* (O'Reilly, 2025) — the broker-as-broadcast-channel reasoning behind giving each instance its own consumer group instead of sharing one.
- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026) — the durability-versus-latency trade-off this chapter's Kafka-versus-Redis comparison is a concrete instance of.
- Sam Newman, *Building Microservices, 2nd Edition* (O'Reilly, 2021) — scaling a service beyond one instance and the shared-state problems, cross-instance fan-out among them, that introduces.
- *Cloud Native Design Patterns* — "WebSockets at Scale" chapter — the pub/sub-backplane-plus-resume-don't-restart posture this chapter's two-broker proof directly implements.
- [Apache Kafka documentation](https://kafka.apache.org/documentation/) and [Redis Pub/Sub documentation](https://redis.io/docs/latest/develop/interact/pubsub/) — the two broker mechanisms this chapter contrasts side by side.
