---
title: "Reconnect: Stateless"
order: 15
part: "Production Concerns"
description: "Reconnecting a client with no server-side session to resume."
duration: "17 min read"
---

Chapter 10 built two clients that reconnect on their own — exponential backoff, jitter, a fresh connector per attempt — and both of them already said, in their own Javadoc and docstring, exactly what that reconnect does not cover: a fresh connection resumes receiving new frames, it does not replay what the gap cost. That sentence was a forward reference. This chapter is where it gets proven live, against `examples/part4-backplane`, the example this part centers on. Part 3 and Chapter 10's clients could get away with disclosing the limitation in prose because their fixture-replay server sends the same three events on every connection, gap or no gap — there was never a real gap to lose anything in. `examples/part4-backplane` adds the piece that was missing: an inject endpoint that puts a new event onto the wire while a client is disconnected, and a backplane abstraction with three interchangeable modes, one of which — `stateless`, the default — keeps no record of that event anywhere. Connect, receive the seed, disconnect, have an event injected, reconnect with `?afterEventId=<last seen>` exactly the way Chapter 10's clients already know how to ask, and the event is gone. Not delayed, not buffered, not available on request — gone, because nothing in this mode ever wrote it down. `examples/part4-backplane/verify.sh`'s Stage A proves this live, on both stacks, every run: that's this chapter's `## On the wire` section. Chapter 16 is the other half of the same proof, same sequence, same `verify.sh`, different backplane mode — the one where the gap event comes back.

## Three modes, one default, one question each client already knows how to ask

`examples/part4-backplane/PROTOCOL.md`'s "Resume parameter" section lays out the full picture that this chapter and Chapter 16 split between them: a client reconnecting to this example's `/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events` channel MAY pass `?afterEventId=<eventId>` — the id of the last `HandlingEvent` it already received — and what the server does with that query parameter depends entirely on which of three `Backplane` implementations is active for the running instance. `BackplaneMode` names them `STATELESS`, `KAFKA`, and `REDIS`; `BackplaneRouter` reads `backplane.mode` (the `BACKPLANE_MODE` environment variable, default `stateless`) once per instance and dispatches every call — `onConnect`, `replayFor`, `publish` — to whichever one is active, so neither `HandlingEventBackplaneWebSocket` nor `HandlingEventInjectResource` has to know or care which mode is running underneath it.

`stateless` is the default profile and the one this chapter is about: no broker container, no shared state, `compose.yaml`'s base services with neither `--profile kafka` nor `--profile redis` applied. `kafka` is Chapter 16's mode — the same query parameter, answered from a durable, replayable topic. `redis` sits between the two and belongs to Chapter 18: it closes the cross-instance fan-out gap stateless mode has (an event injected through one instance never reaches a client connected to a different instance), but it still answers `afterEventId` the same way stateless mode does — ignored, no history — because Redis Pub/Sub has no retention to replay from. The table in `PROTOCOL.md` states this precisely: fan-out across instances is No for stateless, Yes for both brokers; `afterEventId` resume is "Ignored (no history)" for stateless AND for Redis, and only Kafka "Replays gap-era events after it." That asymmetry matters for this chapter specifically — the gap this chapter proves is not a quirk of having no broker at all, it is a property of having no *history*, and a mode can have a broker and still have that property.

Every mode answers the identical query parameter, because `HandlingEventBackplaneWebSocket.onOpen` and `ws_server.py`'s connection handler parse `afterEventId` off the URL before they know or care which mode is active — `QueryParams.get(connection.handshakeRequest().query(), "afterEventId")` on the Quarkus side, `_split_path_and_after_event_id`'s `parse_qs(split.query).get("afterEventId", [None])[0]` on the Python side. The parameter's presence on the wire is mode-independent; what varies is purely what the active `Backplane` implementation does when it is asked to resolve it.

## The stateless delivery path: seed, then whatever's live, `afterEventId` ignored

