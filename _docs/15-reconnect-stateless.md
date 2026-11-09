---
title: "Reconnect: Stateless"
order: 15
part: "Production Concerns"
description: "What a client loses when it reconnects to a server that keeps no event history, and when that loss is acceptable."
duration: "11 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why `?afterEventId=` is accepted on the wire but discarded when the server keeps no history.
- Separate the fixture seed from the live stream, and see why that split makes the stateless gap structural.
- Decide when stateless reconnect is enough and when it loses data no later request can recover.
- Reproduce the gap: disconnect, inject an event, reconnect, and watch it fail to arrive.
- Say why no client-side change, however aggressive the backoff, can close the gap.

## Why this matters

A reconnecting client uses exponential backoff, jitter and a fresh connector per attempt, and none of that replays what happened while it was gone. A fresh connection resumes new frames. It does not recover the cost of the gap.

`examples/part4-backplane` makes that visible. It adds an inject endpoint that puts a new event on the wire while a client is disconnected, and a `Backplane` abstraction with three interchangeable modes. The default, `stateless`, keeps no record of the event anywhere. Connect, receive the seed, disconnect, inject an event, reconnect with `?afterEventId=<last seen>`, and the event is gone. It isn't delayed or buffered: nothing ever wrote it down.

{% include excalidraw.html file="15-gap-timeline" alt="A timeline in stateless mode. A client connects and receives the seed, the socket drops, an event is injected while it is disconnected and is never queued or stored, and the client reconnects with afterEventId, which is accepted and ignored, so only the live tail resumes." caption="Figure 15.1: An event injected during the disconnect is never queued or stored, so reconnecting with afterEventId resumes the socket and not the missing event." %}

## `afterEventId` with no history behind it

A client that drops and reconnects wants the events it missed. The wire contract lets it say where it stopped: `?afterEventId=<eventId>` on the `/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events` channel, naming the last `HandlingEvent` it received. Whether the server can answer depends on which of three `Backplane` implementations is active:

| Mode | Fan-out across instances | `afterEventId` |
|---|---|---|
| `stateless` (default) | No | Ignored, no history |
| `redis` | Yes | Ignored, no history (Pub/Sub has no retention) |
| `kafka` | Yes | Replays gap-era events after it |

`BackplaneRouter` reads `backplane.mode` (`BACKPLANE_MODE`, default `stateless`) once per instance and dispatches `onConnect`, `replayFor` and `publish` to the active mode, so the endpoint and the inject resource don't know which one runs. The gap is a property of having no history, not of having no broker: Redis has a broker and still loses it.

Resuming from a sequence number requires the server to keep an ordered record it can search for "everything after this id." Stateless mode has no such record, so it accepts the parameter and drops it.

