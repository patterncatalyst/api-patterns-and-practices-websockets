---
title: "Backpressure and Flow Control"
order: 12
part: "Production Concerns"
description: "A bounded outbound path per connection, two signals that trip it, and a CLOSE or DROP policy for a server pushing to slow clients."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Bound the outbound path of every connection separately, so one slow client cannot grow the server's memory.
- Watch the two signals of a slow consumer: a full buffer and a single send that hangs past a timeout.
- Choose between `CLOSE` and `DROP` by whether a channel's events are discrete facts or superseded values, and set the choice in configuration.
- Avoid the `asyncio.Queue(maxsize=0)` trap, where zero means unbounded.
- State what TCP flow control covers and the gap that an application-level bound closes.

## Why this matters

A client bounds its inbound buffer so a server pushing `HandlingEvent`s cannot outrun the client's own processing. The server needs the mirror image: a bound on the path between the code that produces events and the `send()` that writes to one client's socket. The direction of the problem is the same, a producer outrunning a consumer, but the reason differs. A client has one producer, its one connection. A server with a thousand open connections has a thousand outbound paths, and one slow client must not become a problem for the other 999.

## Same problem, the other end of the wire

The `handlingEvents` channel is push-only. The server gets no in-band signal about how fast a client consumes, and nothing like a request to wait for before producing the next message. If it hands each event to the socket layer the instant the previous one is accepted, nothing stops it from producing faster than a slow client's TCP stack or application can drain.

WebSockets Next exposes no outbound queue to bound. Items returned from a `Multi` are written as they are emitted, and the one documented knob, `quarkus.websockets-next.server.max-pending-messages`, bounds inbound messages only. `OutboundBackpressureGuard` therefore tracks the connection's outstanding, unacknowledged `sendText` calls itself. The Python side bounds an actual `asyncio.Queue` in `OutboundQueue`. The two primitives answer the same question: is this connection's outbound path falling behind, and what happens next?

Both are scoped per connection. `sendAll` creates a fresh `AtomicInteger pending` and `AtomicBoolean closeRequested` on every call, and the Python handler constructs its `OutboundQueue` inside the per-connection coroutine. One connection's counter climbing has no effect on any other connection.

## Why the outbound path has to be bounded

The bound (`maxPendingSends` and `QUEUE_MAXSIZE`, both defaulting to 32) is more than a tuning knob. Without it there is no backpressure at all, and the failure is unbounded memory growth on the server. An unbounded `enqueue()` keeps appending while a producer outpaces a stalled client. One slow client costs one growing list; a hundred (a congested mobile link, a laptop put to sleep mid-session, a client that never reads) cost a hundred, and the server cannot know in advance which connections will behave that way. Reaching this takes nothing more than a client that reads slowly.

The two buffers solve similar problems for different reasons:

| | Client inbound buffer | Server outbound buffer |
|---|---|---|
| Decouples | Socket reads from frame processing in one process | Event production from one client's socket write |
| Producers | One (the server) | One per connection, thousands at once |
| Protects | The client's processing from stalls | The server's finite memory from a per-connection multiplier |

## The bounded outbound buffer and its two triggers

A server pushing events cannot tell a fast client from a stalled one until its sends back up. By then the events are queued in server memory, one list per slow client. The fix is to bound each connection's outbound path, watch for a full buffer or a send that hangs past a timeout, and apply a configured policy, `CLOSE` or `DROP`, when either trips.

Two independent signals count as "the consumer fell behind". The buffer fills, a sustained rate mismatch. Or one `send()` hangs past a timeout, meaning the client's TCP receive window is full because it stopped reading, so even one frame at a time cannot get out. The first shows the problem gradually; the second shows it all at once.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    private Uni<Void> sendOne(WebSocketConnection connection, HandlingEvent event, String bookingId,
            AtomicInteger pending, AtomicBoolean closeRequested) {
        if (closeRequested.get()) {
            // Another item already tripped the CLOSE policy; nothing left to do.
            return Uni.createFrom().voidItem();
        }
        if (pending.get() >= maxPendingSends) {
            return applyPolicy(connection, bookingId, closeRequested,
                    "outbound buffer exceeded (pending=" + pending.get() + " >= max=" + maxPendingSends + ")");
        }

        pending.incrementAndGet();
        return connection.sendText(event)
                .ifNoItem().after(sendTimeout).failWith(
                        () -> new TimeoutException("sendText exceeded " + sendTimeout
                                + ", peer is not draining its receive buffer"))
                .onItemOrFailure().transformToUni((v, failure) -> {
                    pending.decrementAndGet();
                    if (failure == null) {
                        return Uni.createFrom().<Void>voidItem();
                    }
                    if (failure instanceof TimeoutException) {
                        return applyPolicy(connection, bookingId, closeRequested, failure.getMessage());
                    }
                    Log.errorf(failure, "failed to send event %s to bookingId=%s", event.eventId(), bookingId);
                    return Uni.createFrom().voidItem();
                });
    }
