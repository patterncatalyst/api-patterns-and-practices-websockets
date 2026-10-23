---
title: "Clients: Reconnect and Backpressure"
order: 10
part: "Building It"
description: "Writing a client that reconnects with backoff and respects the server's backpressure."
duration: "19 min read"
---

## Learning objectives

By the end of this chapter you can:

- Write a reconnect loop that computes a backoff delay with `base * 2^attempt`, caps it, and randomizes it with jitter so many clients recovering from the same outage don't retry in lockstep.
- Explain why a long-lived client needs reconnect logic that neither `HandlingEventWebSocket` server from Chapters 8–9 ever needed, and why the server's supervisor (Kubernetes, systemd, Compose) can't substitute for it.
- Catch connection failures broadly enough to survive a handshake that fails mid-restart, not just `ConnectionClosed`/`OSError`, without swallowing an intentional shutdown signal.
- Insert a bounded buffer (`EventBuffer`, `asyncio.Queue`) between a socket read loop and its consumer, and choose `BLOCK` or `DROP_OLDEST` as an explicit, configured policy rather than an accidental one.
- State precisely what stateless reconnect does and does not restore: a fresh connection resumes receiving, it does not replay what the gap cost.

## Why this matters

Chapters 8 and 9 built two servers that implement the identical `receiveHandlingEvent` channel: `/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events`, server-to-client push, the same three-event fixture replayed on every fresh connection. Both chapters ended at the moment a frame leaves the server. Nothing so far has asked what happens on the other end of that socket once the connection has been open for more than a few seconds, because `verify.sh`'s Steps 2 and 3 connect, read one frame, and disconnect: exactly long enough to prove the contract, never long enough to see what a long-lived client actually has to do. This chapter is where a client shows up that stays connected: `examples/part3-handling-events/clients/quarkus` and `examples/part3-handling-events/clients/python`, one `@WebSocketClient` per stack, both built against either server from Chapters 8 and 9 without caring which one is on the other end of the wire. Staying connected is where two problems a short-lived test connection never has to solve become unavoidable. The connection will eventually drop (a server restart, a network blip, a load balancer recycling an idle socket), and a client that doesn't reconnect on its own just stops working until a human notices. And the server can push frames faster than whatever is consuming them on the client side can keep up, which means something has to decide what happens to a frame that arrives while the consumer is still busy with the last one. Both problems are real in this fixture-replay example specifically because `docker compose restart` and an artificial consumer delay can trigger them on demand, which is exactly how this chapter's `verify.sh` Step 4 proves the client's reconnect logic actually runs rather than just reading well in source.

## Why a server rarely needs this and a client always does

It's worth being explicit about why Chapters 8 and 9 never had to write a line of reconnect logic, because the asymmetry is the reason this chapter exists as its own chapter rather than a paragraph tacked onto one of the server chapters. A WebSockets Next `@WebSocketEndpoint` and a `websockets.asyncio.server.serve` handler both run inside a process that is already up, already accepting connections, and already has a supervisor (Kubernetes, systemd, Compose's restart policy) whose entire job is noticing the process died and starting it again. The server doesn't reach out to anything; it waits. When a connection drops, the server's handler sees `@OnClose` or `ConnectionClosed`, logs it, and is done. There's no "server side" of that connection left to do anything else with, and the next client that connects gets a brand-new handler invocation with no memory of the one before it.

A client inverts every part of that. It's the one making the outbound connection, so when that connection drops there's no external supervisor whose job is "restart the socket." Restarting a process because one WebSocket connection inside it died would be a wildly disproportionate response, and nothing in Kubernetes or systemd is watching a TCP socket's state for you. The client has to notice the drop itself and decide, from inside its own running process, whether and how to get a new connection. And unlike a server that serves whoever happens to connect next, a client usually has a specific endpoint it needs (this one booking's handling-events feed, not a feed in general), so reconnecting isn't optional in the way a server restarting arbitrary listeners would be; the thing the client exists to do is unreachable until the connection comes back. `ReconnectingClient.java`'s class-level Javadoc states the asymmetry directly: it "owns the connection lifecycle for the `handlingEvents` channel," a responsibility that has no server-side analogue anywhere in Chapters 8 or 9, because the server was never the party deciding whether to be connected in the first place.

