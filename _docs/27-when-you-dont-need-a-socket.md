---
title: "When You Don't Need a Socket"
order: 27
part: "The Bigger Picture"
description: "Recognizing when a WebSocket is the wrong tool, and what to reach for instead."
duration: "18 min read"
---

## Learning objectives

By the end of this chapter you can:

- Separate the design-time question (which transport fits a new interaction) from the operating question (what a socket costs once it carries production traffic).
- Itemize the operational burden a WebSocket adds, using the reconnect, liveness, backpressure, backplane, auth, tracing and deployment work in the examples as receipts.
- Map a scenario to one of six alternatives: Server-Sent Events, long-polling, webhooks, gRPC server-streaming, plain request/response, and a message broker.
- Recognize the signals that mean a socket already in production should migrate.
- Rule out HTTP/2 server push for browser fan-out.

## Why this matters

The transport decision framework resolved the booking page's handling-event feed to a WebSocket. The same framework run against a different interaction often resolves to something cheaper. A team that has built the reconnect, liveness, backpressure and backplane machinery for one feed will be tempted to reuse the socket for everything. The transport decision answers which transport fits a new interaction before any code exists. The questions here come after: what a socket already in production costs, and whether its interaction still belongs on one. The answer for the handling-event feed stays a socket, because it needs duplex, low-latency delivery.

## The cost of a socket you didn't need

Each item is a cost the examples paid to keep a long-lived, full-duplex connection correct and operable.

**Reconnection is application code.** In `examples/part4-backplane`, the default `StatelessBackplane` fans out to whoever is subscribed right now and keeps nothing. A client that disconnects, misses an event and reconnects with `?afterEventId=<last seen>` never gets the gap event. Closing the gap took a second mode: a Kafka-backed backplane with its own topic, retention and replay-and-dedup logic on both stacks. A long-poll client or webhook receiver has no gap to resume across, because each delivery is a complete, bounded unit.

**Liveness needs its own clock.** Vert.x's idle timeout resets on any read or write, and the server's own ping is a write, so a silent peer and a healthy one look the same to an idle timer. In `examples/part4-connection`, Quarkus tracks `LAST_PONG_AT` per connection, stamped only by a real pong, and a scheduled sweep closes stale ones with `4408`. SSE and gRPC streams ride HTTP/2 connections that answer liveness in their own way; webhooks and long-polls never hold a connection open between messages, so they never ask whether anyone is still listening.

**Backpressure is a hand-rolled guard.** A raw WebSocket gives the application only TCP flow control. `OutboundBackpressureGuard` (Quarkus) and `OutboundQueue` (Python) decide whether to drop, buffer or close a slow client, and a tripped guard closes with `4290`, a code specific to this project. One sharp edge: `OUTBOUND_QUEUE_MAXSIZE<=0` means unbounded on Python's `asyncio.Queue`, while the Quarkus guard trips on `pending >= maxPendingSends`, so the same-looking setting means opposite things on the two stacks. gRPC server-streaming gets flow control from HTTP/2 windows at no extra code; long-polls and webhooks hold nothing open long enough to need it.

**Fan-out needs a backplane as well as sticky routing.** A load balancer doesn't move a long-lived connection mid-life, and an event injected on instance B must reach the client on instance A. The cross-instance check in `part4-backplane` (inject through B, find the delivering line in A's own log) shows that stickiness alone can't solve this. A webhook sender calls whichever endpoint the receiver registered, and a stateless call has no "which instance holds the connection" question.

**Browser auth is forced into the URL.** The browser `WebSocket` constructor can't set an `Authorization` header, so the token travels as `?token=` and lands in access logs, history and proxy traces. `part4-connection` accepts that with a short token TTL and `wss://`, and collapses all four token failures to close code `1008` so a prober can't learn which check failed. SSE and long-polling use ordinary requests that carry a normal header on every call.

**Tracing is hand-written.** No `opentelemetry-instrumentation-websockets` package exists and the `websockets` library has no OTel hook. `part6-observability` wraps the Python connection in a manual `ws.handling-events.connection` span; Quarkus traces the HTTP upgrade automatically but needs an added `@WithSpan` for connection-scoped work. The same Python service's FastAPI routes are traced with zero code.

**Deployment needs longer clocks and ordering.** Ingress-nginx raises `proxy-read-timeout` and `proxy-send-timeout` past 60 seconds so an idle socket survives; OpenShift needs `haproxy.router.openshift.io/timeout: "3600s"` on each Route. The always-wired Quarkus Kafka channels also crash the app at startup if the bootstrap host doesn't resolve, so `scripts/install-strimzi.sh` blocks on Kafka `Ready` before the apps roll out. A plain REST endpoint has no idle timeout to raise and no dependency it must wait for.

## The alternatives

| Reach for | When | What it saves | What it costs |
| --- | --- | --- | --- |
| Server-Sent Events | Only the server sends and the receiver is a browser tab | `EventSource` reconnects natively and sends `Last-Event-ID` for resume; no duplex handshake, ping/pong or backpressure guard | One open HTTP response per client still has to be counted |
| Long-polling | The path buffers or truncates long-lived responses, such as some corporate egress proxies | Degrades to plain request/response; needs nothing beyond HTTP | A full request cycle per update, wasteful at high frequency and fine for a status that changes a few times a day |
| Webhook | Service to service, and the receiver can host a reachable HTTPS endpoint | No held connection, liveness sweep or backpressure | Delivery order isn't guaranteed, so the receiver carries a sequence number or timestamp; the sender owns retry with backoff |
| gRPC server-streaming | Neither end is a browser and both share a Protobuf contract | Typed messages and HTTP/2 flow control | Browsers need a grpc-web proxy |
| Plain request/response | Nothing is live: a daily report, a refresh button, a settings screen | Nothing to hold open, reconnect or sweep | None; the cheapest option |
| Message broker | Backend-to-backend traffic that needs reliable, replayable delivery with no requirement that both sides be online together | Replay, per-partition ordering, fan-out | Running a log |