`StatelessBackplane` is the shortest backplane in either stack, because there is no history to write. Both stacks parse `afterEventId` off the URL before they know which mode is active, so one reconnect path works against any mode.

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
                "stateless backplane: no local subscribers for bookingId=%s eventId=%s: dropped",
                booking_id,
                event.eventId,
            )
            return
        for queue in list(queues):
            queue.put_nowait(event)

    async def subscribe(self, booking_id: str, after_event_id: str | None) -> AsyncIterator[HandlingEvent]:
        del after_event_id  # unused: no history to replay
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
```

`publish` hands the event to whatever is subscribed right now: open connections on this JVM watching that booking in `LocalDelivery.deliver`, a set of `asyncio.Queue`s in Python. With no subscriber, the Python side logs that it dropped the event. There is no list, log, ring buffer or row keyed by `eventId`, so there is nowhere for a disconnected client's event to wait. `LocalDelivery.deliver` iterates `OpenConnections.findByEndpointId(...)` at the instant `publish` runs, and Python tears down a booking's subscriber set when its last connection leaves: both are fan-out over present-tense subscribers, not writes to a durable structure.

What a fresh connection receives comes from two sources that never touch. The three-event fixture seed is sent by the WebSocket handler itself (`HandlingEventFeed` on Quarkus, `sequence()` in Python) in every mode and never flows through a backplane, so every connection starts from the same baseline. Everything after the seed is mode-dependent: whatever `replayFor` returns (empty for stateless), then whatever arrives live.

### Why accept the parameter and discard it

Rejecting it would force the client to know the mode. Accepting it keeps one reconnect path: the same client, sending `?afterEventId=<last seen>` every time, can point at a stateless, Redis or Kafka instance with no branch of its own. The cost is that the parameter is advisory. A client can't rely on it unless it knows the mode on the other end, and that knowledge comes from the protocol notes, not the wire format.

It also means the fix can't live in the client. Reconnecting promptly, with backoff and jitter, and sending `afterEventId` on every attempt is everything a client can do. The event was never retained anywhere a request could reach. The fix is a server-side place to keep events and a way to answer "after X" against it: a backplane with retention.

## When stateless is enough

Stateless is the right start for reasoning about the trade-off, and a reasonable place to stay when the cost of a gap is low.

| Stateless is enough when | It is not enough when |
|---|---|
| Only the latest value matters (a live position, a price, a gauge) | Every event is a discrete fact (customs charges, an audit trail) |
| A cheap full resync exists: one `GET` against the system of record | The feed is the record, with no endpoint to re-fetch the gap |
| The next push supersedes whatever the gap cost | A consumer must account for every `eventId` |

A booking's `HandlingEvent` history (`RECEIVE`, `LOAD`, `CUSTOMS`, `DELIVERED`) fails the second column. Each event is a fact about cargo at a stage and doesn't supersede the one before it, and the contract defines one operation on the channel, so a reconnecting client has no REST endpoint to poll for the gap.

{% include excalidraw.html file="15-when-stateless-ok" alt="Two bands. Stateless reconnect is fine when a full resync is cheap, only the latest value matters, or gaps are self-correcting. It is not enough when every event is a discrete fact, no cheap resync exists, or at-least-once delivery is required, which needs a durable, replayable log." caption="Figure 15.2: Stateless reconnect fits when a fresh value supersedes a stale one or a full resync is cheap, and falls short when every event matters and the feed is the only record." %}

The failure is quiet. The inject call returns `202 Accepted` every time, because publishing is fire-and-forget from the injector's side. The event is handed to a delivery path that finds no open connection and does nothing. Nothing errors, retries or alerts. A reconnecting client simply has fewer events than if it had stayed connected.

> **Decision**
>
> Use stateless reconnect when a stale value is harmless or a full resync is one cheap request. When every event is a fact and the feed is the only record, add a backplane with retention (Kafka) and treat `afterEventId` as a real resume point. A cleverer reconnect loop never recovers what the server didn't keep.

> **🤖 Explore with your agent**
>
> "In examples/part4-backplane, with BACKPLANE_MODE=stateless, connect to /ws/v1/bookings/{bookingId}/handling-events, read the three seed frames, disconnect, POST an event to /internal/bookings/{bookingId}/handling-events, then reconnect with ?afterEventId set to the last seed eventId. Report whether the injected event arrives, which class discards afterEventId on each stack, and which of our booking events would make this gap a correctness bug."
>
> Check: the inject call returns 202, the reconnect shows only the three seed frames, and the agent points to StatelessBackplane.replayFor on Quarkus and the `del after_event_id` line in Python.

## Build, run, observe

```bash
cd examples/part4-backplane && ./verify.sh
```

Stage A runs on the default profile (no `--profile kafka`, no `--profile redis`) against both stacks. It connects and confirms the three seed frames, with the third being the fixture's `CUSTOMS` event, then disconnects, injects a fresh event through `/internal/bookings/{% raw %}{bookingId}{% endraw %}/handling-events`, and reconnects with `?afterEventId=` set to that last seed id. It passes when the gap event does not appear. The script waits three seconds before declaring absence; that is enough because no producer is left that could deliver the event later.

```
--- quarkus Ch15 stateless gap (bookingId=bkg_...) ---
lib.sh: ok, quarkus ch15: connected, received 3 seed frames, disconnected
lib.sh: inject eventId=evt_... bookingId=bkg_... via localhost:8080 -> HTTP 202
lib.sh: ok, quarkus ch15: gap event evt_... NOT delivered after reconnect (stateless loses gap-era events, as spec'd)

--- python Ch15 stateless gap (bookingId=bkg_...) ---
lib.sh: ok, python ch15: connected, received 3 seed frames, disconnected
lib.sh: inject eventId=evt_... bookingId=bkg_... via localhost:8082 -> HTTP 202
lib.sh: ok, python ch15: gap event evt_... NOT delivered after reconnect (stateless loses gap-era events, as spec'd)
```

Experiments:

- Let the script continue: Stage B repeats the same sequence under `--profile kafka`, and the gap event arrives after reconnect.
- Change the reconnect URL in the script to drop `?afterEventId=`; the stateless result is unchanged, because the parameter was never consulted.

## For deeper coverage

- Unmesh Joshi, *Patterns of Distributed Systems* (Addison-Wesley, 2023): the replicated-log reasoning behind resuming a stream and not only a connection.
- Sam Newman, *Building Resilient Distributed Systems* (O'Reilly, 2026): the stateless-versus-durable trade-off in context.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: where a silent, unrecoverable gap sits in the taxonomy.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455) section 7: the close-code framework reconnect logic builds on.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the contract language behind the `handlingEvents` operation and its `afterEventId` query parameter.
