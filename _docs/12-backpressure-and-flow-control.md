---
title: "Backpressure and Flow Control"
order: 12
part: "Production Concerns"
description: "What happens when a producer outruns a consumer, and the flow-control options available on a socket."
duration: "15 min read"
---

Chapter 10 built a bounded buffer between a client's socket read loop and whatever code processes each frame, because a server can push `HandlingEvent`s faster than a client's consumer can keep up, and something has to decide what happens to the frames that arrive while the consumer is still busy with the last one. That chapter's buffer protected the client. This chapter is the mirror image: `examples/part4-connection/quarkus/.../connection/OutboundBackpressureGuard.java` and `examples/part4-connection/python/app/outbound.py` protect the **server**, bounding the path between the code that produces `HandlingEvent`s — the fixture replay in this example, a live event source in a real backend — and the `sendText()`/`send()` call that writes bytes onto a specific client's socket. The direction of the problem is the same (a producer outruns a consumer), but the party doing the bounding and the reason it has to changes, and that change is worth taking seriously rather than treating this chapter as "Chapter 10 again, with the names swapped." A client only has one producer to worry about — the server on the other end of its one connection. A server handling `handlingEvents` connections for every booking in the system has as many independent outbound paths as it has open connections, and a single slow client on any one of them cannot be allowed to become a problem for the other nine hundred.

## Same problem, the other end of the wire

The `handlingEvents` channel (`contracts/asyncapi.yaml`, `operations.receiveHandlingEvent`) is server-push-only: a client opens the connection and receives whatever the server has to send, and the server has no in-band signal from the client about how fast it is consuming those frames. That absence is the whole reason this chapter exists. If the channel were request/response, the server would wait for the next request before producing the next response, and the client's own pace would throttle the server for free. A push channel has no such request to wait for — the server decides when to send, and if it decides to send the next `HandlingEvent` the instant the previous one is handed to the socket layer, nothing stops it from producing far faster than a slow client's TCP stack, OS, or application code can drain.

`OutboundBackpressureGuard`'s Javadoc states the structural reason this exists as its own class rather than inline code in the endpoint directly: WebSockets Next doesn't expose an outbound queue for an `@OnOpen`/`@OnTextMessage` handler to bound itself. Items returned from a `Multi` are written to the connection as they're emitted, and the one documented backpressure knob the framework ships — `quarkus.websockets-next.server.max-pending-messages` — bounds **inbound** messages, not outbound ones. So this example's Quarkus side tracks its own outstanding, not-yet-acknowledged `sendText` calls for a single connection, checking the same two signals its Python sibling checks against an actual `asyncio.Queue`. Two different primitives, same question asked of each: is this specific connection's outbound path falling behind, and if so, what happens next?

`HandlingEventConnectionWebSocket.onOpen` delegates to the guard directly rather than looping over `feed.events()` itself:

```java
@OnOpen
public Uni<Void> onOpen(@PathParam String bookingId) {
    String token = QueryParams.get(connection.handshakeRequest().query(), "token");
    JwtHs256.VerificationResult auth = JwtHs256.verify(token, jwtSecret);
    if (!auth.valid()) {
        Log.warnf("handling-events connection REJECTED bookingId=%s reason=%s", bookingId, auth.reason());
        return connection.close(new CloseReason(CloseCodes.AUTH_FAILURE, "authentication failed"));
    }
    connection.userData().put(LAST_PONG_AT, System.currentTimeMillis());
    Log.infof("handling-events connection opened bookingId=%s subject=%s; replaying %d fixture event(s)",
            bookingId, auth.subject(), feed.events().size());
    return backpressureGuard.sendAll(connection, feed.events(), bookingId);
}
```

