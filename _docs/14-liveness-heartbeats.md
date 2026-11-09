---
title: "Liveness and Heartbeats"
order: 14
part: "Production Concerns"
description: "Detecting a dead connection before the application does, with ping/pong and a pong-tracked liveness sweep."
duration: "12 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why TCP can't tell you a WebSocket peer is gone, and what RFC 6455 ping and pong frames add.
- Show why `quarkus.http.idle-timeout` never trips for a silent peer when `auto-ping-interval` is on.
- Implement a pong-tracked liveness sweep: stamp the last pong per connection, check it from a scheduled bean.
- Size `liveness-timeout`, `auto-ping-interval` and `sweep-interval` so one late pong doesn't close a healthy connection.
- Read a liveness close correctly: the sweep requests `4408`, and `onClose` on a silent peer observes `1006`.

## Why this matters

A feed server assumes the peer is still there, still reading, and will say so when something breaks. That fails when the peer's machine loses power, a NAT drops its mapping, or a partition swallows packets in one direction. TCP can sit in that half-open state indefinitely. The first symptom is usually a backlog of events nobody reads, or a load balancer whose connection table fills with dead sockets.

Both stacks send protocol pings with one line of configuration. The hard part is deciding what a missing pong means, and on Quarkus the obvious configuration doesn't detect a silent peer at all.

{% include excalidraw.html file="14-idle-timeout-trap" alt="Two lanes. In the first, a silent peer never answers the server's ping, and each outbound ping resets the 40-second idle-timeout clock, so the connection looks healthy forever. In the second, the same peer never pongs, LAST_PONG_AT goes stale, and a scheduled sweep closes the connection with 4408 once the silence exceeds the liveness timeout." caption="Figure 14.1: The server's own ping resets its own idle clock, so idle-timeout never fires for a silent peer. A pong-tracked sweep does." %}

## Pattern: Heartbeat

### The problem

RFC 6455 builds a probe into the protocol: a ping frame, which the peer must answer with a pong carrying the same payload. Browsers, `websocat` and both reference clients answer at the transport level, with no application code. The server sends pings on a schedule with `quarkus.websockets-next.server.auto-ping-interval` on Quarkus and `ping_interval` and `ping_timeout` on `serve()` in Python.

On Quarkus, the config most people reach for next looks complete: turn on auto-ping, then set `quarkus.http.idle-timeout` so Vert.x tears down a quiet connection. It doesn't work. Vert.x resets the idle clock on any read or write, and the server's own outbound ping is a write. Every 20 seconds the server resets its own clock whether or not the peer has answered anything. A peer that went silent at the upgrade and a peer that answers every ping look identical to idle-timeout.

A raw TCP socket that completes the opening handshake and then sends nothing reproduces it. Against the Quarkus app with only auto-ping and idle-timeout, that socket stayed open well past the idle window. The same socket against the Python app closed.

### The solution

A **Heartbeat** requires a periodic answer from the peer within a bounded window, and closes the connection when the answer stops coming, rather than watching for any traffic at all.

Use it when:

- peers can disappear without a FIN (mobile clients, NAT, load balancers);
- a dead connection holds something worth freeing (a subscription, a session, a slot in a connection table);
- clients reconnect, so closing early shortens the outage.

### How Quarkus and Python model it

The ping half is configuration on both stacks:

{% include codetabs.html langs="Quarkus|Python" %}

```properties
quarkus.websockets-next.server.auto-ping-interval=20
```
```python
ping_interval = float(os.environ.get("WS_PING_INTERVAL_S", "20"))
ping_timeout = float(os.environ.get("WS_PING_TIMEOUT_S", "20"))
return serve(handler, host, port, ping_interval=ping_interval, ping_timeout=ping_timeout)
```

Quarkus then needs the pong half written down. `@OnOpen` stamps `LAST_PONG_AT` in the connection's `userData()` so a peer that never pongs still has a baseline, and `@OnPongMessage` moves it forward:

```java
    @OnPongMessage
    void onPongMessage(Buffer data) {
        connection.userData().put(LAST_PONG_AT, System.currentTimeMillis());
        Log.debugf("handling-events pong received bookingId=%s", connection.pathParam("bookingId"));
    }
```

The check lives in a separate `@ApplicationScoped` bean, `HeartbeatLivenessSweep`. A `@Scheduled` method runs on its own worker thread with no WebSocket session context, so it reads every open connection from the `OpenConnections` registry instead, scoped to this endpoint by `findByEndpointId`. Injecting a `WebSocketConnection` there would resolve to whatever connection is active for the current request, which is meaningless on a scheduler thread. A connection the sweep finds overdue is marked and closed:

```java
    @Scheduled(every = "${example.heartbeat.sweep-interval:5s}", concurrentExecution = ConcurrentExecution.SKIP)
    void sweep() {
        Instant now = Instant.now();
        for (WebSocketConnection connection : openConnections.findByEndpointId(HandlingEventConnectionWebSocket.ENDPOINT_ID)) {
            if (!connection.isOpen() || Boolean.TRUE.equals(connection.userData().get(CLOSE_REQUESTED))) {
                continue;
            }
            Instant lastSeen = lastSeen(connection);
            Duration silentFor = Duration.between(lastSeen, now);
            if (silentFor.compareTo(livenessTimeout) > 0) {
                String bookingId = connection.pathParam("bookingId");
                Log.warnf("handling-events connection bookingId=%s silent for %s (>%s): requesting close as dead (liveness timeout)",
                        bookingId, silentFor, livenessTimeout);
                connection.userData().put(CLOSE_REQUESTED, true);
                connection.close(new CloseReason(CloseCodes.LIVENESS_TIMEOUT, "no pong received within the liveness window"))
                        .subscribe().with(
                                v -> Log.debugf("handling-events connection %s close completed after liveness timeout", connection.id()),
                                failure -> Log.errorf(failure, "error closing unresponsive connection %s during liveness sweep", connection.id()));
            }
        }
    }
```

`CLOSE_REQUESTED` stops later ticks from re-requesting a close while the first one drains. The close is subscribed to rather than awaited, because blocking the sweep thread for up to ten seconds per dead connection would stall the check on every other connection. `concurrentExecution = SKIP` keeps overlapping runs from piling up.

Python needs no application code. `websockets` tracks whether each ping got its own pong, which is the distinction the Quarkus sweep rebuilds by hand. The two stacks agree on when a silent peer is closed and disagree on the code: Quarkus closes with `4408` (`CloseCodes.LIVENESS_TIMEOUT`), and the library closes with its own `1011`.

## A close request isn't a close

Closing is a two-way handshake: the server sends a close frame and waits for the peer's close frame before tearing down TCP. A peer the sweep just proved unresponsive won't send one. Vert.x gives up after a fixed ten seconds (`HttpServerOptions.DEFAULT_WEBSOCKET_CLOSING_TIMEOUT`, not a Quarkus property) and terminates the connection.

So `onClose` on the endpoint observes `1006`, abnormal closure, and not `4408`. The `4408` frame was sent but never acknowledged, and a close code only reaches a peer that is still reading. Close-code metrics taken in `onClose` count liveness closes under `1006`.

{% include excalidraw.html file="14-pong-sweep-timeline" alt="A timeline from the last pong through two unanswered pings, the sweep tick that finds silence over the liveness timeout, the 4408 close request, and the ten-second closing-handshake grace that ends with TCP forced closed and onClose seeing 1006." caption="Figure 14.2: From last pong to a closed socket: detection at the liveness timeout, then up to ten seconds of closing grace before onClose sees 1006." %}

## Choosing the windows