`StatelessBackplane` is the shortest of the three `Backplane` implementations in either stack, and its brevity is the point — there is no history-tracking code to write because there is no history. On the Quarkus side, `replayFor` takes `bookingId` and `afterEventId` and returns `List.of()` unconditionally, regardless of what `afterEventId` says. `publish` hands the injected event straight to `LocalDelivery.deliver`, which pushes it to every currently-open connection on *this JVM instance* watching that booking and then forgets it ever existed — no queue, no log, no append-only anything. The Python sibling is structurally identical: `subscribe` does `del after_event_id  # unused` as its first line inside the method body, then creates a fresh `asyncio.Queue` for this one connection and yields whatever shows up on it for as long as the connection stays open; `publish` does `queue.put_nowait(event)` for every currently-subscribed queue on that booking and, if there are none, logs `"no local subscribers ... dropped"` and returns. Both class docstrings say the same thing in almost the same words. The Java one: "there is no history to resume from — `replayFor` always returns empty." The Python one: "this mode keeps no history at all, so a gap-era injected event — one published while a given client was disconnected — is lost for that client, by design."

What a fresh connection receives is assembled from two sources that never touch each other. `Backplane`'s own Javadoc calls this out as a design note shared verbatim with the Python README: the 3-event fixture seed is sent directly by the WebSocket handler itself — `HandlingEventFeed` on the Quarkus side, `sequence()` on the Python side — unconditionally, in every mode, and it never flows through a `Backplane` at all. Only what comes *after* the seed is mode-dependent, and it comes from two different places depending on timing: whatever `replayFor`/the mode's own history returns (always empty for stateless), then whatever arrives live over `LocalDelivery.deliver` / the subscriber's `asyncio.Queue` for as long as the connection stays open. The seed guarantees every fresh connection — first attempt or fifth reconnect — starts from the same deterministic baseline; the mode-dependent half decides whether anything that happened while this specific client wasn't watching ever shows up.

{% include codetabs.html langs="Quarkus|Python" %}

```java
@Override
public List<HandlingEvent> replayFor(String bookingId, String afterEventId) {
    return List.of();
}

@Override
public void publish(String bookingId, HandlingEvent event) {
    localDelivery.deliver(bookingId, event);
}
```
```python
async def publish(self, booking_id: str, event: HandlingEvent) -> None:
    queues = self._subscribers.get(booking_id)
    if not queues:
        logger.info(
            "stateless backplane: no local subscribers for bookingId=%s eventId=%s — dropped",
            booking_id, event.eventId,
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
            yield await queue.get()
    finally:
        self._subscribers[booking_id].discard(queue)
```

Notice what's absent from both snippets: anything resembling a list, a log, a ring buffer, a database row keyed by `eventId`. `publish` in both languages is a direct hand-off to whatever is subscribed *right now* — a CDI-managed list of `WebSocketConnection`s on one side, a `set` of `asyncio.Queue`s on the other — and if nothing is subscribed, the event is dropped on the spot. There is nowhere for a disconnected client's missed event to wait, because waiting requires a place to wait in, and stateless mode was never given one.

{% include excalidraw.html file="15-gap-timeline" alt="A timeline inside a band labeled Stateless mode (default profile, no broker). CONNECT (3-event fixture seed delivered) has an arrow labeled 'socket drops' to DISCONNECT (client goes away; StatelessBackplane keeps nothing). DISCONNECT has a downward arrow labeled 'client not watching' to GAP (a dashed box: POST /internal/.../handling-events injected while disconnected), which has an amber downward arrow labeled 'never queued, never stored' to a grey LOST box (no subscriber queue to land in — delivered to nobody, kept nowhere). Separately, DISCONNECT's row continues right via an arrow labeled 'new WS upgrade' to RECONNECT (?afterEventId=<last seed id> query param accepted...), which connects to a box reading '...and IGNORED — replayFor()/subscribe() return no history for this id — ever', which has an amber downward arrow labeled 'the only thing resumed is the socket' to LIVE TAIL ONLY (new events from reconnect onward are delivered normally). Caption at the bottom: resuming the socket is not resuming the stream — the gap event is gone the moment it's injected; reconnect can't ask for what no server ever kept." caption="Figure 15.1 — the stateless gap: an event injected during the disconnect window is never queued and never stored, so reconnecting with afterEventId resumes the socket, not the missing event." %}

