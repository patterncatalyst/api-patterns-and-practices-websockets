---
title: "Liveness and Heartbeats"
order: 14
part: "Production Concerns"
description: "Detecting a dead connection before the application does, with ping/pong and application-level heartbeats."
duration: "16 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why TCP's own failure signals can't be trusted to detect a dead WebSocket peer, and what RFC 6455's ping/pong control frames add at the protocol level.
- Diagnose why `quarkus.http.idle-timeout` alone never trips for a silent peer, because the server's own outbound `auto-ping-interval` ping resets the same idle clock it's supposed to guard.
- Implement a pong-tracked liveness sweep (`@OnOpen`/`@OnPongMessage` stamping `LAST_PONG_AT`, checked by a separate `@Scheduled` `HeartbeatLivenessSweep` bean reading `OpenConnections`) instead of relying on transport-level idle-timeout.
- Size `liveness-timeout`, `auto-ping-interval`, and `sweep-interval` so a detector tolerates one missed pong without false-positiving on a healthy connection.
- Read a liveness-triggered close correctly: the sweep requests `CloseCodes.LIVENESS_TIMEOUT` (`4408`), but a silent peer's own `onClose` observes `1006` once Vert.x's closing-handshake grace expires.

## Why this matters

The backpressure guard and the error taxonomy both assume the thing they're guarding is still there: a connection that's open, a peer that's reading, a socket that will eventually tell you if something goes wrong. Liveness is what happens when that assumption fails: the peer stops reading, stops answering, stops doing anything at all, and neither TCP nor the application layer notices right away. `examples/part4-connection` is both servers this part's production-concerns example builds, `HandlingEventConnectionWebSocket` on the Quarkus side, `ws_server.py`'s `handler` on the Python side, and this chapter layers one more concern onto both: detecting a dead peer before the application or the operator notices some other way, like a backlog of events nobody's reading.

The interesting part of this chapter isn't the ping/pong mechanics themselves: WebSockets Next and the `websockets` library both send pings automatically, no application code required for that half. The obvious way to wire up liveness detection in Quarkus, turn on auto-ping, set an HTTP idle-timeout, done, doesn't work, for a reason that only shows up once you trace exactly what resets an idle-timeout clock. `HeartbeatLivenessSweep.java`'s class Javadoc puts it directly: a silent peer can stay "not idle" indefinitely, confirmed live against `verify.sh`'s own raw, non-ponging socket probe. What follows is the trap, the pong-tracked fix, and the two-stack comparison once the Python sibling's answer, the `websockets` library's own ping-aware keepalive, is on the table alongside it.

## Why TCP doesn't tell you the peer is gone

A WebSocket connection sits on top of a long-lived TCP connection, and TCP's own failure signals are weaker than they look for this purpose. If a peer's process crashes cleanly, or the peer sends a FIN, the OS on this end eventually sees it and the socket read fails. But if the peer's machine loses power, a NAT device silently drops the mapping, or a network partition swallows packets in one direction without tearing down the connection, TCP can sit there indefinitely believing the connection is still open. This is the textbook "half-open connection" problem, and it's exactly why both the WebSocket protocol (RFC 6455) and application-level heartbeat patterns exist at all: something has to actively probe the peer, because passively waiting for TCP to notice isn't a bound anyone can rely on.

RFC 6455 builds a probe into the protocol itself: a ping frame, which a conformant endpoint must answer with a pong frame carrying the same payload, entirely at the protocol level: no application code sees either frame unless it asks to. WebSockets Next exposes this as `quarkus.websockets-next.server.auto-ping-interval`; the `websockets` library exposes the identical idea as `ping_interval`/`ping_timeout` passed to `serve()`. Either way, the pattern is the same: the server sends a ping on a schedule, and a spec-compliant client (a browser, `websocat`, either reference client this site builds) answers automatically at the transport level. The question this chapter has to answer isn't "how do you send a ping" (that part is one config line on both stacks); it's what you do with whether a pong arrived or not, and that's where the two stacks take different paths.

## The idle-timeout trap: a ping your own server answers for you

