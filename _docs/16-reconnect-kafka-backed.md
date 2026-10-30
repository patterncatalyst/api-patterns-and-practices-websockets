---
title: "Reconnect: Kafka-Backed"
order: 16
part: "Production Concerns"
description: "Reconnecting a client against a Kafka-backed log so it can resume exactly where it left off."
duration: "14 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain what changes between stateless and `--profile kafka` mode: the same `?afterEventId=` query parameter now resolves against a durable, replayable `handling-events` topic keyed by `bookingId`.
- Trace `KafkaBackplane.replayFor`'s found/not-found branches and explain why a seed-event id is guaranteed to miss, replaying the topic's full history instead of erroring.
- Explain why the Python `KafkaBackplane.subscribe` buffers a per-connection history before searching for `after_event_id`, rather than deciding skip-versus-yield while streaming.
- Reason about the one documented, dedup-absorbed race between Quarkus's always-on `@Incoming` consumer and its per-connection replay snapshot, and why the Python sibling never hits it.
- State retention's role as the hard bound on how far back a replay can reach, and recognize when that bound, not the replay logic, is what needs to change.

## Why this matters

Stateless reconnect has a hard limit: a client gets the connection back, not the frames that were pushed while it was down. `examples/part4-backplane`'s default profile proves that limit live: `verify.sh`'s `run_ch15_stateless_gap` connects a client, disconnects it, injects an event into the gap, reconnects with `?afterEventId=<last seen eventId>`, and asserts the gap event is **not** in the log. No broker, no history, nothing to ask. This chapter runs the other half of the same example: `--profile kafka` stands up the identical server code against a real `apache/kafka:4.3.1` broker, and `run_ch16_kafka_replay` runs the exact same disconnect-inject-reconnect sequence and asserts the opposite outcome: the gap event **is** delivered after reconnect, replayed from a durable topic the client never directly touches. Same wire contract, same `?afterEventId=` query parameter, same three-event fixture seed. The only thing that changes between the two modes is whether anything durable sits behind the socket to answer a reconnecting client's implicit question: what did I miss?

## The topic behind the socket

`PROTOCOL.md`'s "Backplane modes" section is specific about what changes in kafka mode: "the server has the booking's event history from the Kafka topic (within retention). On connect it replays the events after `afterEventId` (or, if absent, from the live tail), then continues live." Both stacks implement this with a single Kafka topic, `handling-events`, keyed by `bookingId`. This example uses one partition, but the keying is what would let a production deployment shard by booking across many partitions without breaking per-booking ordering, since Kafka guarantees order only within a partition and every record for a given booking always lands in the same one. `KafkaBackplane.java`'s class Javadoc calls this "replay doubles as the history store": `auto.offset.reset=earliest` means a freshly started Quarkus instance replays the topic from the beginning into its in-memory `injected` map before any client ever connects, so a reconnecting client's `afterEventId` search always has the full picture to filter against, not just whatever this particular instance happened to see since its own uptime began. The Python sibling's `kafka_backplane.py` reaches the same guarantee a different way: `KafkaBackplane.subscribe` opens a fresh consumer per connection with `auto_offset_reset="earliest"` and does its own history scan at subscribe time, rather than keeping one long-lived in-memory map the way the Quarkus instance does.

What makes this durable rather than merely "better buffered" is the thing both READMEs are careful to state as a design decision rather than an accident: the topic carries **only injected events**, never the three-event fixture seed. `app/ws_server.py`'s `_deliver_loop` sends the seed directly from `feed.py` on every connection, in every backplane mode, before it ever touches `backplane.subscribe`; the Quarkus `HandlingEventBackplaneWebSocket.onOpen` does the identical split, sending `feed.events()` unconditionally and only asking `BackplaneRouter.replayFor` for whatever comes after it. The Python README's "Design note" states the reason directly: this keeps the deterministic baseline "byte-for-byte identical across stateless/kafka/redis," so a fresh connection in any mode sees the same three events regardless of which `Backplane` implementation happens to be wired up. The consequence that matters for this chapter is that `afterEventId` naming one of those three seed event ids can never be found in the topic's own history, since it was never produced there, and both implementations treat that as the expected case, not an edge case to special-case around.