The broker row is the backplane in `part4-backplane` itself: once reconnect and scale-out needed replayable fan-out, the fix was Kafka, not a smarter socket. Its `kafka` and `redis` toggle states the trade. Kafka buys durability and replay at the price of operating a log; Redis buys most of the cross-instance fan-out with less to run and no replay.

The same shipping domain has an interaction for each row:

| Interaction | Fits |
| --- | --- |
| A warehouse dashboard showing dozens of handling-event updates a minute, never sending anything back | SSE |
| A customs broker's integration checking a status that moves a handful of times a day | Long-polling |
| A partner's booking system that wants a call the instant a shipment clears customs and already runs a public endpoint | Webhook |
| An internal analytics service aggregating handling events across the fleet | gRPC server-streaming |
| A booking confirmation page watching a status that changes twice a day | Plain request/response, or SSE |

**HTTP/2 server push is not an option.** Chrome and most major browsers removed it. If an interaction needs server-to-browser push, the live choices are WebSocket or SSE.

{% include excalidraw.html file="27-socket-or-alternative" alt="A decision keeps the WebSocket only when both sides send with sub-second delivery. Otherwise the interaction moves to SSE, long-polling, a webhook, gRPC server-streaming, plain request/response or a message broker, and HTTP/2 server push is marked as a dead end. A footer lists the signals to move off a socket: idle tabs, an unused client channel, a low update rate, a proxy that breaks Upgrade, and fan-out cost that grows with instances." caption="Figure 27.1: keep the socket, or move to the alternative that fits the interaction." %}

## Migration signals

A socket already in production is a candidate to migrate when any of these holds:

- **Idle tabs hold file descriptors for rare updates.** A connection open for a tab's life, watching a value that changes a couple of times a day, pays the full liveness and connection-table cost for almost nothing.
- **The client-to-server direction has never carried a message.** The duplex capability was never used, and `EventSource` gives up nothing the interaction needed.
- **Updates are rarer than the overhead of holding the connection.** When a long-poll's per-update cost is lower in aggregate than a standing connection's, long-polling or SSE wins on economics.
- **A proxy or firewall breaks the `Upgrade` handshake.** A socket that works in every tested environment but fails intermittently behind a customer's network is this case, and no client retry fixes a proxy that strips `Connection: Upgrade`.
- **Fan-out cost tracks instance count, not subscriber count.** A backplane with N instances subscribed does roughly N times the deserialize-and-filter work per event, whether or not those instances have a client waiting. If instances grow faster than clients per booking, partition the backplane or reconsider whether the interaction needs a socket-backed backplane at all.

> **Decision**
>
> Use a socket only when the interaction needs low-latency, full-duplex delivery held open continuously: both sides send, and the update rate justifies a standing connection. Otherwise: SSE when only the server sends to a browser, long-polling when the path distrusts held-open responses, a webhook when the receiver can host an endpoint, gRPC server-streaming when neither end is a browser, plain request/response when nothing is live, and a broker for backend-to-backend traffic.

> **🤖 Explore with your agent**
>
> "In examples/part4-backplane and examples/part4-connection, list every interaction the services carry (the handling-events channel on /ws/v1/bookings/{id}/handling-events, the internal inject endpoint POST /internal/bookings/{id}/handling-events, and any other route). For each, apply this rule: keep the socket only if both sides send and updates need to arrive in well under a second; otherwise name SSE, long-polling, a webhook, gRPC server-streaming, plain request/response or a broker, and say which of the socket costs (reconnect with ?afterEventId, the 4408 liveness sweep, the 4290 backpressure close, the 1008 auth close, the backplane) it would remove."
>
> Check: the reply keeps the handling-events channel as a socket, classifies the inject endpoint as plain request/response, and names a concrete cost removed for each change.

## Build, run, observe

There is nothing new to run. The costs above are already in the examples, and each can be observed there:

```bash
examples/part4-connection/verify.sh
examples/part4-backplane/verify.sh
```

`part4-connection` covers the liveness close and the backpressure close; `part4-backplane` covers resume across a gap and cross-instance delivery. Each script prints `ok, ` and `FAIL, ` per check and ends with `PASS: ` when all hold.

Experiments:

- In `part4-backplane`, run the default stateless mode, disconnect a client, inject an event, and reconnect with `?afterEventId=<last seen>`: the gap event is absent. Switch to the Kafka mode and it replays.
- In `part4-connection`, set `OUTBOUND_QUEUE_MAXSIZE=0` on Python and `EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0` on Quarkus: Python treats zero as unbounded and never closes with `4290`, while Quarkus closes with `4290` on the first burst.

## For deeper coverage

- Zimmermann, O., Stocker, M., Lübke, D., Zdun, U. & Pautasso, C., *Patterns for API Design* (Addison-Wesley, 2022): integration patterns for the request/response and messaging shapes the alternatives draw from.
- Bellemare, A., *Building Event-Driven Microservices, Second Edition* (O'Reilly, 2025): the broker-based alternative named above for backend-to-backend traffic, covering the durability and replay trade-offs `examples/part4-backplane` demonstrates directly.
- *Cloud Native Design Patterns*, "Communications" chapter: the full comparison of interaction styles the alternatives specialize for the "already shipped a socket" question.
- [RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455): the WebSocket protocol whose operational costs are itemized above.
- [RFC 6202](https://datatracker.ietf.org/doc/html/rfc6202): best practices for long-polling and streaming over HTTP, the alternative named above for network paths that don't trust a long-lived connection.