The Quarkus side of `examples/part4-connection` starts from the config most people reach for first, because on paper it sounds complete: turn on `auto-ping-interval` so pings go out, and set `quarkus.http.idle-timeout` so Vert.x tears down any connection that's gone quiet. `application.properties` sets both (`auto-ping-interval=20` and `idle-timeout=40s`) and the comment directly above the idle-timeout line names the problem before it becomes one: "This is NOT what detects a dead peer on this channel." Vert.x's idle-timeout resets on *any* read or write activity on the connection, and the server's own outbound ping is write activity on that same connection. Every 20 seconds, whether or not the peer has answered a single ping since the connection opened, the server itself resets its own idle clock by sending the next one. A peer that silently stopped responding the instant it connected and a peer that's answering every ping look identical to the idle-timeout mechanism, because idle-timeout was never watching for a pong: it was watching for *any* traffic, and the server's own outbound pings guarantee there always is some.

This isn't a hypothetical concern raised in review; it's a confirmed live result. `verify.sh`'s `raw_silent_client_close_wait` probe hand-writes a WebSocket opening handshake over a raw TCP socket, no WebSocket client library at all, confirms the 101 upgrade response, and then sends absolutely nothing else: no pong, no close, nothing, for the rest of the probe window. Before `HeartbeatLivenessSweep` existed, that probe against the Quarkus app stayed open well past the configured idle-timeout window, while the identical probe against the Python app (which does implement pong-aware detection, covered below) correctly closed. Two servers, the same raw non-ponging client, two different outcomes: the gap between them is precisely the idle-timeout trap, caught by an automated test rather than left for an operator to discover in production when a load balancer's connection table fills up with sockets nothing is using.

{% include excalidraw.html file="14-idle-timeout-trap" alt="Two horizontal lanes. Top lane, labeled BROKEN: SILENT PEER (upgrade completes, then never answers a ping) connects to SERVER auto-ping (sends PING every auto-ping-interval, 20s) via an arrow labeled 'stays silent', which connects via an arrow labeled 'write activity' to idle-timeout clock (resets on this WRITE, read OR write both count), which loops to a box below it labeled '40s idle-timeout never expires, connection looks healthy forever' via an amber arrow labeled 'clock reset, again and again'. Bottom lane, labeled WORKS: SILENT PEER (same peer, never pongs) connects via 'never pongs' to LAST_PONG_AT (stamped on open, never updated again, stays stale), which connects via 'sweep reads userData()' to HeartbeatLivenessSweep (ticks every sweep-interval, 5s, compares now - LAST_PONG_AT), which drops via an amber arrow labeled 'silentFor > timeout' to a box reading '>livenessTimeout (45s), close(4408) requested'. Caption: idle-timeout resets on the server's own outbound ping; a silent peer never trips it. Only an explicit pong-tracked sweep does." caption="Figure 14.1: the idle-timeout trap (the server's own ping keeps resetting its own idle clock) versus the pong-tracked sweep that detects a silent peer." %}

## The fix: track pongs explicitly, sweep for silence on a schedule

The fix in `HandlingEventConnectionWebSocket` and `HeartbeatLivenessSweep` replaces "has this connection seen any traffic" with the narrower, correct question: "has this specific connection's peer answered a ping recently." That requires two pieces working together, because the data (when did this connection last pong) and the check (is any connection now overdue) live naturally in different places.

`HandlingEventConnectionWebSocket` owns the data. `@OnOpen` stamps a `LAST_PONG_AT` timestamp (epoch millis, stored via `WebSocketConnection#userData()`) the moment the connection opens, specifically so a peer that never pongs even once still has a baseline to measure silence from, rather than `HeartbeatLivenessSweep` finding no entry at all and not knowing what to do with it. `@OnPongMessage` stamps the identical key every time a pong arrives, which is the only place `LAST_PONG_AT` moves forward after that initial stamp: a healthy, spec-compliant client answers the protocol-level ping automatically and lands here every `auto-ping-interval`; a peer that stops answering stops updating this timestamp.