## Why `?afterEventId` can't help without a backplane

It's tempting to read `StatelessBackplane`'s `replayFor` and see a bug — why accept a query parameter and then ignore it instead of rejecting it outright? The answer is in `Backplane`'s interface contract and in what "resume" requires to work at all. Resuming from an id means the server has to be able to answer the question "what happened after this id, for this booking?" — which means somewhere, something kept a record of events in order, keyed well enough to find "after X" rather than merely "the current state." Stateless mode has no such record by construction: `LocalDelivery.deliver` iterates `OpenConnections.findByEndpointId(...)` and pushes to whichever ones are open and watching this `bookingId` *at the instant `publish` is called* — it is a fan-out operation over present-tense subscribers, not a write to a durable structure. The Python `StatelessBackplane`'s `_subscribers` dict is the same shape: a `defaultdict(set)` of live `asyncio.Queue`s, torn down (`del self._subscribers[booking_id]`) the moment the last subscriber disconnects. There is no data structure in either implementation that an `afterEventId` lookup could query, because none was ever built — adding one is precisely what Chapter 16's `KafkaBackplane` does instead.

Accepting the parameter and discarding it, rather than rejecting a request that includes it, is also the more consistent contract for a client that doesn't know or care which mode it's talking to. `HandlingEventBackplaneWebSocket.onOpen` and `ws_server.py`'s handler both parse `afterEventId` unconditionally before routing to the active mode — the same Chapter 10 client, with the same `?afterEventId=<last seen>` logic, can point at a stateless instance, a Kafka instance, or a Redis instance without any branch in its own code, and every mode accepts the connection and the parameter identically. What differs is purely whether the parameter does anything once it arrives. A client built against this contract has to assume the parameter is advisory, never a guarantee, unless it specifically knows which mode is running on the other end — and `PROTOCOL.md`'s table is where that knowledge has to come from, not the wire format itself.

This is also why fixing the gap can't be a client-side change. Chapter 10's clients already do everything a client can do: they reconnect promptly, with backoff and jitter, and they already send `afterEventId` on every attempt. None of that reaches the missing event, because the event was never retained anywhere a client's request could reach it. The fix has to live on the server, in the form of a place to keep events after they're published and a way to answer "after X" against that place — which is a backplane with retention, not a smarter client.

## When stateless is fine, and when it isn't

None of this makes stateless mode a mistake. `examples/part4-backplane`'s own README calls `stateless` "the 'before' picture" specifically because it's the right *starting point* for reasoning about this trade-off, not because it's wrong to ship. The deciding question is what a gap costs downstream, and that cost depends entirely on what the data represents, not on anything about WebSockets as a transport.

Stateless reconnect is the right tool when a missed event is recoverable by other means or doesn't matter once something newer has arrived. A live position indicator, a stock ticker, a dashboard gauge — these are all cases where an old value isn't a smaller version of the truth, it's actively wrong the moment a newer one exists, so losing whatever arrived during a disconnect costs nothing a client couldn't already discard on arrival. The other shape that's fine: a feed backed by a system of record a client can cheaply re-query on reconnect. If "what happened in the gap" is always answerable by one `GET` against the same backing store the feed is notifying about, then the WebSocket channel's job was only ever to say "something changed, go look" — the feed itself was never the record, so it never needed to replay one.

`examples/part4-backplane`'s own domain — a booking's `HandlingEvent` history — fails both of those tests, which is exactly why this part reaches for Kafka next rather than calling stateless mode good enough. Each `HandlingEvent` (`RECEIVE`, `LOAD`, `CUSTOMS`, `DELIVERED`, the shapes `contracts/asyncapi.yaml` defines) is a discrete fact about one piece of cargo moving through a specific stage, not a value that supersedes the one before it — a billing system reconciling customs charges or an auditor reconstructing a shipment's full handling history needs *every* event, not the latest one alone. And there's no cheap full-resync available: the feed in this example *is* the record a client sees events through; there's no separate `GET /bookings/{% raw %}{bookingId}{% endraw %}/handling-events` endpoint a reconnecting client could poll instead, by design — `contracts/asyncapi.yaml` only defines the one operation. When both conditions hold — every event is individually significant, and there's no side door to re-fetch what was missed — stateless mode's silent loss isn't a quirk a client can route around, it's a correctness gap. That's the gap Chapter 16 closes.

