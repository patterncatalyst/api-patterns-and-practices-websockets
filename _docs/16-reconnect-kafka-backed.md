---
title: "Reconnect: Kafka-Backed"
order: 16
part: "Production Concerns"
description: "Resuming a reconnecting client from a durable Kafka topic, and absorbing the duplicate delivery that replay can cause."
duration: "11 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain what changes under `--profile kafka`: the same `?afterEventId=` resolves against a durable `handling-events` topic keyed by `bookingId`.
- Trace the found and not-found branches of `replayFor`, and why a seed event id always misses and replays the whole history.
- Explain why the Python backplane buffers a connection's history before searching for `after_event_id`.
- Absorb the documented replay-versus-live duplicate on Quarkus by deduplicating on `eventId`.
- State retention as the hard bound on how far back a replay reaches.

## Why this matters

Stateless reconnect returns the connection and not the frames pushed while it was down. With a Kafka broker behind the same server code, the same disconnect, inject and reconnect sequence ends differently: the gap event is replayed from a durable topic the client never touches. The wire contract, the `?afterEventId=` parameter and the three-event fixture seed are unchanged. The only difference is whether anything durable answers a reconnecting client's implicit question, "what did I miss?"

{% include excalidraw.html file="16-gap-filled-by-replay" alt="A two-row timeline. In the stateless row the gap event is injected, nothing stores it, and it is lost after reconnect. In the Kafka row the gap event is published to the handling-events topic and replayed exactly once after reconnect." caption="Figure 16.1: The same disconnect, inject and reconnect sequence as stateless reconnect, but a durable topic turns a lost event into a replayed one." %}

## Pattern: Resume from a sequence number

### The problem

A server that fans events out to open connections remembers nothing. A client that reconnects with `?afterEventId=<last seen>` needs the server to find that id in an ordered record and send what followed. The record has to survive instance restarts and be readable by whichever instance the client lands on.

### The solution

**Resume from a sequence number** lets a reconnecting client name the last event it saw and has the server replay everything after it from an ordered, retained record: here, a Kafka topic keyed by `bookingId`, searched for the id.

Use it when:

- resume, replay or at-least-once delivery is a requirement of the feature;
- reconnecting clients may land on a different instance than they left;
- you can run and size a broker, a consumer group per instance, and a retention policy.

### How Quarkus and Python model it

Both stacks use one topic, `handling-events`, keyed by `bookingId`. It runs one partition; the key is what lets a production deployment shard by booking across partitions without breaking per-booking order, because Kafka orders only within a partition.

The topic carries only injected events, never the fixture seed. Each connection sends the seed directly from the feed in every mode, then asks the backplane for whatever follows. That keeps the baseline identical across stateless, Kafka and Redis, and it has a consequence for resume: a seed event id is never in the topic, so it always misses. Both stacks treat the miss as the expected case. The split is what makes the fallback correct and not merely convenient. If the seed were produced to the topic on every connection, a seed id would be findable, and once the topic held history from earlier connections, finding the right occurrence would be ambiguous. Kept out, a seed id never matches, so the not-found branch is always the right one for it. Every backplane also filters strictly by `bookingId`, so many bookings sharing one physical topic never contaminate each other's search.

{% include excalidraw.html file="16-topic-offset-resume" alt="The seed feed goes directly to the client and bypasses Kafka. The inject endpoint publishes keyed records to the handling-events topic. Subscribe or replayFor searches the topic for afterEventId and either replays the suffix or replays everything. Records older than retention are unrecoverable. A replay burst and the live consumer can deliver the same event twice, which the client resolves by deduplicating on eventId." caption="Figure 16.2: The seed never touches Kafka. Only injected events are keyed into the topic by bookingId, and an afterEventId that names a seed id falls back to replaying everything in the topic." %}

Resume has three outcomes. With no `afterEventId`, nothing is replayed and the client gets the seed plus the live tail. If the id is found, the server replays the suffix strictly after it, so nothing the client saw is resent. If it is not found, the server replays the entire history: the client's last known state predates anything the topic carries, so "replay everything" is correct and "replay nothing" is not.

On Quarkus, `auto.offset.reset=earliest` makes a starting instance replay the topic into an in-memory map of injected events before any client connects, so the search sees the full history and not only what this instance saw since it started. `replayFor` snapshots that map with `List.copyOf` over a `CopyOnWriteArrayList`, so concurrent appends from the always-running consumer can't leak a half-built list into the search.

```java
    @Override
    public List<HandlingEvent> replayFor(String bookingId, String afterEventId) {
        List<HandlingEvent> snapshot = List.copyOf(injected.getOrDefault(bookingId, List.of()));
        if (afterEventId == null || afterEventId.isBlank()) {
            return List.of();
        }

        int index = -1;
        for (int i = 0; i < snapshot.size(); i++) {
            if (snapshot.get(i).eventId().equals(afterEventId)) {
                index = i;
                break;
            }
        }
        if (index < 0) {
            Log.infof("afterEventId=%s not found in injected history for bookingId=%s "
                            + "(expected when it names a fixture-seed event); replaying all %d injected event(s)",
                    afterEventId, bookingId, snapshot.size());
            return snapshot;
        }
        return List.copyOf(snapshot.subList(index + 1, snapshot.size()));
    }
```

Python opens a new `AIOKafkaConsumer` (with `auto_offset_reset="earliest"`) on every `subscribe`, so it has to decide from a cold start where "now" is. `aiokafka` offers no "replay this range" primitive. It seeks to the beginning, snapshots the current end offsets, and buffers every record for this booking up to that snapshot. Only then does it search:

```python
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
```