`HeartbeatLivenessSweep` owns the check, and it lives in its own `@ApplicationScoped` bean rather than as a method on the endpoint, because the two run in fundamentally different execution contexts. The endpoint class only ever runs invoked by Quarkus, for one connection at a time, while that connection's `@SessionScoped` `WebSocketConnection` context is active. A liveness sweep is the opposite shape: it needs its own schedule, it needs to see every open connection on the endpoint at once, and it needs to keep running regardless of whether any particular connection's session context happens to be active at that instant. A `@Scheduled` method runs on its own worker thread with no WebSocket session context at all, so the sweep reads live connections straight off the injected `OpenConnections` registry (scoped to this endpoint via `OpenConnections#findByEndpointId(HandlingEventConnectionWebSocket.ENDPOINT_ID)`) rather than resolving a `WebSocketConnection` via `@Inject`, which would bind to whatever connection happens to be active for the current request and be meaningless on a scheduler thread.

{% include codetabs.html langs="Quarkus|Python" %}

```java
# application.properties — Ch14 heartbeat configuration
quarkus.websockets-next.server.auto-ping-interval=20
quarkus.http.idle-timeout=40s

example.heartbeat.liveness-timeout=45s
example.heartbeat.sweep-interval=5s
```
```python
# app/ws_server.py — create_server(): Ch14 heartbeat configuration
ping_interval = float(os.environ.get("WS_PING_INTERVAL_S", "20"))
ping_timeout = float(os.environ.get("WS_PING_TIMEOUT_S", "20"))
return serve(handler, host, port, ping_interval=ping_interval, ping_timeout=ping_timeout)
```

Both sides expose their windows as configuration rather than constants: `QUARKUS_WEBSOCKETS_NEXT_SERVER_AUTO_PING_INTERVAL`, `EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT`, `EXAMPLE_HEARTBEAT_SWEEP_INTERVAL` on the Quarkus side; `WS_PING_INTERVAL_S`/`WS_PING_TIMEOUT_S` on the Python side, which is what lets `verify.sh` shrink production-sized windows down to a few seconds for a deterministic test rather than waiting out 45-second defaults in CI.

The sweep itself is a single `@Scheduled` loop, and the actual detection logic in `HeartbeatLivenessSweep#sweep` is short enough to read in full:

{% include codetabs.html langs="Quarkus|Python" %}

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
            connection.userData().put(CLOSE_REQUESTED, true);
            connection.close(new CloseReason(CloseCodes.LIVENESS_TIMEOUT, "no pong received within the liveness window"))
                    .subscribe().with(
                            v -> {},
                            failure -> Log.errorf(failure, "error closing unresponsive connection %s during liveness sweep", connection.id()));
        }
    }
}
```
```python
# No equivalent method exists in ws_server.py. create_server's docstring
# states the division of responsibility directly: "ping_interval/ping_timeout
# are handed straight to the `websockets` library, which sends a ping every
# ping_interval seconds and closes the connection if no pong arrives within
# ping_timeout seconds of that ping — no code in this module implements
# liveness detection; it is entirely the library's responsibility."
```

Two details in the Java sweep are easy to misread as incidental, but each one changes behavior under real load. `CLOSE_REQUESTED` exists because closing a connection isn't instant (the next section covers exactly why), and without that flag every subsequent tick of a 5-second sweep would re-request a close on the same connection that's still draining from the previous tick's request. And `connection.close(...)` is subscribed to, not awaited: blocking the sweep's thread for up to ten seconds per dead connection would stall every other connection this same run still needs to check, which defeats the point of a sweep that's supposed to scan all open connections on a tight schedule.

## A close request isn't a close: the ten-second grace and the 1006 you'll see

Closing a WebSocket is itself a two-way handshake, not a single packet: the server sends a close frame and then waits for the peer to send its own close frame back before the TCP connection tears down. This is where the sweep's own logic runs into an unavoidable wrinkle: a peer the sweep has just proven isn't responding to anything isn't going to send that close acknowledgment either. Vert.x's answer is a fallback timer: `HttpServerOptions.DEFAULT_WEBSOCKET_CLOSING_TIMEOUT`, ten seconds, not currently exposed as a Quarkus config property, after which Vert.x gives up waiting for the acknowledgment and forcibly terminates the TCP connection anyway.

The behavior this produces is confirmed live, and it is not what a quick read of the code would predict: `HandlingEventConnectionWebSocket#onClose` observes the connection's own final `CloseReason` as code `1006` (abnormal closure) in this case, not `CloseCodes.LIVENESS_TIMEOUT` (4408), the code the sweep requested. The 4408 close frame the sweep sent never completed its handshake, because the peer that triggered it by going silent stays silent through its own teardown; what `onClose` sees instead is Vert.x's own abnormal-closure code for a connection it had to force shut. This is standard WebSocket protocol behavior for an unresponsive peer: a close code can only reach a peer that's still reading, and by definition this one isn't. Anyone instrumenting this endpoint's `onClose` for close-code metrics needs to know that a liveness-triggered closure shows up as 1006 at that observation point, with 4408 only ever visible in the close frame the server attempted to send, not in what the dead peer's side (or this endpoint's own `onClose`) ultimately records.