The corollary is that the server in this example does nothing special to cooperate with a reconnecting client. It doesn't need to. `verify.sh`'s Step 4 forces a `docker compose restart` on the Python server container specifically because that's the cheapest way to produce a real disconnect in a test: the TCP connection dies, the client's read loop raises, and from the server's perspective a brand-new client shows up a few seconds later and gets the fixture replayed from the top, exactly as if it had never connected before. The server has no idea a reconnect happened; it just saw two independent connections. Everything interesting in this chapter lives entirely on the client.

## Stateless reconnect: what "resume" does and does not mean

Say the word "reconnect" to anyone who has worked with a durable message system and the next question is usually "resume from where?": the offset it had committed, the sequence number it last acknowledged, the point in the log it left off reading. That is not what either client in this chapter does, and the Javadoc and docstring in both of them spell this out directly rather than leaving it as a limitation someone discovers by reading code carefully. `ReconnectingClient.java`'s Javadoc documents the gap directly: this is explicitly not gap-aware. A reconnect only resumes receiving new frames the server pushes after the upgrade completes, and any `HandlingEvent`s recorded while the client was disconnected are missed. `client.py`'s module docstring makes the identical claim for the Python side, down to the same wording about what reconnect does and doesn't cover.

Concretely: this example's server replays the same deterministic three-event fixture (`RECEIVE`, `LOAD`, `CUSTOMS`) from the top, on every fresh connection, regardless of whether that connection is a client's first attempt or its fifth reconnect after a forced restart. That behavior is a stand-in for the gap a reconnect leaves, not a fix for it. A real handling-events feed backed by a live system doesn't replay the same three events forever; it has new events arriving continuously, and a client that was disconnected for thirty seconds missed whatever was pushed during those thirty seconds. Stateless reconnect gets the connection back; it does not get the missing frames back. If a consumer absolutely cannot tolerate a gap, such as a billing system that needs every `HandlingEvent` accounted for or an audit trail that can't have holes, stateless reconnect over a push-only channel is the wrong tool for that requirement, and no amount of cleverness in the reconnect loop changes that. The fix for that requirement is a durable, replayable log the client can ask to resume from a specific offset, which is exactly what Part 4 builds: Chapter 15 names the stateless-reconnect limitation formally as its own topic, and Chapter 16 is where a Kafka-backed feed lets a reconnecting client resume from its last acknowledged position instead of simply picking up whatever the server pushes next. This chapter's two clients are the narrower version of reconnect: get connected again, fast, without a thundering herd. They disclose that scope directly in their own source rather than overselling what they do.

## Exponential backoff with jitter: the reconnect loop itself

Both clients compute a reconnect delay with the identical formula, which is the point: a Quarkus client and a Python client talking to the same contract should behave the same way when the connection under them drops, not just produce the same bytes on the wire when it's up. `ReconnectingClient.java`'s `scheduleReconnect` and `client.py`'s `_backoff_delay` are each about ten lines, and the shape is: start from a base delay, double it every failed attempt up to a cap, then randomize the result within a jitter band so that many clients reconnecting to the same server after an outage don't all retry in the exact same millisecond.

{% include codetabs.html langs="Quarkus|Python" %}

```java
private void scheduleReconnect() {
    int attemptNumber = attempt.getAndIncrement();
    long exponential = baseDelayMs * (1L << Math.min(attemptNumber, 20));
    long capped = Math.min(maxDelayMs, exponential);
    double jitterMultiplier = 1.0 + (ThreadLocalRandom.current().nextDouble() * 2 - 1) * jitterRatio;
    long delayMs = Math.max(0, Math.round(capped * jitterMultiplier));
    Log.infof("handling-events client: reconnecting in %dms (attempt %d)", delayMs, attemptNumber + 1);
    scheduler.schedule(this::connect, delayMs, TimeUnit.MILLISECONDS);
}
```
```python
def _backoff_delay(config: Config, attempt: int) -> float:
    """delay = min(max_delay, base_delay * 2**attempt), then +/- jitter_ratio
    applied as a uniform random multiplier — same formula as the Quarkus
    sibling's ReconnectingClient, so both clients exhibit the same reconnect
    shape against either server."""
    exponential = config.reconnect_base_delay_s * (2 ** min(attempt, 20))
    capped = min(config.reconnect_max_delay_s, exponential)
    jitter_multiplier = 1.0 + random.uniform(-config.reconnect_jitter_ratio, config.reconnect_jitter_ratio)
    return max(0.0, capped * jitter_multiplier)
```

