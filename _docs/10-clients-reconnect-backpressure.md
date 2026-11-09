---
title: "Clients: Reconnect and Backpressure"
order: 10
part: "Building It"
description: "Writing a client that reconnects with jittered exponential backoff and buffers frames behind an explicit backpressure policy."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Write a reconnect loop with `base * 2^attempt` delay, a cap and jitter, so clients recovering from one outage do not retry in lockstep.
- Explain why a long-lived client needs reconnect logic that a server never does.
- Catch connection failures broadly enough to survive a handshake that fails mid-restart, without swallowing a shutdown signal.
- Put a bounded buffer between the socket read loop and its consumer, and choose `BLOCK` or `DROP_OLDEST` as an explicit policy.
- State what stateless reconnect restores and what it does not.

## Why this matters

A client that stays connected hits two problems a short test connection never does. The connection will drop (a server restart, a network blip, a load balancer recycling an idle socket), and a client that does not reconnect on its own stops working until someone notices. And the server can push frames faster than the consumer handles them, so something has to decide what happens to a frame that arrives while the consumer is busy.

There is a client per stack: `examples/part3-handling-events/clients/quarkus` (a `@WebSocketClient`) and `examples/part3-handling-events/clients/python`, and either connects to either server. A `docker compose restart` and an artificial consumer delay trigger both problems on demand.

## Why a client always needs this

A server waits. Its process has a supervisor (Kubernetes, systemd, a Compose restart policy) whose job is restarting it, and when a connection drops its handler sees `@OnClose` or `ConnectionClosed`, logs it and is done. The next client gets a fresh handler with no memory of the last.

A client makes the outbound connection, and nothing external watches that socket. Restarting a process because one WebSocket inside it died would be disproportionate, so the client has to notice the drop and get a new connection itself. A client also usually needs one specific feed, so reconnecting is the reason it exists. The server does nothing to cooperate: after a restart it sees a new connection and replays the fixture from the top.

## Stateless reconnect

Reconnect with a durable system raises the question of resuming from where: a committed offset, a last acknowledged sequence number. Neither client here does that, and both say so. A reconnect resumes receiving whatever the server pushes after the upgrade completes. Events recorded while the client was away are missed. The fixture replaying from the top on every connection stands in for that gap and does not close it.

Stateless reconnect gets the connection back, not the missing frames. A consumer that cannot tolerate gaps, such as billing or an audit trail, needs a durable, replayable log it can resume from an offset. Stateless reconnect over a push-only channel is the wrong tool for it.

## Exponential backoff with jitter