Every connection gets its own `pending` counter and its own `closeRequested` flag — `sendAll` creates `AtomicInteger pending` and `AtomicBoolean closeRequested` fresh on every call, scoped to that one `Multi` chain. One slow connection's counter climbing toward its threshold has no way to affect any other connection's counter; the bound this chapter builds is per-connection, not a single global budget shared across every client the server happens to be serving at once. The Python sibling gets the same isolation for a different reason: `_run_connection` constructs `outbound = OutboundQueue()` inside the per-connection `handler` coroutine, so each WebSocket gets its own queue instance with its own `asyncio.Queue(maxsize=...)` underneath it, not a shared queue multiple connections write into.

## The bounded outbound buffer and its two triggers

Both implementations watch for the same two independent conditions, and the Python module's docstring states them as plainly as anything in this codebase: the queue fills up — the producer is enqueueing faster than `drain()` can send, a sustained rate mismatch — or a single `send()` call itself hangs past a timeout, meaning the client's TCP receive window is full because it stopped reading, so even one frame at a time can't get out. Either condition is "the consumer fell behind"; the difference is whether it fell behind gradually (the buffer is the evidence) or stopped entirely (one send never completes at all).

The Python side is the more literal version to reach for first, because it has an actual bounded queue sitting between producer and consumer:

{% include codetabs.html langs="Quarkus|Python" %}

```java
private Uni<Void> sendOne(WebSocketConnection connection, HandlingEvent event, String bookingId,
        AtomicInteger pending, AtomicBoolean closeRequested) {
    if (closeRequested.get()) {
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
                            + " — peer is not draining its receive buffer"))
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
    producer — see module docstring.
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
                f"send() exceeded {SEND_TIMEOUT_S}s — peer is not draining its receive buffer"
            )
```

Python's version reads closer to the textbook shape: `enqueue()` is a synchronous, non-blocking `put_nowait` call the producer loop runs for every frame, so `_run_connection`'s producer (the fixture-to-JSON loop) never waits on the network directly — it either lands in the queue or trips `QueueFull` immediately. `drain()` is the long-running coroutine on the other side, popping frames one at a time and awaiting each `send()` with a timeout wrapped around it. Two lines, two signals: `except asyncio.QueueFull` catches the first (buffer is full), `except asyncio.TimeoutError` around the `wait_for` catches the second (one send hung).

The Quarkus version gets to the same two signals without an explicit queue object to point at, because `Multi.createFrom().iterable(events).onItem().transformToUniAndMerge(...)` is already Quarkus's own producer/consumer machinery — there's no raw `java.util.Queue` for `OutboundBackpressureGuard` to bound directly. So it tracks outstanding work itself: `pending.get() >= maxPendingSends` is the buffer-full check (too many `sendText` calls are outstanding at once, meaning the producer is pushing faster than the socket drains), and `.ifNoItem().after(sendTimeout).failWith(...)` wraps every individual `sendText` call with the same kind of per-send timeout Python's `asyncio.wait_for` provides. Different mechanics — a counted semaphore standing in for a bounded queue's depth — but it answers the identical question Python's queue answers: is this connection accumulating more outstanding sends than it should, or has a single send stopped moving entirely.

{% include excalidraw.html file="12-slow-consumer-timeline" alt="A timeline with five stages flowing left to right. t0: connection opens, buffer empty, client draining. t1: client slows down, TCP receive window fills. t2: sendText/send() stays pending — the socket write itself blocks. t3: buffer fills OR send() exceeds timeout — policy trips. From t3, an amber arrow labeled 'policy = CLOSE' goes down to a box: t4 (CLOSE): 4290 SLOW_CONSUMER — remaining events dropped. A dashed arrow labeled 'policy = DROP' goes down to a second box: t4 (DROP): this event discarded, buffer keeps accepting new ones. A caption at the bottom reads: without a bound, this same timeline keeps t1-t3 going forever — the buffer grows without limit and the server's own memory is what eventually fails, not the client." caption="Figure 12.1 — a producer outrunning a consumer: the client's TCP window fills first, then the server's own send calls back up behind it, until one of the two signals trips the configured policy." %}