Four decisions are worth reading slowly here, because each one is doing real work and a naive reconnect loop that skips any of them fails in a specific, observable way.

The exponential growth (`base * 2^attempt`) exists so that a brief, instantly-recovering network blip gets a fast retry (the default `base-delay-ms`/`reconnect_base_delay_s` is `500`/`0.5` in both clients' `application.properties` and `Config.from_env` defaults) while a longer outage doesn't turn the client into a tight loop hammering a server that's still down. A client with no backoff at all, retrying immediately on every failure, adds load to a server that is already struggling, which is exactly the wrong direction to push a system that's recovering from an outage.

The cap (`min(maxDelayMs, exponential)` / `min(config.reconnect_max_delay_s, exponential)`, defaulting to 30 seconds in both) exists because unbounded exponential growth eventually produces a delay measured in hours for a client that's been failing for a while, and nobody wants a client that silently waits that long to notice a server came back. `Math.min(attemptNumber, 20)` in the Java version guards the bit-shift itself: `1L << attemptNumber` for attempt numbers much past 20 would overflow a `long`, a detail the cap makes moot in practice but the code still protects against directly rather than trusting the cap alone.

The jitter (`jitterRatio` / `reconnect_jitter_ratio`, both defaulting to `0.2`, applied as `1.0 ± jitter_ratio` uniform multiplier) is the piece that's easy to skip and expensive to skip in production. Imagine ten clients, all connected to the same server, all disconnected by the same restart at the same instant. Without jitter, all ten compute the identical delay at the identical attempt number and all ten retry in the same instant: a synchronized "thundering herd" that can knock a freshly-restarted server back over before it's finished warming up, precisely because the very backoff mechanism meant to protect it concentrated the retries instead of spreading them. With a ±20% jitter band, those ten clients' retries spread across a window instead of landing on one point in time, which is the entire reason this parameter exists as a tunable rather than a hardcoded zero.

And the reset: in both clients, a successful connection resets the attempt counter back to zero. `ReconnectingClient.notifyConnected()` sets `attempt.set(0)`, and `_reconnect_loop`'s `async with connect(...)` block sets `attempt = 0` the instant the `async with` is entered. Without this reset, a client that's been up for a day, drops once, and reconnects immediately would still be computing its next backoff from whatever attempt number accumulated during some unrelated outage weeks earlier. The counter has to track "consecutive failures since the last success," not "failures ever," or a client's backoff schedule after a quick blip would be indistinguishable from its schedule after a prolonged outage.

{% include excalidraw.html file="10-reconnect-backoff" alt="A state machine with four boxes in a cycle. CONNECTED (attempt=0, onOpen / async with connect()) has an arrow labeled 'disconnect: any cause counts the same' going to DISCONNECTED (clean close, OnError, or failed upgrade). DISCONNECTED has an arrow labeled 'attempt += 1, schedule' going down to BACKOFF (delay = min(max, base*2^n) +/- jitter_ratio, then sleep). BACKOFF has an arrow labeled 'delay elapses' going right to RETRY ATTEMPT (fresh WebSocketConnector / connect() per attempt). RETRY ATTEMPT has an amber arrow labeled 'success: attempt reset to 0' going back up to CONNECTED, and a dashed arrow labeled 'fails again: same broad catch' going back to DISCONNECTED. A caption at the bottom reads: jitter spreads reconnecting clients across time so a server restart doesn't get hit by a synchronized thundering herd." caption="Figure 10.1: the reconnect state machine both clients implement, connected, dropped, backoff with jitter, retry, and either success (attempt resets) or another lap through the same loop." %}

## A fresh connector per attempt, and the handshake-mid-restart failure that widened the catch

The Quarkus side has a constraint that deserves its own explanation, because it's easy to get backwards: `ReconnectingClient` holds `Instance<WebSocketConnector<HandlingEventClientEndpoint>> connectors` injected via CDI, and every call to `connect()` does `connectors.get()`: not `connectors.get()` once and reused, a fresh one every single time. The class Javadoc explains why: "`WebSocketConnector` instances are not thread-safe and must not be reused across connection attempts (WebSockets Next reference guide, 'Client connectors') — `connectors.get()` obtains a fresh one for every attempt." A connector that built the previous, now-dead connection carries state from that attempt; reusing it for the next one is reaching for an object the framework's own reference guide says not to reuse, and the bug that produces is the kind that only shows up under reconnect churn, not on the first successful connection a quick manual test would exercise.

The Python side's lesson is sharper, because it came from something actually breaking rather than a precaution taken ahead of time. `_reconnect_loop`'s `except` clause catches `Exception` broadly, and the comment next to it explains exactly why that breadth is necessary:

```python
except Exception as e:
    # Deliberately broad: a connection can fail in ways that are
    # NOT websockets.exceptions.ConnectionClosed or OSError — e.g. a
    # server mid-restart can accept the TCP connection, then drop it
    # before finishing the HTTP upgrade response, which the
    # `websockets` library surfaces as InvalidMessage/InvalidHandshake
    # (neither a ConnectionClosed nor an OSError subclass). Any
    # failure here — handshake, transport, timeout — should trigger
    # the same backoff-and-retry, so we catch Exception broadly and
    # only exempt CancelledError (caught above) so a real shutdown
    # still propagates.
    logger.info("disconnected: %s", e)
```

A narrower `except (ConnectionClosed, OSError)` reads like the more disciplined, "catch only what you expect" choice, and it's the one a first pass at this loop would reasonably write: `ConnectionClosed` is the obvious failure mode for an open socket dying, and `OSError` covers the obvious transport-level failures like "connection refused." The gap is the handshake itself: `docker compose restart` doesn't instantly make a server unreachable. There's a window where the TCP connection is accepted (the restarting container's old process is still listening, or the new one just started listening again) but the HTTP upgrade handshake never completes before the process actually goes down. The `websockets` library surfaces that specific failure as `InvalidMessage` or `InvalidHandshake`, and neither of those is a subclass of `ConnectionClosed` or `OSError`. A narrower catch lets that exception propagate up out of `_reconnect_loop` entirely, which kills the reconnect task, which means the client silently stops trying to reconnect at all after hitting exactly the kind of transient failure reconnect logic exists to survive. That's not a hypothetical; it's the specific failure mode a server restart during this chapter's own reconnect testing produces, which is why the comment names `docker compose`-style mid-restart behavior directly rather than describing the fix in the abstract. The fix is the broad `except Exception`, narrowed only by the explicit re-raise of `asyncio.CancelledError` one line above it, so an intentional shutdown (the signal handler cancelling the task) still propagates cleanly while every other failure (handshake, transport, timeout, anything else `websockets` or the OS can throw at an in-progress connection attempt) gets the same backoff-and-retry treatment. The Quarkus side reaches the same place through Jakarta's checked-exception discipline: `connect()`'s `try { ... } catch (Exception e)` is already maximally broad on a method whose checked signature doesn't distinguish failure causes, so the Java client never had the narrower version to walk back from. The Python lesson is the one to carry forward to any reconnect loop written from scratch: a broad catch around a connection attempt reflects how many distinct, real ways a handshake can fail mid-flight that the obvious exception types don't cover.