{% include excalidraw.html file="15-when-stateless-ok" alt="Two stacked bands. Top band, labeled Stateless reconnect is FINE when: three boxes — A full resync is cheap (GET the current state on reconnect; the feed is a notification, not the record of truth), Only the latest value matters (a position indicator, a live price — an old value is stale, not missing), and Gaps are self-correcting (the next push supersedes whatever the gap cost) — with a caption beneath reading 'default/stateless mode (this chapter) is the right tool'. Bottom band, labeled Stateless reconnect is NOT ENOUGH when: three boxes — Every event is a discrete fact (billing, customs, an audit trail — a missed HandlingEvent is a missed charge), No cheap full resync exists (the feed IS the record; no REST endpoint to re-GET the gap from), and At-least-once delivery is required (a consumer needs every eventId accounted for, not only the newest one) — with a caption beneath reading 'needs a durable, replayable log a client can resume from an offset — Chapter 16's Kafka-backed backplane'." caption="Figure 15.2 — the decision: stateless reconnect is fine when a fresh value supersedes a stale one or a full resync is cheap, and not enough when every event is individually significant and the feed is the only record of it." %}

## On the wire

`examples/part4-backplane/verify.sh`'s Stage A is this chapter's proof, run against the default profile — no `--profile kafka`, no `--profile redis`, `BACKPLANE_MODE=stateless` — on both stacks, every time `verify.sh` runs. `run_ch15_stateless_gap` connects, confirms all three seed frames land (asserting the third one's `eventId` matches the fixture's known `CUSTOMS` event), then disconnects, injects a fresh event through the same instance's `/internal/bookings/{% raw %}{bookingId}{% endraw %}/handling-events` endpoint, and reconnects with `?afterEventId=` set to the last seed event's id — exactly the resume call Chapter 10's clients already know how to make:

```bash
frames="$(ws_frames_n "ws://${ws_target}${path}" 3 20)"
last_frame="$(tail -n1 <<<"$frames")"
last_event_id="$(json_field '.eventId' <<<"$last_frame")"
assert_eq "$LAST_SEED_EVENT_ID" "$last_event_id" "$stack ch15: 3rd seed frame is the fixture's CUSTOMS event"

gap_event_id="$(gen_id evt_)"
inject_event "$http_target" "$booking_id" "$gap_event_id"

pid="$(ws_connect_bg "ws://${ws_target}${path}?afterEventId=${LAST_SEED_EVENT_ID}" "$log")"
wait_for_log_count "$log" '"eventType":"CUSTOMS"' 1 20
sleep 3

if grep -qF "\"eventId\":\"${gap_event_id}\"" "$log"; then
  echo "lib.sh: FAIL — $stack ch15: gap event $gap_event_id WAS delivered after reconnect (stateless must lose it)" >&2
  return 1
fi
echo "lib.sh: ok — $stack ch15: gap event $gap_event_id NOT delivered after reconnect (stateless loses gap-era events, as spec'd)" >&2
```

The three-second `sleep` before the negative assertion is deliberate, not padding — the comment above it in `verify.sh` spells out why it's trustworthy as a negative check rather than a race: "if stateless mode were (incorrectly) delivering the gap event, it would show up within this short wait — there is no live producer left to eventually deliver it later." A positive assertion ("the event arrived") only needs to wait long enough; a negative one ("the event never arrives") needs a reason to believe waiting longer wouldn't change the answer, and here that reason is structural — `StatelessBackplane.publish` only ever reaches *currently open* subscribers, so once the reconnect's seed-plus-nothing has already been delivered, nothing is still in flight that could surface the gap event a moment later.

Run it directly from the repo root:

```bash
cd examples/part4-backplane && ./verify.sh
```