## CLOSE vs DROP: picking a policy for this channel

Both implementations expose the same choice as configuration rather than a hardcoded behavior: `example.backpressure.policy` (Quarkus, `ConfigProperty` defaulting to `CLOSE`) and `OUTBOUND_BACKPRESSURE_POLICY` (Python, environment variable defaulting to `close`). `applyPolicy` in Quarkus and `_on_backpressure` in Python are the two methods that branch on it, and both read as a short, direct `if`:

`CLOSE` closes the connection with `CloseCodes.SLOW_CONSUMER` (`4290`) and stops sending whatever remains in that connection's event list. `OutboundBackpressureGuard`'s Javadoc calls this the safer default, and the reasoning generalizes past this one example: an unbounded number of slow clients, each holding an unbounded number of outstanding sends, is a resource-exhaustion path for the server itself, a bigger risk than a bad experience for that one slow client. Closing trades a guaranteed, clean failure for one connection against an open-ended growth problem for the process hosting every connection.

`DROP` skips the event that tripped the threshold, logs a warning, and lets the connection continue — the queue (or counter) keeps accepting new work instead of tearing the socket down. Both Javadocs state clearly that `DROP` is not the right fit for this particular channel's semantics: a `HandlingEvent` is a discrete fact about cargo movement — a container was received, loaded, cleared through customs — and a client that never receives one of those without any record of the gap has a correctness problem, not a "the next update supersedes this one anyway" situation the way a live ticker price or a position indicator would. `DROP` exists in both implementations to demonstrate the trade-off and give an operator or downstream integrator a lever to pull if their own channel's semantics genuinely tolerate it — a telemetry feed where only the latest reading matters, say — not because this example's `handlingEvents` channel is a good match for it.

{% include excalidraw.html file="12-outbound-buffer-policy" alt="A flow diagram. Producer (fixture replay / a new HandlingEvent is recorded) has an arrow labeled 'enqueue / pending++' going to BOUNDED OUTBOUND BUFFER (maxPendingSends / QUEUE_MAXSIZE, default 32), which has an arrow labeled 'sendText / send()' going to connection.sendText() / websocket.send() — the slow client's socket. Below the buffer, two dashed arrows labeled 'full, or send() > timeout' branch down-left to CLOSE (default) — close(4290 SLOW_CONSUMER), stop sending, safe default, and down-right to DROP — log + skip this event, keep the connection open. CLOSE has an amber dashed arrow back up labeled 'connection torn down — no more frames' pointing at the buffer. DROP has an amber arrow back up labeled 'next event still enqueued' pointing at the socket write box. A caption at the bottom reads: two signals trip the policy — the buffer is full (sustained rate mismatch), or one send() hangs past the timeout (peer stopped reading entirely)." caption="Figure 12.2 — the bounded outbound buffer sitting between the producer and the socket write, and the two policies for what happens once one of the two trigger conditions fires." %}

One structural detail in the Quarkus side is easy to miss and worth naming directly, because it explains a line of code that would otherwise look like an unusual way to write a method that sends some messages: `sendAll` returns a `Uni<Void>` rather than subscribing to anything itself, and `onOpen` returns that `Uni` directly instead of calling `.subscribe()` on it. `WebSocketConnection` is a `@SessionScoped` CDI bean, and that scope is only guaranteed active while Quarkus itself is driving the `Uni`/`Multi` an `@On*` callback returns — not inside a `Uni` the callback's own code subscribes to manually, whose completion handler runs later on a raw Vert.x thread after the scope has already torn down, which fails with `ContextNotActiveException`. Composing every `sendText` and `close` call into one `Uni` and letting `onOpen` return it is what keeps the whole send sequence, including every backpressure check along the way, inside the single subscription Quarkus itself manages.

## Why the outbound path has to be bounded at all