## Resuming from afterEventId: found, not found, and the fallback

A client reconnects with `?afterEventId=<the last eventId it saw>`. Both stacks answer the same three-way question against the topic's history: was that id found, and if so, what comes after it? `KafkaBackplane.java`'s `replayFor` snapshots this booking's injected-event history (a `List.copyOf` of a `CopyOnWriteArrayList`, so concurrent appends from the always-running `@Incoming` consumer can't leak a partially built list into the search) and walks it looking for `afterEventId`. Found means replay the suffix strictly after it, so nothing the client already saw gets resent. Not found means replay the **entire snapshot**, and the Javadoc spells out exactly when that happens: "expected whenever `afterEventId` names a fixture event (the Ch15 gap scenario: a client's last-seen id, right after connecting, is one of the 3 seed events); fixture ids never appear in this buffer at all, so the search always misses for them." The Python implementation reaches the identical decision through a different mechanism, because `aiokafka` gives it a consumer and offsets rather than Quarkus's always-on, continuously-updated map:

{% include codetabs.html langs="Quarkus|Python" %}

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
```python
if after_event_id is not None:
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
else:
    await consumer.seek_to_end(*topic_partitions)
```

The Python code is doing something the Java side doesn't have to: deciding, from a cold start, how far "the current end of the topic" is, because `KafkaBackplane` opens a brand-new `AIOKafkaConsumer` on every `subscribe` call rather than keeping one running continuously. `seek_to_beginning` plus `end_offsets` snapshots where the live tail was at the moment this client connected, then `remaining` tracks how many records are still owed per partition before that snapshot is fully buffered; `history` accumulates every record for this `booking_id` seen along the way, and the loop only stops once every partition has delivered up to its snapshotted end offset. Only after the whole history is buffered does the search for `after_event_id` run, exactly the same found/not-found logic as the Java side, line for line in spirit if not in syntax.

The module docstring explains why buffering has to happen before deciding, not during: streaming can't know in advance whether an id will ever show up, so it can't decide in time whether the record it's looking at right now should ultimately be kept. Deciding skip-versus-yield while streaming has a sharp edge: it can hang indefinitely when the only historical record is also the last one before the live tail, an off-by-one in "have we reached the subscribe-time snapshot" bookkeeping. Buffering first and searching second, the shape both snippets above show, avoids that edge entirely.

## Seed-direct, injected-to-topic: why the split matters for resume

{% include excalidraw.html file="16-topic-offset-resume" alt="A diagram showing the seed feed delivered directly to the client bypassing Kafka entirely, the inject endpoint publishing keyed records into the handling-events topic, the subscribe/replayFor step searching that topic for afterEventId with a found-replay-suffix or not-found-replay-everything branch, and a ghost box showing records older than retention as unrecoverable; a replay burst and the always-on live consumer can double-deliver the same event, which the client resolves by deduping on eventId." caption="Figure 16.1: the topic/offset/resume model: the seed never touches Kafka, only injected events are keyed into the topic by bookingId, and an afterEventId that names a seed id always falls back to replaying everything currently in the topic." %}

The seed-direct/injected-only split from the previous section is what makes the found/not-found fallback *correct* rather than merely convenient. Picture the alternative: if the three fixture events were also produced to the topic on every connection, a reconnecting client's `afterEventId` naming the third seed event would be **findable** in the topic, and "replay the suffix after it" would work by coincidence, until the topic accumulated enough history from prior test runs or prior bookings that finding the right occurrence became ambiguous. Keeping the seed out of Kafka entirely sidesteps that: a seed-event id can *never* match anything in the topic, so the not-found branch is always the right branch for it, deterministically, regardless of how much other history has accumulated on the shared topic from other bookings. `verify.sh`'s own comment on `LAST_SEED_EVENT_ID` makes this explicit: it names the fixture's third event id as "the correct `?afterEventId=` value for every reconnect test below no matter which generated bookingId that test uses," precisely because that id's absence from the topic is a structural guarantee, not a timing accident.