`./verify.sh` runs Stage A first, against the default profile, before moving on to Stage B's Kafka replay proof (Chapter 16) and Stage C's Redis fan-out proof (Chapter 18) — Stage A alone is reproduced here because it's the only one this chapter's claim depends on:

```
=== Stage A: default profile (stateless) — Ch15 visible-gap proof ===
...
--- quarkus Ch15 stateless gap (bookingId=bkg_...) ---
lib.sh: ok — quarkus ch15: connected, received 3 seed frames, disconnected
lib.sh: inject eventId=evt_... bookingId=bkg_... via localhost:8080 -> HTTP 202
lib.sh: ok — quarkus ch15: gap event evt_... NOT delivered after reconnect (stateless loses gap-era events, as spec'd)

--- python Ch15 stateless gap (bookingId=bkg_...) ---
lib.sh: ok — python ch15: connected, received 3 seed frames, disconnected
lib.sh: inject eventId=evt_... bookingId=bkg_... via localhost:8082 -> HTTP 202
lib.sh: ok — python ch15: gap event evt_... NOT delivered after reconnect (stateless loses gap-era events, as spec'd)

=== Stage A complete: Ch15 stateless gap PROVEN LIVE on both stacks ===
```

The `202 Accepted` on the inject call is the detail worth not skating past: the HTTP request that puts the gap event onto the wire succeeds completely, every time — `HandlingEventInjectResource.inject` and `inject_handling_event` both return `202` unconditionally, because publishing to the active backplane is fire-and-forget from the injector's point of view. Nothing about the gap is visible as a failure at the moment it happens. The event is accepted, logged, and handed to `LocalDelivery.deliver` (or its Python equivalent), which finds no open connection watching that booking and does nothing further — a clean, quiet, individually correct operation at every step, that nonetheless adds up to the event never reaching the client it was meant for. That's the shape of this failure mode in production, too: nothing errors, nothing retries, nothing alerts — a reconnecting client has fewer events than it would have had if it had stayed connected, and nothing in stateless mode's own behavior surfaces that difference.

## Where this goes next

This chapter named and proved the gap stateless reconnect leaves: a fresh connection resumes the live stream, not the stream's history, because `StatelessBackplane`/`stateless_backplane.py` were built to hold none. `?afterEventId=` travels on the wire in every mode, but only a mode with somewhere to look up "after X" can answer it — stateless mode has nowhere, by design, which is why the parameter is accepted and ignored rather than rejected outright. Chapter 16 runs the identical sequence — connect, seed, disconnect, inject, reconnect with the same query parameter — against `--profile kafka` instead, where `KafkaBackplane.replayFor` has a durable topic to query and the same gap event that vanished in this chapter's proof comes back after reconnect, deduped by `eventId`. Figure 15.1's layout is Chapter 16's starting point: same five stages, same positions, with the grey LOST box at the end replaced by a delivered one. Chapter 18 takes the Kafka and Redis modes further still, proving an event injected through one server instance reaches a client connected to a completely different one — the cross-instance half of the backplane neither this chapter nor Chapter 16 needed, because both ran their proofs against a single instance.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>In stateless mode — the default profile of <code>examples/part4-backplane</code>, no broker required — a reconnecting client's <code>?afterEventId=</code> query parameter is accepted on the wire by both stacks but answered identically by every mode's shared code path and then discarded by this one: <code>StatelessBackplane.replayFor</code> always returns an empty list, and Python's <code>subscribe</code> discards the parameter in its first line, because neither implementation keeps a history to look it up against. <code>examples/part4-backplane/verify.sh</code>'s Stage A proves the consequence live, on both stacks: an event injected while a client is disconnected is accepted with <code>202</code>, delivered to zero open connections, and permanently unrecoverable — a reconnect with the correct <code>afterEventId</code> resumes the live tail only. That is the right trade-off when a stale value is harmless or a full resync is cheap elsewhere; it is the wrong one when every event is an individually significant fact and the feed is the only record of it, which is this example's own domain. Closing that gap requires a place to retain events and a way to answer "after X" against that place — a durable, replayable log, not a cleverer client — which is exactly what Chapter 16's Kafka-backed backplane mode adds to the identical wire contract.</p></div>