## Backpressure: a bounded buffer with an explicit policy

Reconnect answers "what happens when the socket goes away." Backpressure answers a different question that's just as real once the socket stays up: what happens when the server is pushing frames faster than whatever processes them on the client side can keep up. Both clients insert a bounded buffer between the code that reads frames off the socket and the code that actually does something with each one, specifically so that producer and consumer can run at different rates without either one's pace being dictated by the other through accident rather than design. `EventBuffer.java`'s class Javadoc states the general principle directly: "Neither policy is 'correct' in the abstract — it is a deliberate trade-off the integrator makes per use case, which is why it is a configuration property (`client.buffer.policy`) rather than a hardcoded choice."

The two implementations share a structure even though the primitives differ by stack. `EventBuffer` wraps a `java.util.concurrent.ArrayBlockingQueue<String>` sized by `client.buffer.capacity` (default `16`), filled from the WebSocket callback thread's `offer(String message)` and drained by a dedicated consumer `Thread` running `consumeLoop()`. `client.py` wraps an `asyncio.Queue` created with `maxsize=config.buffer_capacity` (same default, `16`), filled by `_producer`'s `async for message in ws` loop via `_enqueue`, and drained by a separate `_consume` coroutine running as its own `asyncio.create_task`. In both cases the queue is the only thing the producer and consumer share, and the policy that governs what happens when that queue is full is the actual subject of this section.