This is also why `compose.yaml` running four app instances against one shared Kafka container, exercised across three sequential `verify.sh` stages, doesn't produce cross-contamination between scenarios: every `Backplane` implementation filters strictly by `bookingId`, and `verify.sh` generates a fresh `bookingId` for every scenario even though all four instances share one physical topic. A found-vs-not-found search against a shared topic is only trustworthy if the thing being searched for is scoped correctly in the first place: the `bookingId` key does that scoping, and the seed/injected split does the rest.

## Dedup by eventId: the benign race this chapter absorbs

{% include excalidraw.html file="16-gap-filled-by-replay" alt="A two-row timeline. The top row, Ch15 stateless, shows connect, disconnect, a gap event injected that nothing stores, reconnect with afterEventId, and the gap event lost because afterEventId is ignored. The bottom row, Ch16 kafka, shows the same connect and disconnect, but the gap event is published to the durable handling-events topic, and after reconnect with the same afterEventId it is replayed exactly once because the id is not found and the topic's full history is replayed." caption="Figure 16.2: the same disconnect/inject/reconnect sequence as the stateless-reconnect example, but a durable topic behind the socket turns 'lost' into 'filled, exactly once.'" %}

"Exactly once" in the delivery-guarantee sense takes more machinery to guarantee than the phrase suggests, and the part4-backplane README is upfront about where this example lands: not a guarantee, but a documented, bounded, benign race that a dedup step absorbs. On the Quarkus side, `KafkaBackplane`'s `@Incoming` consumer runs continuously, in the background, regardless of whether any client is connected, because SmallRye Reactive Messaging wires `@Incoming` statically, so it's always consuming:

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

That `localDelivery.deliver` call pushes the event to every **currently open** connection watching this booking, the instant the record arrives, independent of whatever `onOpen` is doing for a client that connected moments earlier. If a client's reconnect lands at just the wrong moment (its WebSocket connection is already registered and open, but `onOpen`'s own `replayFor` snapshot hasn't finished being computed and returned yet), the same gap event can reach that client twice: once in the `Multi` that `onOpen` returns (because `replayFor`'s snapshot already includes it) and once from `consume`'s direct `localDelivery.deliver` call (because the connection is already live). `PROTOCOL.md` names this directly as "a narrow timing window on reconnect," and the README is specific about the mechanism: "Quarkus's always-on Kafka consumer and its per-connection `replayFor` snapshot are not synchronized against each other." The Python implementation doesn't have this exposure at all, because it never runs a background consumer independent of a connection: `kafka_backplane.py`'s `subscribe` opens one consumer per connection, buffers the history, replays it, and only then starts the live loop on that same consumer, so there's no second code path that could deliver the same record through a different channel. The README states the contrast directly: "in practice its count is always 1."

`verify.sh`'s `run_ch16_kafka_replay` treats this as a known, bounded outcome rather than a flaw to paper over: the comment on the assertion spells out the full harness convention: "a raw frame count of 1 **or** 2 for that one event both count as PASS (0 means it was lost; more than 2 would mean something is actually wrong)." That convention stands in for what a real downstream consumer should do on its own: key on `eventId`, treat a repeat of an id it has already processed as a no-op, and get exactly-once *processing* semantics on top of a transport that only promises at-least-once in this narrow window. `PROTOCOL.md`'s "Resume parameter" section states the client-facing contract this way: "the client dedups by `eventId`; net effect = every gap-era event delivered exactly once, no duplicates." That line is doing real work: it turns "this specific implementation has a known timing race" into "the wire contract still delivers exactly-once semantics to any client that implements the dedup it was always going to need anyway," because a reconnecting client that doesn't key on `eventId` already has to tolerate *some* duplication risk the moment a server can replay history at all, broker or no broker.

## Retention: the bound on how far back a replay can reach

A topic's durability extends only as far as its retention policy keeps records around, and that's the one place this example's generosity (`auto.offset.reset=earliest`, replay-the-whole-topic-on-miss) runs into a hard wall rather than a design choice. A client that reconnects after being disconnected longer than the topic's retention window finds that the events from early in the gap have already aged out: `KafkaBackplane.subscribe`'s buffering loop and `KafkaBackplane.java`'s `replayFor` can only replay what Kafka still has; neither implementation has any way to reconstruct a record the broker has already deleted. This is the dividing line between "kafka mode" and an actual audit-grade event store: a topic configured with a short retention (hours, to bound disk usage on a high-volume topic) buys resilience against the ordinary disconnects this chapter's scenario models (a network blip, a server restart, a client that was offline for a coffee break) without buying protection against a client that's been disconnected for a week. If a consumer cannot tolerate ever losing history no matter how long it's offline, the fix is a retention policy sized to that requirement (or a compacted/tiered topic, or a separate durable sink entirely), not a change to the replay logic itself: the logic already replays everything it can reach; retention decides what "everything" means.