It's tempting to treat the bound (`maxPendingSends`/`QUEUE_MAXSIZE`, both defaulting to 32) as an arbitrary tuning knob and move on, but the number is standing in for a much blunter fact: without a bound, there is no backpressure mechanism at all, and the failure mode is not "the connection gets slow" — it's unbounded memory growth on the server. Picture the unbounded version of either implementation: `enqueue()` without a `maxsize` keeps appending to a list forever, and a producer that outpaces a stalled client fills that list at whatever rate new `HandlingEvent`s arrive, with nothing to stop it. One slow client costs the server one growing list. A hundred slow clients — a client behind a congested mobile connection, a client on a laptop that's been put to sleep mid-session and resumed an hour later, a client that opened a connection and never reads from the socket at all — cost the server a hundred growing lists, and the server has no way to know in advance which of its open connections will behave that way. That is a resource-exhaustion path reachable by nothing more exotic than a client that reads slowly, which makes it a real operational risk for any server that pushes data over a long-lived connection, not a contrived edge case invented for this chapter.

This is also the place where the asymmetry with Chapter 10's client-side buffer is worth stating precisely, because the two chapters solve structurally similar problems for different reasons. Chapter 10's client bounds its buffer so the code reading frames off the socket never blocks on the code that processes them — the buffer's job is to decouple two pieces of work running inside the same client process, and a client has exactly one upstream producer (one server connection) to worry about. This chapter's server bounds its buffer so that one misbehaving client cannot make the server itself unbounded — the buffer's job is to protect the server's own finite memory against a multiplier effect that doesn't exist on the client side, because a server potentially has thousands of these buffers open at once, one per connection, and every single one of them is a liability if it's allowed to grow without limit.

## The `maxsize=0` gotcha

`verify.sh`'s Step 5 comment documents something about `asyncio.Queue` that is easy to get backwards, and getting it backwards produces exactly the kind of bug that looks correct in a quick manual test and then fails the first time anyone runs it under load: `OUTBOUND_QUEUE_MAXSIZE=0` does not mean a zero-capacity queue. It means an **unbounded** one. That's `asyncio.Queue`'s own documented behavior — `maxsize <= 0` disables the bound entirely — and it's the opposite of what "0" would mean for almost any other size-like parameter in this same codebase, where 0 usually reads as "nothing fits." A developer who reaches for `OUTBOUND_QUEUE_MAXSIZE=0` expecting "the smallest possible queue, so backpressure trips immediately" gets the one configuration that guarantees backpressure never trips at all, which is the exact failure mode this whole chapter exists to prevent — now self-inflicted through a single misread environment variable rather than a missing bound.

`verify.sh` hits this directly while building its own deterministic trigger for Step 5. Quarkus's guard compares `pending.get() >= maxPendingSends`, so `EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0` trips on the very first send attempt — `0 >= 0` is true before anything has been sent — and that's exactly the value `verify.sh` uses for the Quarkus one-off container. The Python side can't use the same trick: `OUTBOUND_QUEUE_MAXSIZE=0` doesn't make a zero-capacity queue, it makes an unbounded one, so the harness instead sets `OUTBOUND_QUEUE_MAXSIZE=1`. That value works because `_run_connection` enqueues all three fixture events synchronously, before the `drain` task ever gets scheduled to pull the first one off — so the second `enqueue()` call always lands against a queue that's already holding one item with `maxsize=1`, overflowing deterministically regardless of how the event loop happens to schedule things afterward. Two different "trip it reliably" values for what looks like the identical knob, and the reason for the difference is this exact asymmetry between how `0` behaves in a hand-rolled counter versus a standard-library bounded queue.

## TCP flow control underneath the application bound