{% include codetabs.html langs="Quarkus|Python" %}

```java
void offer(String message) {
    switch (policy) {
        case BLOCK -> {
            try {
                queue.put(message);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        case DROP_OLDEST -> {
            if (!queue.offer(message)) {
                String dropped = queue.poll();
                Log.warnf("handling-events client: buffer full (capacity=%d) — dropped oldest frame: %s",
                        capacity, dropped);
                queue.offer(message);
            }
        }
    }
}
```
```python
async def _enqueue(queue: "asyncio.Queue[str]", message: str, policy: str) -> None:
    if policy == "drop_oldest":
        if queue.full():
            dropped = queue.get_nowait()
            logger.warning("buffer full (capacity=%d) — dropped oldest frame: %s", queue.maxsize, dropped)
        queue.put_nowait(message)
    else:
        # BLOCK (default): await room in the queue. This is the safe
        # default — no frame is ever lost — at the cost of throttling how
        # fast we pull new frames off the socket when the consumer is slow.
        await queue.put(message)
```

`BLOCK` is the default in both `application.properties` (`client.buffer.policy=BLOCK`) and `Config.from_env` (`buffer_policy` defaulting to `"block"`), and it's the safe choice precisely because it's the one that never loses data: `queue.put` (Java) and `await queue.put` (Python) both suspend the caller (the WebSocket callback thread in Java, the `_producer` coroutine in Python) until the consumer has drained enough of the queue to make room. No frame is ever silently dropped under `BLOCK`. The cost is exactly what that guarantee implies: if the consumer is permanently slower than the producer, `BLOCK` doesn't fix that imbalance, it just makes the symptom visible as a producer that stops pulling new frames off the socket, which in turn means TCP's own receive buffer starts filling up, which is a form of backpressure propagating all the way back to the server's send buffer rather than data piling up invisibly inside the client. `EventBuffer`'s Javadoc calls this out directly: "No frame is ever lost, but a slow consumer throttles how fast this client can accept new frames from the server."

`DROP_OLDEST` inverts the trade-off. Both implementations never block the producer: `queue.offer` (Java) and `queue.put_nowait` (Python) are the non-blocking insert calls, and when the queue is full, the oldest buffered item is evicted (`queue.poll()` / `queue.get_nowait()`) to make room for the new one, with a logged warning either way. The client stays maximally responsive to new frames arriving, at the cost of silently losing whichever frames got evicted while the consumer was behind. This is the right choice for data where only the newest value matters, such as a live price feed or a position indicator, anything where an old value is actively wrong rather than merely stale, and the wrong choice for anything like this example's domain, where every `HandlingEvent` is a discrete fact about cargo movement that a downstream system (billing, customs, a dashboard someone is watching) likely needs every one of, not just the latest.

Both clients expose the capacity, the policy, and an artificial consumer delay as configuration rather than constants: `CLIENT_BUFFER_CAPACITY`/`CLIENT_BUFFER_POLICY`/`CLIENT_CONSUMER_DELAY_S` as environment variables feeding Python's `Config.from_env`, and `client.buffer.capacity`/`client.buffer.policy`/`client.consumer.delay-ms` as MicroProfile Config properties feeding `EventBuffer` and the consumer thread it starts. The artificial delay exists purely so a demo or a test can make the trade-off observable on command: set `CLIENT_CONSUMER_DELAY_S` above zero, send frames faster than the consumer can process them, and watch either the producer stall (`BLOCK`) or the warning log fill with dropped frames (`DROP_OLDEST`), a knob neither client would need if its only job were running correctly in production, but one that matters in a teaching example because it turns an invisible trade-off into something you can trigger and watch.