## The cost: a broker and a consumer per instance

None of this is free: durability spends what stateless reconnect's simplicity bought. The stateless mode in `examples/part4-backplane` needs nothing beyond the application process itself: no broker, no topic to provision, no consumer group to manage, no retention policy to size. Kafka mode needs all of it: `compose.yaml` brings up an `apache/kafka:4.3.1` container and gates every app instance on `wait_for_tcp localhost 9092 90` before the readiness probe even starts; `application.properties` wires a distinct consumer group per instance (`${INSTANCE_ID:quarkus}-handling-events`) so Kafka's normal load-balancing-across-a-shared-group behavior doesn't eat events a per-instance history needs to see in full; and both `KafkaBackplane` implementations carry real operational surface: offsets, partition assignment, `auto.offset.reset` semantics, and, on the Python side, a buffering strategy that exists because `aiokafka`'s streaming model doesn't hand you "replay this range" as a primitive. The part4-backplane top-level README's comparison table is blunt about where this lands: kafka mode means "higher" latency and complexity from "topic/partition/offset bookkeeping," against redis mode's "pure pub/sub" and stateless mode's "N/A." None of the three modes is "better" in the abstract: the table's own framing is that the contrast is the point. Reach for Kafka when resume, replay, or at-least-once delivery guarantees are a real requirement of what's being built, not as a default upgrade from stateless the moment a production deployment needs more than one instance. Fan-out across instances serving the same booking needs a backplane of some kind, but not necessarily Kafka: Redis buys the fan-out half of that at a fraction of the operational cost, with no replay at all.

## On the wire

`examples/part4-backplane/verify.sh`'s Stage B is where this chapter's claims stop being Javadoc and docstrings and become something a script has to observe to print `PASS`. It brings the whole stack up with `--profile kafka`, waits for the broker's port, then runs `run_ch16_kafka_replay` against both stacks: connect, confirm the three seed frames, disconnect, inject a gap event, reconnect with `?afterEventId=<last seed eventId>`, and assert the gap event shows up:

```bash
wait_for_log_count "$log" '"eventType":"CUSTOMS"' 1 20
wait_for_log_pattern "$log" "\"eventId\":\"${gap_event_id}\"" 40
sleep 3

local raw_count
raw_count="$(grep -cF "\"eventId\":\"${gap_event_id}\"" "$log" || true)"
if (( raw_count < 1 )); then
  echo "lib.sh: FAIL — $stack ch16: gap event $gap_event_id was NOT delivered after reconnect" >&2
  return 1
fi
if (( raw_count > 2 )); then
  echo "lib.sh: FAIL — $stack ch16: gap event $gap_event_id delivered $raw_count times — beyond the documented at-most-2 replay/live race" >&2
  return 1
fi
```

Run it from the repo root:

```bash
bash examples/part4-backplane/verify.sh
```

A representative run shows Stage A proving the Ch15 loss on both stacks, then Stage B bringing Kafka up and proving the opposite outcome:

```
=== Stage A complete: Ch15 stateless gap PROVEN LIVE on both stacks ===

=== Stage B: --profile kafka — Ch16 replay + Ch18 fan-out (kafka) ===
--- quarkus Ch16 kafka replay (bookingId=bkg_...) ---
lib.sh: ok — quarkus ch16: connected, received 3 seed frames, disconnected
lib.sh: inject eventId=evt_... bookingId=bkg_... via localhost:8080 -> HTTP 202
lib.sh: ok — quarkus ch16: gap event evt_... delivered after reconnect (raw frame count=2; dedup-by-eventId => exactly one logical delivery; count=2 is PROTOCOL.md's documented benign replay-vs-live race)
--- python Ch16 kafka replay (bookingId=bkg_...) ---
lib.sh: ok — python ch16: connected, received 3 seed frames, disconnected
lib.sh: inject eventId=evt_... bookingId=bkg_... via localhost:8082 -> HTTP 202
lib.sh: ok — python ch16: gap event evt_... delivered after reconnect (raw frame count=1; dedup-by-eventId => exactly one logical delivery; count=2 is PROTOCOL.md's documented benign replay-vs-live race)

=== Stage B: Ch16 kafka replay PROVEN LIVE on both stacks ===
```