Everything above happens above the transport layer, and the application-level bound this chapter builds is not duplicating what TCP already does underneath it — it covers a gap TCP flow control leaves open. TCP already has its own backpressure: a receiver advertises a window of how much unacknowledged data it's willing to buffer, and a sender's kernel stops pushing new bytes onto the wire once that window fills, because the peer hasn't acknowledged room for more. That's exactly what the "a single `send()` call hangs" signal is observing from the application's side — `websocket.send()`/`sendText()` ultimately writes into the OS socket buffer, and if the client's TCP receive window has filled (because its application stopped calling `recv()`/reading the socket), the kernel's own write call blocks, and that block is what surfaces, several layers up, as the timeout `OutboundBackpressureGuard` and `OutboundQueue` both watch for.

So why isn't TCP's own flow control enough on its own, without any of this application-level bookkeeping? Because TCP's window only throttles how fast bytes go out onto one socket — it has no opinion on what the application producing those bytes should do while it's waiting, and by itself it provides no signal the application can act on before that write call blocks the calling thread or coroutine. Without `OutboundBackpressureGuard`'s or `OutboundQueue`'s bound sitting above it, a blocked write doesn't stop the producer; it starts queuing up whatever the producer keeps handing it in application memory while the write sits blocked, which is precisely the unbounded-growth path the previous section walked through. TCP flow control protects the network and the two kernels from being overrun with un-acknowledged bytes; it does nothing to protect the server process's own heap from a producer that keeps generating `HandlingEvent`s faster than one stalled socket can carry them away. The application-level buffer and its policy are what turn "the kernel's write call is blocked" into a decision the server makes directly — wait up to a bounded time, then close or drop — instead of an unbounded pile-up that only becomes visible once the process runs out of memory.

## On the wire

`examples/part4-connection/verify.sh`'s Step 5 is where this chapter's close code stops being Javadoc and docstring and becomes something a running process does, live. The comment introducing that step states the deterministic-trigger problem directly: Quarkus's guard "compares pending-sends > threshold, so 0 trips before anything is ever sent," while Python's `OutboundQueue` "sits on top of `asyncio.Queue`, where `maxsize<=0` means UNBOUNDED ... rather than zero-capacity" — the opposite of a deterministic trigger — which is why the harness settles on `1` for Python instead. Both one-off containers run on alternate host ports (`18080` for Quarkus, `18091` for Python) so the primary stack keeps running throughout:

```bash
echo "--- Quarkus: EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0 ---"
docker run -d --name "$BP_QUARKUS_NAME" \
  -p "${BP_QUARKUS_PORT}:8080" \
  -e "WS_JWT_SECRET=${SHARED_JWT_SECRET}" \
  -e EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0 \
  "$QUARKUS_IMAGE" >/dev/null
wait_for_ws "localhost:${BP_QUARKUS_PORT}" "$CHANNEL_PATH"
bp_result="$(ws_close_probe "ws://localhost:${BP_QUARKUS_PORT}${CHANNEL_PATH}?token=${VALID_TOKEN}")"
assert_eq "4290" "$(json_field '.close_code' <<<"$bp_result")" "quarkus backpressure close code"
assert_eq "0" "$(json_field '.frames' <<<"$bp_result")" "quarkus backpressure: zero frames delivered before close"

echo "--- Python: OUTBOUND_QUEUE_MAXSIZE=1 ---"
docker run -d --name "$BP_PYTHON_NAME" \
  -p "${BP_PYTHON_PORT}:8081" \
  -e "WS_JWT_SECRET=${SHARED_JWT_SECRET}" \
  -e OUTBOUND_QUEUE_MAXSIZE=1 \
  "$PYTHON_IMAGE" >/dev/null
wait_for_ws "localhost:${BP_PYTHON_PORT}" "$CHANNEL_PATH"
bp_result="$(ws_close_probe "ws://localhost:${BP_PYTHON_PORT}${CHANNEL_PATH}?token=${VALID_TOKEN}")"
assert_eq "4290" "$(json_field '.close_code' <<<"$bp_result")" "python backpressure close code"
```

`ws_close_probe` is the small `websockets`-library Python script `verify.sh` uses throughout, because `websocat` can't observe close codes reliably — it opens the connection, reads frames until the server closes it, and prints one line of JSON: `{"frames": N, "envelope_bad_request": bool, "close_code": N|null}`. Against both one-off containers above, that line comes back identically shaped on both stacks:

```json
{"frames": 0, "envelope_bad_request": false, "close_code": 4290}
```

Zero frames, because both thresholds were forced low enough to trip the CLOSE policy before the very first `HandlingEvent` in the fixture ever reaches the socket — `assert_eq "0" ... "quarkus backpressure: zero frames delivered before close"` is the harness checking exactly that. Run it from the repo root to watch it happen against both stacks in sequence:

```bash
cd examples/part4-connection
./verify.sh
```

The env knobs this chapter's example exposes, pulled directly from `examples/part4-connection/README.md`'s table:

| Env var | Stack | Default | Purpose |
|---|---|---|---|
| `EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS` | Quarkus | `32` | outbound in-flight send cap |
| `EXAMPLE_BACKPRESSURE_POLICY` | Quarkus | `CLOSE` | `CLOSE` or `DROP` |
| `OUTBOUND_QUEUE_MAXSIZE` | Python | `32` | outbound queue depth (`<=0` is unbounded, not zero-capacity) |
| `OUTBOUND_BACKPRESSURE_POLICY` | Python | `close` | `close` or `drop` |

To watch the `DROP` policy instead — events discarded with a warning rather than the connection closing — set `EXAMPLE_BACKPRESSURE_POLICY=DROP` (Quarkus) or `OUTBOUND_BACKPRESSURE_POLICY=drop` (Python) alongside the same forced-low threshold and the warning line each implementation logs (`Log.warnf`/`logger.warning`) shows up instead of a `4290` close.

## Where this goes next

This chapter built the server-side mirror of Chapter 10's client-side buffer: a bounded outbound path with two independent trigger signals (a full buffer, a single send past its timeout) and an explicit, configured policy for what happens once one of them fires, defaulting to the safer choice — close the slow consumer — rather than the one that loses data without any record of the gap, for a channel where every event is a fact that matters. The `maxsize=0` gotcha is a reminder that the primitive underneath a bounded queue can have its own surprising edge behavior, and that edge behavior is exactly the kind of thing `verify.sh` exists to catch live rather than leave as an assumption. Chapter 13 picks up the other close code this same endpoint uses — `4400` for a malformed client frame on a channel that defines no client-to-server messages at all — and the broader error taxonomy both stacks share. Chapter 14 adds the liveness layer this chapter's backpressure guard doesn't cover on its own: a client that's still technically connected, still answering nothing, but never stalls a `sendText` call long enough to trip the backpressure timeout, which needs its own dedicated detector rather than relying on this chapter's mechanism to notice it. And Chapter 20 returns to throughput from a different angle — not what to do when a consumer falls behind, but how to get more useful work through the channel before it has to.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>A server pushing data over a long-lived connection needs a bounded outbound path for the same reason a client needs a bounded inbound one, but for a sharper reason: one slow client can only hurt itself if nothing bounds the buffer in front of it, while a server with no bound multiplies that cost by every connection it happens to be serving, turning one stalled client into an unbounded-memory problem for the whole process. Both stacks in this example watch the identical two signals — the buffer (or outstanding-send counter) is full, or a single send exceeds a timeout — and apply one of two policies: <code>CLOSE</code> (the default, close code <code>4290</code>) stops sending and tears the connection down, the safer choice when every missed event is a correctness problem rather than a value superseded by the next update; <code>DROP</code> discards the offending event and keeps the connection open, appropriate only for feeds where staleness beats a gap. Treat a size-like environment variable's zero value as something to verify, not assume — <code>asyncio.Queue</code>'s <code>maxsize&lt;=0</code> means unbounded, the opposite of what "zero capacity" would suggest, and the only way this chapter's own test harness caught it was by running the deterministic trigger live and watching Python's queue refuse to overflow at the value that worked for Quarkus.</p></div>