| Setting | Default | Role |
|---|---|---|
| `auto-ping-interval` | 20s | How often the server pings |
| `example.heartbeat.liveness-timeout` | 45s | Silence tolerated: two ping intervals plus 5s grace |
| `example.heartbeat.sweep-interval` | 5s | How often the sweep checks; adds at most one interval to detection time |
| Vert.x closing grace | 10s | Fixed; not configurable |
| `quarkus.http.idle-timeout` | 40s | Unrelated backstop; does not detect a silent peer |

The liveness timeout tolerates two consecutive missed pongs, not one. A single late pong from a GC pause or a busy event loop is not proof of death, and a timeout of exactly one interval closes healthy connections the first time a client hiccups. The cost is that a dead peer stays undetected roughly twice as long. Worst-case time to a closed socket on Quarkus is `liveness-timeout + sweep-interval + 10s`.

Python has one fewer knob: `ping_timeout` plays the role of the liveness timeout, measured from the latest ping, and the library checks the deadline in its own event loop, so there is no sweep cadence to add.

> **Decision**
>
> Protocol ping and pong is a probe, not a detector. Detect a dead peer by requiring a pong within a bounded window. On Quarkus that means a pong-tracked sweep (stamp on open and on pong, close with `4408` after two missed intervals), never `auto-ping-interval` plus `idle-timeout` alone. On Python, set `ping_interval` and `ping_timeout` and let the library close with `1011`. Expect `1006` in `onClose` for a silent peer.

> **🤖 Explore with your agent**
>
> "In examples/part4-connection, add a second Quarkus endpoint that uses the same pong-tracked liveness rule as HandlingEventConnectionWebSocket: stamp LAST_PONG_AT in @OnOpen and @OnPongMessage and let HeartbeatLivenessSweep close it with 4408 after example.heartbeat.liveness-timeout. Do not rely on quarkus.http.idle-timeout, and make the sweep skip connections that already have CLOSE_REQUESTED set."
>
> Check: the sweep iterates both endpoint ids, and a raw socket that completes the upgrade and sends nothing is closed within liveness-timeout + sweep-interval + about 10s.

## Build, run, observe

```bash
bash examples/part4-connection/verify.sh
```

The script starts one-off containers for both stacks on ports 18082 (Quarkus) and 18092 (Python) with the windows shrunk to a few seconds: auto-ping 2s, liveness timeout 5s and sweep 1s on Quarkus (`QUARKUS_WEBSOCKETS_NEXT_SERVER_AUTO_PING_INTERVAL`, `EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT`, `EXAMPLE_HEARTBEAT_SWEEP_INTERVAL`), and `WS_PING_INTERVAL_S=2`, `WS_PING_TIMEOUT_S=3` on Python. A client built on a WebSocket library answers pings automatically, so the probe is a raw TCP socket that does the opening handshake, confirms the `101`, then sends nothing. It passes when each server closes that socket within 25 seconds. A recorded run closed Quarkus after 15.8s and Python after 3.4s: Quarkus pays the sweep and the ten-second grace, Python only `ping_timeout`.

Experiments:

- Shrink `EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT` and `EXAMPLE_HEARTBEAT_SWEEP_INTERVAL` and watch the close time move with their sum plus the fixed ten seconds.
- Remove `HeartbeatLivenessSweep` and rerun: the Quarkus probe reports `STILL_OPEN` past the idle-timeout window, which is the trap in Figure 14.1.
- Raise `WS_PING_TIMEOUT_S` on the Python server and the closing time follows it.

## For deeper coverage

- Unmesh Joshi, *Patterns of Distributed Systems* (Addison-Wesley, 2023): the HeartBeat pattern behind the pong-tracked sweep.
- Michael T. Nygard, *Release It!, Second Edition* (Pragmatic Bookshelf, 2018): timing out a connection that looks alive but isn't, and the cost of guessing the window wrong in either direction.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: the taxonomy a silent, half-open connection falls into.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455) section 5.5.2 and 5.5.3: the ping and pong control frames.
- [Quarkus WebSockets Next reference guide](https://quarkus.io/guides/websockets-next-reference): `auto-ping-interval` and the ping/pong configuration.