Both stacks pass with a raw frame count the harness accepts as either 1 or 2: the Quarkus instance's always-on consumer is the one that hits the documented race in practice, producing 2; the Python instance's per-connection buffer-then-replay consumer is the one the part4-backplane README says is "always 1" in practice, and this run bears that out. Either count means the same thing to a real client that dedups on `eventId`: the gap event arrived, exactly once, logically; that is the outcome stateless reconnect proved was structurally impossible without a broker behind the socket.

## Where this goes next

This chapter closed the gap stateless reconnect left open: a durable, replayable Kafka topic behind the socket, keyed by `bookingId`, carrying only injected events so the deterministic fixture seed stays identical across every mode, lets a reconnecting client's `afterEventId` resolve to either "replay the suffix after it" or "replay everything, because that id predates anything this topic has ever carried," and either branch is a correct answer. The cost is real: a broker to run, a consumer per instance to manage, offset and retention bookkeeping neither stateless nor Redis mode needs, and one documented, bounded, dedup-absorbed race on the Quarkus side that the Python implementation's different internal shape avoids entirely. The same `examples/part4-backplane` example comes back from a different angle once more than one instance serves the same booking: not "did a reconnecting client miss anything," but "does an event injected through one instance reach a client connected to a different instance," proved over both this chapter's Kafka backplane and the simpler, non-replayable Redis alternative, so the two durability options this part has now built sit side by side as a real choice rather than a hierarchy with one obvious winner.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>A reconnecting client that cannot tolerate missing events needs a durable, replayable log behind the socket, not a cleverer reconnect loop on the client: stateless reconnect proves that no amount of client-side sophistication recovers data the server never kept. This chapter's answer is a Kafka topic (<code>handling-events</code>, keyed by <code>bookingId</code>) carrying only injected events, never the fixture seed, so a client's <code>?afterEventId=</code> resolves against that topic's history as either "replay the suffix after this id" (found) or "replay everything the topic has" (not found: the expected outcome whenever the id names a seed event, which never reaches the topic at all). A real consumer dedups on <code>eventId</code> to absorb the one documented race this example discloses: Quarkus's always-on consumer and its per-connection replay snapshot can, in a narrow timing window, deliver the same gap-era event twice; <code>verify.sh</code> accepts a raw frame count of 1 or 2 for exactly this reason, and the Python sibling's per-connection buffer-then-replay design doesn't hit the race at all. None of this is free: a broker, a consumer group per instance, and a retention policy that bounds how far back a replay can reach are real operational cost stateless reconnect never had to pay. Reach for it when resume or at-least-once delivery is a real requirement of what's being built, not as a default upgrade the moment a service needs more than one instance: Redis buys cross-instance fan-out without any of this chapter's replay machinery, at the cost of giving up replay entirely.</p></div>

## For deeper coverage

- Adam Bellemare, *Building Event-Driven Microservices, Second Edition* (O'Reilly, 2025): the event-log durability and consumer-offset model this chapter's `handling-events` topic and replay-on-reconnect logic is built on.
- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026): replication logs, retention, and the at-least-once-versus-exactly-once distinction behind this chapter's dedup-by-`eventId` contract.
- Unmesh Joshi, *Patterns of Distributed Systems* (Addison-Wesley, 2023): the Replicated Log and Idempotent Receiver patterns this chapter's durable topic and client-side `eventId` dedup directly implement.
- *Cloud Native Design Patterns*, "Event-Driven" chapter: the event-backbone reasoning (commit-after-side-effect, schemas as contract) behind treating a Kafka topic as a history store.
- [Apache Kafka documentation](https://kafka.apache.org/documentation/): consumer offsets, `auto.offset.reset`, and the retention policy that bounds this chapter's replay.