{% include excalidraw.html file="14-pong-sweep-timeline" alt="A left-to-right timeline of five boxes connected by arrows. T+0s: last pong received, LAST_PONG_AT stamped. Arrow to T+20s / T+40s: server PINGs sent, peer never answers. Arrow labeled '2 missed pongs' to T+45s: sweep tick, silentFor > livenessTimeout. Arrow labeled '4408 selected' to T+45s: close(4408) requested, CLOSE_REQUESTED marked. Arrow labeled 'close frame sent' to T+45s..~55s: Vert.x closing-handshake grace, peer never ACKs. A downward amber arrow labeled '~10s with no reply' leads to a final box below: T+~55s: TCP forced closed; onClose sees code 1006. Caption: verify.sh's Step 6 shrinks all three knobs for a fast test (~16s observed live, not ~55s), the sequence of events is identical, only the durations shrink." caption="Figure 14.2: the real timeline from last pong to the TCP socket closing: detection at the liveness timeout, then up to ten more seconds of closing-handshake grace before onClose observes 1006." %}

## The Python side: liveness as a library default, not application code

The Python server's answer to this entire chapter is a config comparison, not a parallel implementation. `create_server`'s docstring is explicit that no custom liveness code exists in that module at all: `ping_interval`/`ping_timeout` are handed straight to `websockets.asyncio.server.serve()`, which sends a ping every `ping_interval` seconds and closes the connection itself if no pong arrives within `ping_timeout` seconds of that specific ping. There is no idle-timeout layer to accidentally defeat here, because the library's keepalive mechanism was built pong-aware from the start: it tracks whether *this* ping got *its* pong, not whether *any* traffic crossed the wire recently, which is exactly the distinction the Quarkus side had to build by hand.

That difference in where the logic lives shows up directly in the close code a silent peer gets. `CloseCodes.LIVENESS_TIMEOUT`'s own Javadoc documents this asymmetry directly rather than leaving it as an unexplained gap: the Python sibling does not close with `4408`. Its keepalive failure closes with the library's own hardcoded `1011` (an RFC 6455 "unexpected condition" code, reused here for "ping went unanswered"), and wrapping that default to emit a matching app-range code was out of scope for this example. The two stacks agree on *when* a silent peer gets closed, within a bounded, configurable window, and disagree on the exact numeric close code a client sees, which is exactly the kind of cross-stack detail a polyglot deployment has to document rather than assume away; `README.md`'s close-code table spells it out for anyone integrating against either server.

## Choosing the windows: how three numbers have to agree

None of this works with arbitrarily chosen numbers; the ping interval, the liveness timeout, and (on the Quarkus side) the sweep interval have to agree with each other or the detector either false-positives on a healthy connection or takes much longer than intended to notice a dead one. `HeartbeatLivenessSweep`'s `livenessTimeout` field documents the reasoning behind its own default directly: `45s` = `auto-ping-interval` (20s) × 2 + 5s grace, a "missed two consecutive pongs" window, not "missed one." Sizing the liveness timeout to exactly one ping interval would treat a single delayed pong, a momentary GC pause, a busy event loop, one slow tick under load, as proof of death, which is a false positive waiting to close a perfectly healthy connection the first time anything on the client side hiccups for a beat. Requiring two consecutive misses before acting is the cheap insurance against that, at the cost of roughly doubling how long a dead peer stays undetected: a trade-off made through a named config property, rather than picking either extreme by accident.