```

```python
    def enqueue(self, frame: str) -> None:
        """Enqueue one outbound frame (a JSON string). On a full queue,
        applies the configured policy immediately rather than blocking the
        producer; see the module docstring.
        """
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            self._on_backpressure(f"outbound queue full (maxsize={self._queue.maxsize})")

    async def drain(self, websocket) -> None:
        """Pop frames and send them, one at a time, in enqueue order. A
        single send that doesn't complete within `SEND_TIMEOUT_S` is treated
        as the same "slow consumer" condition as a full queue.
        """
        while True:
            frame = await self._queue.get()
            try:
                await asyncio.wait_for(websocket.send(frame), timeout=SEND_TIMEOUT_S)
            except asyncio.TimeoutError:
                self._on_backpressure(
                    f"send() exceeded {SEND_TIMEOUT_S}s, peer is not draining its receive buffer"
                )
```

Python has a literal bounded queue between producer and consumer. `enqueue()` is a synchronous `put_nowait`, so the producer never waits on the network: a frame either lands in the queue or trips `QueueFull` at once. `drain()` is the long-running coroutine that pops frames one at a time and awaits each `send()` under a timeout. `except asyncio.QueueFull` catches the first signal and `except asyncio.TimeoutError` around `wait_for` catches the second.

Quarkus has no `java.util.Queue` to bound, because `Multi.createFrom().iterable(events).onItem().transformToUniAndMerge(...)` is already the producer/consumer machinery. It counts outstanding work instead: `pending.get() >= maxPendingSends` is the buffer-full check, and `.ifNoItem().after(sendTimeout).failWith(...)` on every `sendText` is the counterpart of Python's `wait_for`. A counter stands in for the queue's depth; the question answered is the same.

{% include excalidraw.html file="12-slow-consumer-timeline" alt="A timeline from connection open to a tripped policy: the client slows, its TCP receive window fills, the send stays pending, then the buffer fills or the send times out. CLOSE ends with code 4290 and the remaining events dropped; DROP discards one event and keeps accepting new ones." caption="Figure 12.1: A producer outruns a consumer. The client's TCP window fills first, then the server's sends back up behind it, until a signal trips the configured policy." %}

## CLOSE or DROP

Both stacks make the policy configuration, not code: `example.backpressure.policy` in Quarkus (default `CLOSE`) and `OUTBOUND_BACKPRESSURE_POLICY` in Python (default `close`).

| Policy | What happens | Use it when |
|---|---|---|
| `CLOSE` (default) | Close with `4290` (`SLOW_CONSUMER`) and stop sending the rest of that connection's events | Every event is a fact the client must not miss |
| `DROP` | Skip the event that tripped the threshold, log a warning, keep the connection open | A later update supersedes the dropped one: a ticker, a position, a latest-reading telemetry feed |

`CLOSE` is the safer default for any server: an unbounded number of slow clients, each holding an unbounded number of outstanding sends, is a resource-exhaustion path, and a clean failure for one connection beats an open-ended growth problem for the process hosting all of them. `DROP` is wrong for this channel. A `HandlingEvent` is a discrete fact about cargo (received, loaded, cleared through customs), and a client missing one with no record of the gap has a correctness problem.

{% include excalidraw.html file="12-outbound-buffer-policy" alt="A producer enqueues into a bounded outbound buffer of 32 that feeds the slow client's socket write. When the buffer is full or a send exceeds its timeout, CLOSE tears the connection down with 4290 and DROP skips the event and keeps the connection open." caption="Figure 12.2: The bounded buffer between producer and socket write, and the two policies applied when either trigger fires." %}

One Quarkus detail explains why `sendAll` returns a `Uni<Void>` and `onOpen` returns it directly instead of subscribing. `WebSocketConnection` is a `@SessionScoped` CDI bean, and that scope is active only while Quarkus drives the `Uni` or `Multi` a callback returns. A `Uni` the code subscribes to by hand completes later on a raw Vert.x thread after the scope is gone, and fails with `ContextNotActiveException`. Composing every `sendText` and `close` into one returned `Uni` keeps each backpressure check inside the single subscription Quarkus manages.

## What `maxsize=0` means

`OUTBOUND_QUEUE_MAXSIZE=0` is not a zero-capacity queue. `asyncio.Queue` treats `maxsize <= 0` as unbounded, the opposite of what zero means in most size-like parameters. Setting it to get the smallest queue gives you the one configuration where backpressure never trips, which reintroduces the failure the bound exists to prevent. Treat a zero in any size setting as something to verify.

It also forces different test values for the two stacks. Quarkus compares `pending.get() >= maxPendingSends`, so `EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0` trips on the first send before anything has been sent. Python needs `OUTBOUND_QUEUE_MAXSIZE=1`: the handler enqueues all three fixture events before the `drain` task is first scheduled, so the second `enqueue()` always meets a full queue, whatever the event loop does next.

## TCP flow control is not enough

TCP has its own backpressure. A receiver advertises a window of unacknowledged data it will buffer, and the sender's kernel stops writing once it fills. That is what the hanging-`send()` signal observes from above: the client stopped reading, its window filled, the kernel's write blocks, and the block surfaces several layers up as a timeout.

TCP does not protect the server process. The window throttles bytes on one socket and says nothing about what the producer should do meanwhile. Without a bound above it, a blocked write does not stop the producer; the producer's output piles up in application memory while the write waits. TCP protects the network and the two kernels. The application-level bound and policy turn "the kernel's write is blocked" into a decision: wait a bounded time, then close or drop.

> **Decision**
>
> Bound every connection's outbound path, never share one budget across connections, and watch both a full buffer and a send that hangs past a timeout. Default to `CLOSE` with `4290`, and use `DROP` only for feeds where the next update supersedes the dropped one. Verify a zero in any size setting: `asyncio.Queue(maxsize=0)` is unbounded.

> **🤖 Explore with your agent**
>
> "In `examples/part4-connection`, add a one-off run of the Python server with `OUTBOUND_QUEUE_MAXSIZE=1` and `OUTBOUND_BACKPRESSURE_POLICY=drop`, connect to `/ws/v1/bookings/{bookingId}/handling-events` with a valid token, and report which frames arrive and what the server logs. Then switch the policy to `close` and report the close code. State which policy suits `HandlingEvent` and why."
>
> Check: with `close` the connection ends with code `4290` and zero frames delivered; with `drop` the server logs a slow-consumer warning (`dropping frame`) instead of closing.

## Build, run, observe

```bash
cd examples/part4-connection
./verify.sh
```

`verify.sh` starts the Quarkus and Python stacks, then runs one-off containers on alternate host ports (`18080` for Quarkus, `18091` for Python) so the primary stack keeps running. It forces each threshold low (`EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0`, `OUTBOUND_QUEUE_MAXSIZE=1`), connects with a valid token and reads until the server closes. Both stacks close with `4290` and deliver zero frames, because the policy trips before the first event reaches the socket. A passing run prints `PASS: ` at the end.

| Env var | Stack | Default | Purpose |
|---|---|---|---|
| `EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS` | Quarkus | `32` | Outbound in-flight send cap |
| `EXAMPLE_BACKPRESSURE_POLICY` | Quarkus | `CLOSE` | `CLOSE` or `DROP` |
| `OUTBOUND_QUEUE_MAXSIZE` | Python | `32` | Outbound queue depth (`<=0` is unbounded, not zero-capacity) |
| `OUTBOUND_BACKPRESSURE_POLICY` | Python | `close` | `close` or `drop` |

- Set `EXAMPLE_BACKPRESSURE_POLICY=DROP` (Quarkus) or `OUTBOUND_BACKPRESSURE_POLICY=drop` (Python) with the same forced-low threshold: the log shows a slow-consumer warning (`Log.warnf` or `logger.warning`) instead of a `4290` close.
- Set `OUTBOUND_QUEUE_MAXSIZE=0` on the Python server: it never overflows, so no `4290` arrives.

## For deeper coverage

- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026): backpressure and flow control between a producer and a consumer running at different rates.
- Michael T. Nygard, *Release It!, Second Edition* (Pragmatic Bookshelf, 2018): bulkheads, and the resource-exhaustion failure an unbounded per-connection buffer invites.
- *Cloud Native Design Patterns*, "Stream Processing" chapter: bounded buffers and explicit backpressure policies as a named pattern.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455): the private-use close-code range (`4000` to `4999`) that `4290` sits in, and the frame mechanics that `send()` writes onto.
- [Python `websockets` flow control](https://websockets.readthedocs.io/en/stable/topics/design.html#backpressure): how the library handles backpressure internally, underneath `OutboundQueue`.
- [Reactive Streams](https://www.reactive-streams.org/): the non-blocking backpressure vocabulary of bounded demand and explicit signaling.