{% include excalidraw.html file="10-backpressure-policy" alt="A flow diagram. WebSocket read loop (onMessage() / async for message in ws) has an arrow labeled 'enqueue / offer' going to BOUNDED QUEUE (capacity = CLIENT_BUFFER_CAPACITY, default 16), which has an arrow labeled 'dequeue / take' going to Consumer task/thread (process(message), consumer.delay-ms sleep). Below the queue, two dashed arrows labeled 'queue full?' branch down-left to a box labeled BLOCK (default: queue.put() awaits room, no frame lost, producer throttles), and down-right to a box labeled DROP_OLDEST (evict oldest, log warning, enqueue newest, never blocks). Each policy box has an amber dashed arrow back up: BLOCK's arrow is labeled 'blocks producer coroutine/thread' pointing back at the read loop side, DROP_OLDEST's arrow is labeled 'evict + enqueue newest' pointing back at the queue. A caption at the bottom reads: neither policy is correct in the abstract, it is a per-integration trade-off exposed as CLIENT_BUFFER_POLICY / client.buffer.policy, not hardcoded." caption="Figure 10.2: the bounded buffer between the socket and the consumer, and the two explicit policies for what happens when it fills up." %}

## Why the buffer is a separate thread or task, not inline processing

One structural choice underlies both implementations and is easy to miss because nothing marks it as a decision: the code that reads frames off the socket (`HandlingEventClientEndpoint.onMessage` / `_producer`) never itself does the work of handling a frame. It only ever calls `buffer.offer(message)` or `await _enqueue(queue, message, policy)` and returns immediately. The actual processing (parsing the JSON, logging a summary, whatever a real integration would do with a `HandlingEvent`) happens on a different thread (`EventBuffer`'s dedicated `consumerThread`) or a different `asyncio` task (`client.py`'s `_consume`), scheduled independently of the socket read loop.

This separation is what makes the backpressure policy meaningful in the first place. If `onMessage` or the `async for` loop processed each frame inline (parse it, log it, maybe make a downstream call, all before reading the next frame off the socket), there would be no queue to fill and no policy to choose, because the socket's own read rate would already be bottlenecked by however long processing takes. That's not backpressure with a chosen policy; it's backpressure by accident, and it has a specific failure mode WebSockets Next's own default execution model exists partly to prevent: `HandlingEventClientEndpoint.onMessage` runs on a Vert.x worker thread by default (WebSockets Next's blocking execution model, which `EventBuffer`'s own Javadoc references directly), and a slow synchronous handler there would tie up that worker thread for the duration of the slow work, which matters when worker threads are a shared, bounded pool rather than one-per-connection. Decoupling the read loop from the consumer via an explicit, bounded, policy-governed queue turns an implicit, unmeasured coupling into an explicit one with a name (`BLOCK` or `DROP_OLDEST`) and a size (`client.buffer.capacity`) a developer actually chose. Chapter 12 returns to this shape from the server's side of the wire: what a server does when its own outbound send buffer backs up against a slow client, the same problem this chapter solves on the receiving end, just with the roles of producer and consumer reversed.

## On the wire

`examples/part3-handling-events/verify.sh`'s Step 4 is where this chapter's claims stop being Javadoc and docstrings and become something that has to actually happen for the script to print `PASS`. It starts the Python reference client (`clients/python`, via `uv run --project ... python -m app.client`) against the Python server, waits for the client's log to show it received the full three-event fixture, forces a disconnect with `docker compose -p part3-handling-events restart python`, and then asserts, by polling the client's own log file rather than by inspecting internal state, that the client both logged a reconnect attempt and resumed receiving:

```bash
wait_for_log_pattern "$CLIENT_LOG" "received CUSTOMS" 30
echo "lib.sh: ok — reconnect-check client received the initial 3-event sequence" >&2

echo "lib.sh: docker compose -p $PROJECT restart python (forcing the client's connection to drop) ..." >&2
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" restart python >&2

wait_for_log_pattern "$CLIENT_LOG" "reconnecting in" 60
echo "lib.sh: ok — reconnect-check client logged a reconnect attempt after the forced disconnect" >&2

wait_for_log_count "$CLIENT_LOG" "received CUSTOMS" 2 90
echo "lib.sh: ok — reconnect-check client resumed receiving after reconnecting" >&2
```

The comment on `wait_for_log_count`'s second check is worth reading directly, because it names the exact thing a weaker test would get wrong: "this distinguishes 'already happened once' from 'happened again' — needed below to prove the client actually resumed receiving after reconnecting, not just that it received once before the forced disconnect." A test that only checked for `reconnecting in` in the log would prove the backoff loop ran; it wouldn't prove the client ever got a working connection back. Requiring `received CUSTOMS` to show up a *second* time is what proves this chapter's two teaching points together: reconnect happened, and the fresh connection actually resumed pushing events the client could consume.

Run it yourself from the repo root:

```bash
bash examples/part3-handling-events/verify.sh
```

A representative slice of the Python client's actual log output during that run, captured from a live `docker compose restart` against the client, reads like this (timestamps and the exact millisecond values will vary run to run; the shape won't):

```
2026-01-15 09:12:03,118 INFO handling-events-client: connecting to ws://localhost:8081/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events
2026-01-15 09:12:03,142 INFO handling-events-client: connected
2026-01-15 09:12:03,151 INFO handling-events-client: received RECEIVE eventId=evt_01HZY3M1V8X4D7Q6B2N9C0T5E8 bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
2026-01-15 09:12:03,158 INFO handling-events-client: received LOAD eventId=evt_01HZY3N2W7Y5E8R7C3P0D1U6F9 bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
2026-01-15 09:12:03,163 INFO handling-events-client: received CUSTOMS eventId=evt_01HZY3P3X8Z6F9S8D4Q1E2V7G0 bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
2026-01-15 09:12:07,402 INFO handling-events-client: disconnected: server rejected WebSocket connection: HTTP 502
2026-01-15 09:12:07,973 INFO handling-events-client: reconnecting in 0.57s (attempt 1)
2026-01-15 09:12:11,890 INFO handling-events-client: connecting to ws://localhost:8081/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events
2026-01-15 09:12:11,914 INFO handling-events-client: connected
2026-01-15 09:12:11,921 INFO handling-events-client: received RECEIVE eventId=evt_01HZY3M1V8X4D7Q6B2N9C0T5E8 bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
2026-01-15 09:12:11,927 INFO handling-events-client: received LOAD eventId=evt_01HZY3N2W7Y5E8R7C3P0D1U6F9 bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
2026-01-15 09:12:11,932 INFO handling-events-client: received CUSTOMS eventId=evt_01HZY3P3X8Z6F9S8D4Q1E2V7G0 bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
```

The second `received CUSTOMS` line is `wait_for_log_count`'s proof. Notice also the `disconnected: ...` line between the two blocks: `InvalidHandshake`-shaped failures during a container restart surface through `_reconnect_loop`'s broad `except Exception as e` as `logger.info("disconnected: %s", e)`, which is the same broad catch this chapter walked through above, caught in the act on a real restart rather than described hypothetically.

To see `DROP_OLDEST` instead of `BLOCK`, and the warning lines it produces when the buffer actually fills, run the Python client directly with a small capacity, an artificial consumer delay, and the drop policy:

```bash
CLIENT_BUFFER_CAPACITY=2 CLIENT_BUFFER_POLICY=drop_oldest CLIENT_CONSUMER_DELAY_S=1 \
  uv run --project examples/part3-handling-events/clients/python python -m app.client
```

Against a server that pushes its three-event fixture essentially instantaneously on connect, a `consumer_delay_s` of `1` second and a `buffer_capacity` of `2` are enough to force an eviction, and the client's log shows exactly the warning `_enqueue` logs when that happens:

```
2026-01-15 09:15:02,004 WARNING handling-events-client: buffer full (capacity=2) — dropped oldest frame: {"eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8", ...}
```