Both clients use the same formula, so they behave the same when the connection drops: start from a base delay, double it per failed attempt up to a cap, then randomize within a jitter band.

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
    applied as a uniform random multiplier, same formula as the Quarkus
    sibling's ReconnectingClient, so both clients exhibit the same reconnect
    shape against either server."""
    exponential = config.reconnect_base_delay_s * (2 ** min(attempt, 20))
    capped = min(config.reconnect_max_delay_s, exponential)
    jitter_multiplier = 1.0 + random.uniform(-config.reconnect_jitter_ratio, config.reconnect_jitter_ratio)
    return max(0.0, capped * jitter_multiplier)
```

| Part | Default | What it prevents |
|---|---|---|
| `base * 2^attempt` | 500 ms | A blip gets a fast retry, and a long outage does not become a tight loop against a struggling server. |
| Cap | 30 s | Unbounded doubling reaching hours before the client notices the server is back. `min(attemptNumber, 20)` also keeps the Java shift from overflowing a `long`. |
| Jitter | 0.2, a uniform multiplier of `1.0 +/- ratio` | Ten clients dropped by one restart computing the same delay and retrying in one instant, a thundering herd that can knock a warming server back over. |
| Reset | attempt back to 0 on a successful connection (`notifyConnected()` calls `attempt.set(0)`; the Python loop sets `attempt = 0` on entering `async with connect(...)`) | A backoff schedule after a quick blip that carries over failures from an unrelated outage weeks ago. The counter tracks consecutive failures since the last success. |

{% include excalidraw.html file="10-reconnect-backoff" alt="A cycle of four states. CONNECTED moves to DISCONNECTED on any disconnect cause. DISCONNECTED moves to BACKOFF, which waits min(max, base*2^n) with jitter, then to RETRY ATTEMPT. A successful retry resets the attempt counter and returns to CONNECTED, and a failed retry returns to DISCONNECTED." caption="Figure 10.1: The reconnect cycle both clients implement: connected, dropped, backoff with jitter, retry, then success resets the counter or another lap." %}

## A fresh connector per attempt, and a broad catch

On Quarkus, `ReconnectingClient` injects `Instance<WebSocketConnector<HandlingEventClientEndpoint>>` and calls `connectors.get()` for every attempt. `WebSocketConnector` instances are not thread-safe and must not be reused across attempts, according to the WebSockets Next reference guide. Reuse works on the first connection and fails under reconnect churn.

On Python, the reconnect loop catches `Exception` broadly:

```python
except Exception as e:
    # Deliberately broad: a connection can fail in ways that are
    # NOT websockets.exceptions.ConnectionClosed or OSError, e.g. a
    # server mid-restart can accept the TCP connection, then drop it
    # before finishing the HTTP upgrade response, which the
    # `websockets` library surfaces as InvalidMessage/InvalidHandshake
    # (neither a ConnectionClosed nor an OSError subclass). Any
    # failure here (handshake, transport, timeout) should trigger
    # the same backoff-and-retry, so we catch Exception broadly and
    # only exempt CancelledError (caught above) so a real shutdown
    # still propagates.
    logger.info("disconnected: %s", e)
```

A narrower `except (ConnectionClosed, OSError)` reads as more disciplined, and it breaks on exactly the case reconnect exists for. During a `docker compose restart` there is a window where the TCP connection is accepted but the process goes down before the HTTP upgrade completes. The `websockets` library raises `InvalidMessage` or `InvalidHandshake`, neither of which subclasses `ConnectionClosed` or `OSError`. The exception escapes the loop, the reconnect task dies and the client never retries. The broad catch handles every handshake, transport and timeout failure with the same backoff, and the `CancelledError` re-raise one line above it lets a shutdown signal still propagate. The Java `connect()` already catches `Exception`, so it never had the narrow version to walk back.

## Backpressure: a bounded buffer with an explicit policy

Reconnect covers the socket going away. Backpressure covers the socket staying up while the server pushes faster than the consumer works. Both clients put a bounded queue between the code that reads frames and the code that processes them, and the policy for a full queue is a setting:

| | Quarkus | Python |
|---|---|---|
| Queue | `ArrayBlockingQueue<String>` sized by `client.buffer.capacity` | `asyncio.Queue(maxsize=...)` from `CLIENT_BUFFER_CAPACITY` |
| Producer | `onMessage` calls `EventBuffer.offer(message)` | `_producer` loop calls `_enqueue` |
| Consumer | a dedicated thread running `consumeLoop()` | the `_consume` task |
| Policy | `client.buffer.policy` | `CLIENT_BUFFER_POLICY` |
| Delay for demos | `client.consumer.delay-ms` | `CLIENT_CONSUMER_DELAY_S` |

The capacity defaults to 16 and the policy to `BLOCK` in both. The queue is the only thing producer and consumer share.

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
                Log.warnf("handling-events client: buffer full (capacity=%d): dropped oldest frame: %s",
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
            logger.warning("buffer full (capacity=%d): dropped oldest frame: %s", queue.maxsize, dropped)
        queue.put_nowait(message)
    else:
        # BLOCK (default): await room in the queue. This is the safe
        # default (no frame is ever lost) at the cost of throttling how
        # fast we pull new frames off the socket when the consumer is slow.
        await queue.put(message)
```

| Policy | Full queue | Cost | Use it for |
|---|---|---|---|
| `BLOCK` | `queue.put` suspends the producer until the consumer makes room. | A slow consumer throttles how fast the client reads. TCP's receive buffer then fills and the pressure reaches the server's send buffer, instead of data piling up unseen in the client. | Anything where every frame matters. Every `HandlingEvent` is a discrete fact about cargo movement. |
| `DROP_OLDEST` | The producer never blocks. It evicts the oldest buffered frame, logs a warning and enqueues the newest. | Frames evicted while the consumer is behind are lost. | Data where only the latest value matters, such as a price or a position, and an old value is wrong, not just stale. |

`BLOCK` does not fix a consumer that is permanently slower than the producer; it makes the imbalance visible as a reader that stops pulling frames. `DROP_OLDEST` is the wrong choice for a feed like handling events, where billing, customs or a dashboard needs every event, not only the latest.

Neither policy is correct in the abstract. The choice depends on whether a stale frame still carries value, so it is configuration and not a constant.

{% include excalidraw.html file="10-backpressure-policy" alt="The socket read loop enqueues into a bounded queue of capacity 16, and a consumer dequeues from it. When the queue is full, BLOCK makes the producer wait for room with no frame lost, and DROP_OLDEST evicts the oldest frame, logs a warning and enqueues the newest." caption="Figure 10.2: The bounded buffer between the socket and the consumer, and the two policies for a full queue." %}

## Why the consumer is a separate thread or task

The read loop (`HandlingEventClientEndpoint.onMessage`, `_producer`) never processes a frame. It calls `buffer.offer(message)` or `_enqueue` and returns. Processing happens on `EventBuffer`'s consumer thread or the `_consume` task.

That separation is what makes the policy meaningful. If the read loop processed each frame inline, the socket's read rate would be bounded by processing time with no queue to fill and no policy to choose, which is backpressure by accident. On Quarkus there is a second cost: `onMessage` runs on a Vert.x worker thread under WebSockets Next's default blocking execution model, and slow synchronous work there holds a worker from a shared, bounded pool. The queue turns that implicit coupling into one with a name and a size.

> **Decision**
>
> A client reconnects with exponential backoff, a cap and jitter, resets its attempt counter on success and catches connection failures broadly, because nothing else will restart a dropped outbound connection and a handshake can fail in ways `ConnectionClosed` and `OSError` do not cover. It buffers behind a bounded queue and picks `BLOCK` when no frame may be lost or `DROP_OLDEST` when only the newest matters. Stateless reconnect does not replay the gap: a consumer that cannot miss events needs a durable log to resume from an offset.

> **🤖 Explore with your agent**
>
> "In examples/part3-handling-events/clients/python/app/client.py, set CLIENT_BUFFER_CAPACITY=2, CLIENT_BUFFER_POLICY=drop_oldest and CLIENT_CONSUMER_DELAY_S=1, run the client against the Python server on port 8081 and report which of the three fixture frames (RECEIVE, LOAD, CUSTOMS) reach the consumer. Then switch to block and explain what changes at the socket."
>
> Check: the `drop_oldest` run logs a `buffer full` warning, and the `block` run logs `received RECEIVE`, `LOAD` and `CUSTOMS` in order.

## Build, run, observe

```bash
cd examples/part3-handling-events && ./verify.sh
```

The script starts the Python client against the Python server, waits for the full three-event sequence, restarts the server container with `docker compose -p part3-handling-events restart python`, and passes only when the client logs `reconnecting in` and then receives `CUSTOMS` a second time. It prints `PASS: ` on success. A representative client log across the restart:

```
INFO handling-events-client: connected
INFO handling-events-client: received CUSTOMS eventId=evt_01HZY3P3X8Z6F9S8D4Q1E2V7G0 bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
INFO handling-events-client: disconnected: server rejected WebSocket connection: HTTP 502
INFO handling-events-client: reconnecting in 0.57s (attempt 1)
INFO handling-events-client: connected
INFO handling-events-client: received CUSTOMS eventId=evt_01HZY3P3X8Z6F9S8D4Q1E2V7G0 bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
```

The `disconnected:` line is the broad catch handling a failed handshake during the restart. To watch `DROP_OLDEST` act, run the client with a small buffer and a slow consumer against a server that pushes the fixture on connect:

```bash
CLIENT_BUFFER_CAPACITY=2 CLIENT_BUFFER_POLICY=drop_oldest CLIENT_CONSUMER_DELAY_S=1 \
  uv run --project examples/part3-handling-events/clients/python python -m app.client
```

The log shows a `WARNING` line from `_enqueue` that begins `buffer full (capacity=2)`. The Quarkus client reads `CLIENT_BUFFER_CAPACITY`, `CLIENT_BUFFER_POLICY` and `CLIENT_CONSUMER_DELAY_MS` through `application.properties`, and `EventBuffer.offer` logs the same warning against either server.

- Set `CLIENT_BUFFER_POLICY=block` with the same capacity and delay: no frame is dropped and the client reads from the socket more slowly.
- Narrow the Python `except Exception` to `(ConnectionClosed, OSError)` and restart the server: a handshake that fails mid-restart can end the reconnect task, so the client stops retrying.

## For deeper coverage

- Michael T. Nygard, *Release It!, Second Edition* (Pragmatic Bookshelf, 2018): stability patterns for a struggling peer that synchronized retries would hammer, and a queue that must fail in a chosen way once it fills.
- Unmesh Joshi, *Patterns of Distributed Systems* (Addison-Wesley, 2023): the vocabulary behind retrying a connection with backoff and recognizing when client state no longer matches the server.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: the taxonomy a dropped connection and a stalled consumer both belong to.
- *Cloud Native Design Patterns*, "Stream Processing" chapter: bounded buffers and explicit backpressure policies for a producer that can outrun its consumer.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455): section 7.4's close codes, which a reconnect loop's exception handling has to interpret.
- [MDN WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API): the browser `onclose` and `onerror` events a client-side reconnect loop reacts to.