Buffering first is deliberate. Streaming can't know whether the id will ever appear, so it can't decide in time whether the record in hand should be kept. Deciding while streaming can also hang when the only historical record is the last one before the live tail, an off-by-one in the "reached the snapshot" bookkeeping.

### The duplicate you must absorb

On Quarkus, SmallRye Reactive Messaging wires `@Incoming` statically, so the consumer runs continuously, whether or not a client is connected:

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

`localDelivery.deliver` pushes the event to every open connection for the booking the moment the record arrives. If a reconnect lands in the narrow window where the connection is already registered but `onOpen`'s `replayFor` snapshot hasn't returned, the client gets the gap event twice: once in the replay and once from the live push. The consumer and the per-connection snapshot aren't synchronized against each other.

Python never has this window. It opens one consumer per connection, buffers, replays, and then runs the live loop on that same consumer, so there is one delivery path.

The contract absorbs it: the client dedups by `eventId`, and the net effect is every gap-era event delivered once. A consumer should key on `eventId` and treat a repeat as a no-op. That gives exactly-once processing over a transport that promises at-least-once in this window. Any server that can replay history can repeat an event, broker or not.

## Retention

A topic's durability extends as far as its retention policy. A client that was gone longer than retention finds the early events of the gap already deleted, and neither `replayFor` nor `subscribe` can reconstruct a record the broker dropped. Short retention (hours) bounds disk use and covers ordinary disconnects: a network blip, a restart, a coffee break. It does not cover a client offline for a week. If history can never be lost, change the retention policy (or use a compacted or tiered topic, or a separate durable sink). The replay logic already sends everything it can reach; retention decides what that is.

## The cost

| | Stateless | Kafka | Redis |
|---|---|---|---|
| Infrastructure | None | Broker, topic, consumer group per instance, retention policy | Redis |
| Replay on reconnect | No | Yes, within retention | No |
| Cross-instance fan-out | No | Yes | Yes |
| Complexity | Lowest | Topic, partition and offset bookkeeping | Pure Pub/Sub |

`compose.yaml` brings up an `apache/kafka:4.3.1` container under the `kafka` profile, and every app instance `depends_on` the broker with `condition: service_healthy` and `required: false`, so the default profile starts without one. Each instance gets its own consumer group (`${INSTANCE_ID:quarkus}-handling-events`), so Kafka's load-balancing within a shared group doesn't divide up events that every instance's history needs to see in full.

> **Decision**
>
> A client that can't tolerate missing events needs a durable, replayable log behind the socket. Key a retained topic by `bookingId`, keep the seed out of it, resolve `afterEventId` as found (replay the suffix) or not found (replay everything), and dedup on `eventId` on the client. If you only need cross-instance fan-out, use Redis and accept that replay is gone.

> **🤖 Explore with your agent**
>
> "In examples/part4-backplane, start the stack with --profile kafka, connect to /ws/v1/bookings/{bookingId}/handling-events, disconnect after the three seed frames, POST two events to /internal/bookings/{bookingId}/handling-events, and reconnect with ?afterEventId set to the first injected eventId. Report which events are replayed, and add a client-side set of seen eventIds so a duplicate from the Quarkus replay-versus-live race is dropped."
>
> Check: only the second injected event arrives after the reconnect; reconnecting with the last seed eventId instead replays both injected events.

## Build, run, observe

```bash
bash examples/part4-backplane/verify.sh
```

The script runs Stage A (stateless), Stage B (`--profile kafka`) and Stage C (Redis fan-out). In Stage B it waits for the broker's port, then for each stack connects, confirms the three seed frames, disconnects, injects a gap event and reconnects with `?afterEventId=` set to the last seed id. It passes when the gap event arrives at least once and at most twice; zero means it was lost, and more than two is a real bug beyond the documented race.

```
--- quarkus Ch16 kafka replay (bookingId=bkg_...) ---
lib.sh: ok, quarkus ch16: connected, received 3 seed frames, disconnected
lib.sh: inject eventId=evt_... bookingId=bkg_... via localhost:8080 -> HTTP 202
lib.sh: ok, quarkus ch16: gap event evt_... delivered after reconnect (raw frame count=2; ...)
--- python Ch16 kafka replay (bookingId=bkg_...) ---
lib.sh: ok, python ch16: connected, received 3 seed frames, disconnected
lib.sh: inject eventId=evt_... bookingId=bkg_... via localhost:8082 -> HTTP 202
lib.sh: ok, python ch16: gap event evt_... delivered after reconnect (raw frame count=1; ...)
```

A recorded run shows Quarkus at a raw count of 2 and Python at 1, matching the race above. Either count is one logical delivery to a client that dedups on `eventId`.

Experiments:

- Reconnect with `?afterEventId=` set to the injected gap event's own id: the id is found, the suffix after it is empty, and nothing replays.
- Shorten the topic's retention below the time a client stays disconnected: events from the start of the gap no longer replay.

## For deeper coverage

- Adam Bellemare, *Building Event-Driven Microservices, Second Edition* (O'Reilly, 2025): the event-log durability and consumer-offset model behind the topic and replay-on-reconnect.
- Martin Kleppmann and Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026): replication logs, retention, and the at-least-once versus exactly-once distinction behind the dedup contract.
- Unmesh Joshi, *Patterns of Distributed Systems* (Addison-Wesley, 2023): the Replicated Log and Idempotent Receiver patterns this design implements.
- *Cloud Native Design Patterns*, "Event-Driven" chapter: treating a Kafka topic as a history store.
- [Apache Kafka documentation](https://kafka.apache.org/documentation/): consumer offsets, `auto.offset.reset`, and the retention policy that bounds replay.