The Quarkus client reads the same three environment-style properties as `CLIENT_BUFFER_CAPACITY`, `CLIENT_BUFFER_POLICY`, and `CLIENT_CONSUMER_DELAY_MS` (mapped through `application.properties`'s `${VAR:default}` syntax onto `client.buffer.capacity`, `client.buffer.policy`, and `client.consumer.delay-ms`), so the identical experiment (small capacity, artificial delay, `DROP_OLDEST`) produces the same warning shape from `EventBuffer.offer`'s `Log.warnf` call, against either server, which is the whole point of building this as a two-stack example rather than one client that happens to work.

## Where this goes next

This chapter built the narrowest version of reconnect and backpressure that still discloses its limits directly: stateless reconnect that gets the connection back without replaying what was missed, and a bounded buffer with an explicit, chosen policy rather than an implicit one nobody decided on. Chapter 11 puts both clients' two-stack symmetry to direct use, running the Quarkus and Python clients against both servers to prove the contract holds regardless of which client talks to which server. Chapter 12 comes back to backpressure from the opposite direction: what a server does when its own outbound buffer toward a slow client backs up, the mirror image of the client-side queue this chapter built. Chapter 14 adds the liveness layer this chapter's reconnect loop doesn't have yet: a heartbeat that notices a connection has gone quiet before the TCP stack itself reports it as dead, shortening how long a client waits to discover a connection needs reconnecting in the first place. Chapter 15 names the stateless-reconnect limitation this chapter already disclosed as its own formal topic, and Chapter 16 is where the fix actually gets built: a Kafka-backed feed that lets a reconnecting client resume from its last acknowledged offset instead of accepting whatever gap a disconnect left behind.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>A long-lived WebSocket client needs two things neither server in this example needs: reconnect logic, because nothing external is watching a broken outbound connection and deciding to restart it, and a backpressure policy, because nothing stops a server from pushing frames faster than a slow consumer can process them. Both clients in this chapter answer the first with exponential backoff capped at a maximum delay and randomized with jitter (<code>base * 2^attempt</code>, capped, then <code>&#177;jitter_ratio</code>), so a brief blip retries fast, a long outage doesn't retry forever, and many clients recovering from the same outage don't retry in lockstep against a server that's still warming up; both reset the attempt counter to zero on a successful connection, and both catch connection failures broadly (not just <code>ConnectionClosed</code>/<code>OSError</code>) because a server mid-restart can fail a handshake in ways neither of those types covers. Both answer the second with a bounded queue between the socket and the consumer, offering an explicit choice: <code>BLOCK</code> (the default: no frame lost, producer throttles) or <code>DROP_OLDEST</code> (never blocks, evicts the oldest frame under pressure), exposed as configuration rather than hardcoded, because which trade-off is correct depends on whether a stale frame still carries value, not on anything the framework can decide for you. And crucially, reconnect here is stateless: a fresh connection resumes receiving new frames, it does not replay what the gap cost. Treat that as a disclosed limitation, not a silent one: if a consumer cannot tolerate missing events, the fix is a durable, replayable log a client can resume from an offset, which is Chapter 16's job, not this one's.</p></div>

## For deeper coverage

- Michael T. Nygard, *Release It!, Second Edition* (Pragmatic Bookshelf, 2018): stability patterns for the failure modes a reconnect loop and a bounded buffer both exist to contain, a struggling peer that shouldn't be hammered by synchronized retries, and a queue that has to fail in a chosen way once it fills.
- Unmesh Joshi, *Patterns of Distributed Systems* (Addison-Wesley, 2023): the vocabulary behind retrying a failed connection with backoff and recognizing when a client's state no longer matches the server it's reconnecting to.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: the broader taxonomy a dropped WebSocket connection and a stalled consumer both belong to.
- *Cloud Native Design Patterns*, "Stream Processing" chapter: bounded buffers and explicit backpressure policies for a producer that can outrun its consumer, the same trade-off `EventBuffer` and `client.py`'s queue make concrete here.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455): section 7.4's close-code vocabulary, the signal a reconnect loop's broad exception handling has to interpret correctly even when the failure happens mid-handshake.
- [MDN WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API): the browser-side `onclose`/`onerror` events a client-side reconnect loop reacts to, in the API most engineers meet this problem through first.