The sweep interval is the other knob, and it answers a narrower question: how much delay is acceptable between a connection crossing the liveness threshold and the sweep noticing. `example.heartbeat.sweep-interval` defaults to `5s`, far finer-grained than the 45-second `livenessTimeout` it enforces: fine enough that the sweep's own polling cadence adds at most one interval's worth of slop to the detection time, without running so often that scanning every open connection every tick becomes its own cost at scale. The closing-handshake grace (Vert.x's ~10s) is the one number in this chapter that isn't tunable via a Quarkus property at all; it's a hard floor on how long a connection can sit in a neither-open-nor-closed state after a close is requested, which is why `verify.sh`'s Step 6 budgets its wait for `liveness-timeout + sweep-interval + ~10s`, not just the first two. The same reasoning applies to the Python side's `ping_interval`/`ping_timeout` pair, just with one fewer independent knob: `ping_timeout` plays the role `livenessTimeout` plays on the Quarkus side, measured from the most recent ping rather than from the most recent pong, with no separate sweep cadence to add slop because the library's own event loop checks the deadline directly.

## On the wire

`verify.sh`'s Step 6 is where this chapter's claims about both stacks stop being Javadoc and docstrings and become something that has to happen for the script to print `PASS`. It can't use a real WebSocket client to prove a server detects silence, because a spec-compliant client (`websocat` included, and the `websockets` library used everywhere else in this script) answers pings automatically at the protocol level, which means no ordinary client can ever manufacture a dead peer to test against. Instead, `raw_silent_client_close_wait` speaks raw HTTP and TCP directly with Python's stdlib `socket` module: it hand-writes the WebSocket opening handshake, confirms the `101` response, and from that point on sends nothing else, no pong, no close frame, for the rest of the probe, discarding (unparsed) any frame the server sends in the meantime. It tracks one cumulative deadline across the whole wait rather than resetting a per-call socket timeout on every `recv()`, specifically because this channel's own ping frames would otherwise look like activity and reset a naive timeout into running forever.

Step 6 runs this probe against one-off containers of both stacks with their heartbeat windows forced down to a few seconds (`QUARKUS_WEBSOCKETS_NEXT_SERVER_AUTO_PING_INTERVAL=2`, `EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT=5s`, `EXAMPLE_HEARTBEAT_SWEEP_INTERVAL=1s` on the Quarkus side; `WS_PING_INTERVAL_S=2`, `WS_PING_TIMEOUT_S=3` on the Python side) and asserts `CLOSED` (not `STILL_OPEN`) within a 25-second budget on each. The comment sizing that budget states the real math behind it: `EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT` (5s) plus `EXAMPLE_HEARTBEAT_SWEEP_INTERVAL` (1s, worst case) for the sweep to detect and request the close, plus Vert.x's own ~10s closing-handshake grace before it gives up waiting for an acknowledgment the silent peer will, by construction, never send, "~16s observed live; 25s leaves comfortable margin for a slower CI host."

Run it yourself from the repo root:

```bash
bash examples/part4-connection/verify.sh
```

Both assertions read the same shape of result either stack produces:

```
lib.sh: quarkus heartbeat probe result: CLOSED:15.8
=== Step 6: assert_eq "CLOSED" "CLOSED" "quarkus heartbeat: silent peer closed within 25s"
lib.sh: python heartbeat probe result: CLOSED:3.4
=== Step 6: assert_eq "CLOSED" "CLOSED" "python heartbeat: silent peer closed within 25s"
```

The gap between the two `CLOSED` timings is the whole chapter in two numbers. The Python probe closes in a few seconds because `ping_timeout` (3s) alone is the detector: one missed ping's deadline, and the library's own event loop tears the connection down. The Quarkus probe takes roughly `liveness-timeout` (5s, forced) + up to one `sweep-interval` (1s) + Vert.x's fixed ~10s closing-handshake grace, because the sweep's own close request still has to go through that same two-way teardown this chapter covered above: a real, structural difference in how long each stack's detector needs, not a performance regression in either one. Before `HeartbeatLivenessSweep` existed, the Quarkus side of this same probe reported `STILL_OPEN` well past its idle-timeout window; both stacks now close a silent peer within their configured budget, which is the thing Step 6 exists to prove on every run rather than leaving as a claim in a comment.

## Where this goes next

This chapter closed the gap between "the connection object still exists" and "the peer on the other end is there," not with a single universal mechanism, but with two legitimately different answers that happen to agree on the outcome: Quarkus needs an explicit pong-tracked sweep because its transport-level idle-timeout can't tell a healthy connection from one whose own outbound pings are propping open a dead one, while Python's `websockets` library bakes pong-awareness directly into its keepalive and needs no application code at all. The reconnect loop built earlier is the direct beneficiary of this chapter's work on the client side of the wire: a client that notices its connection died sooner reconnects sooner, and liveness detection on the server is what shortens how long a half-open connection sits there looking alive before anything, server or client, does something about it. Stateless reconnect handling picks up the constraint already disclosed on the client side as its own formal topic, and a Kafka-backed feed is where a reconnecting client resumes from its last acknowledged offset instead of accepting whatever gap a disconnect, detected quickly or not, left behind. JWT auth and this chapter's heartbeat sweep also share one structural lesson worth carrying forward: both close reasons collapse to a specific, named close code (`AUTH_FAILURE`, `LIVENESS_TIMEOUT`) rather than letting an ambiguous RFC 6455 code or a bare TCP reset stand in for "here's specifically why this connection ended."

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Protocol ping/pong is a probe, not a liveness detector by itself: what you do with the answer is what detects a dead peer. On Quarkus, <code>quarkus.websockets-next.server.auto-ping-interval</code> plus <code>quarkus.http.idle-timeout</code> looks complete but is not: idle-timeout resets on any read OR write, and the server's own outbound ping is write activity on the same connection, so a peer that never answers a single ping never trips it, confirmed live against a raw, non-ponging socket probe before the fix. The actual detector is <code>HeartbeatLivenessSweep</code>: <code>@OnOpen</code>/<code>@OnPongMessage</code> stamp a per-connection <code>LAST_PONG_AT</code> timestamp, and a separate <code>@Scheduled</code> bean sweeps every open connection on its own schedule, closing (<code>4408</code>) any connection whose last pong is older than a configured <code>liveness-timeout</code> (default: two missed pongs' worth, not one). That close isn't instant: Vert.x's ~10s closing-handshake grace elapses first, because a peer proven unresponsive won't acknowledge its own close either, and <code>@OnClose</code> ultimately observes <code>1006</code>, not <code>4408</code>, once that grace expires. The Python sibling needs none of this application code: the <code>websockets</code> library's own <code>ping_interval</code>/<code>ping_timeout</code> keepalive is pong-aware by construction, closing with its own hardcoded <code>1011</code> instead. Both stacks now close a silent peer within their configured window, proven live in <code>verify.sh</code>'s Step 6, not just asserted in comments, but they do not agree on the exact close code, a documented cross-stack difference by design.</p></div>

## For deeper coverage

- Unmesh Joshi, *Patterns of Distributed Systems* (Addison-Wesley, 2023): the HeartBeat pattern behind this chapter's pong-tracked sweep: detect a failed peer by requiring a periodic signal within a bounded window, not by watching for any traffic at all.
- Michael T. Nygard, *Release It!, Second Edition* (Pragmatic Bookshelf, 2018): the stability-pattern reasoning behind timing out a connection that looks alive but isn't, and the cost of guessing that window wrong in either direction.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: the broader taxonomy a silent, half-open connection falls into.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455) §5.5.2–5.5.3: the ping and pong control frame definitions this chapter's sweep is built on top of.
- [Quarkus WebSockets Next reference guide](https://quarkus.io/guides/websockets-next-reference): `auto-ping-interval` and the ping/pong configuration both stacks' heartbeat windows are set against.
