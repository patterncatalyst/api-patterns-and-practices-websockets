---
title: "The Real-Time Problem"
order: 1
part: "Foundations"
description: "Why request/response falls short for a client watching something change, and what polling costs in requests, capacity and staleness."
duration: "9 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why `GET /bookings/{id}` answers "what is true right now" but has no way to say "tell me the moment that changes."
- Quantify the cost of polling: wasted requests, capacity provisioned for peak, and a latency-versus-staleness trade no interval resolves.
- Decide which interactions need a standing connection and which need a one-time `GET` or a scheduled batch query.
- Describe how a WebSocket `Upgrade` replaces repeated polling with one connection held open for as long as the client cares to watch.

## Why this matters

A client watching booking `BKG-4471` move through customs does not need an answer right now. It needs to know the instant the answer changes, and request/response cannot express that. Every HTTP call is a question the server answers once and forgets, so a client that wants changes has to ask again, and most of those questions land on an answer identical to the last. The cost is measurable, and it is the case for push.

## A booking that does not move on request

The REST booking service tracks a `Booking` through `PENDING`, `CONFIRMED`, `IN_TRANSIT` and `DELIVERED`, and records handling events against it: a container gated in at a terminal, a customs hold opened, a delivery confirmed at the consignee's dock. A shipper's dashboard, a customs broker's queue and an ops alert panel all want each of those as it happens.

`GET /bookings/4471` is a correct, cacheable, idempotent read of a resource, and it is the wrong shape for "tell me when something changes." The booking does not change because the client asked. It changes when a container moves or a hold opens, at moments the client cannot predict, and the booking service cannot tell a client about a change it does not know the client is waiting for, because request/response gives the server no channel to speak first. A richer body or a `lastModified` timestamp helps a poller detect a change slightly sooner, but none of it removes the need to poll.

{% include excalidraw.html file="01-booking-lifecycle" alt="A booking lifecycle drawn as a left-to-right pipeline of four states, PENDING to DELIVERED. Beneath it, a lane of handling events (RECEIVE, LOAD / UNLOAD, HOLD, DELIVERED) is tied by dashed connectors to the state during which each is recorded, and labeled as pushed over the WebSocket rather than polled for." caption="Figure 1.1: The booking lifecycle as a state pipeline, with the handling-event feed pushed over the socket beneath it." %}

## The cost of polling

Every poll costs the same whether or not it finds anything: a pooled connection and its amortized TLS handshake, a request line and headers, authentication, a database or cache read for the booking's current row, and a serialized JSON body on the wire. The fortieth poll that finds `IN_TRANSIT` unchanged does the same work as the one that finally finds `DELIVERED`.

Multiply by watchers. One broker polling every 2 seconds for ten minutes sends 300 requests to observe a handful of real events, often one or two and sometimes none. A thousand brokers watching their own bookings is 300,000 requests for roughly a thousand events worth reporting. The ratio does not improve with more watchers or a longer window; it compounds. The service must provision database connections, threads and load-balancer capacity for peak polling, not for the much smaller load that carries information.

That capacity is not available when it matters most. A customs hold that draws attention (a broker refreshing by hand, a dashboard dropping to a 1-second interval) lands on top of steady-state polling, at the moment the service is also handling the workflow that opened the hold. Polling concentrates load where attention concentrates.

## Latency versus freshness

Shortening the interval trades one cost for another. A 10-second poll misses an event by up to 10 seconds. Dropping to 1 second shrinks the gap but multiplies request volume by ten for every client, and still guarantees nothing: the event can land just after a poll, a full interval from the next. The interval is a guess about when something will happen, made by a client with no information about when.

Staleness is the same trade seen from the other side. A dashboard polling every 30 seconds shows the booking as of its last poll, which may already be 30 seconds behind a hold. Nothing in a `200 OK` with an unchanged body says it might already be wrong, so every poll-driven view carries an unmeasured margin of staleness.

Backing off under load makes both worse. A service under heavy polling reasonably rate limits or sends a longer `Retry-After`, and a client that complies buys the service relief at the cost of its own freshness, at exactly the moment the system is busiest because something real is happening across many bookings. No interval, fixed or adaptive, decouples client freshness from server load; they move in opposite directions along one knob.

## What push changes

A WebSocket inverts who initiates. The client opens one connection, and the server sends a message the moment a handling event is recorded, because sending is a side effect of the event, not a response to a question.

The connection starts as an ordinary HTTP request. The client sends a `GET` with `Upgrade: websocket`, the server answers `101 Switching Protocols`, and from then on the same TCP connection carries WebSocket frames in both directions. In the examples this is `GET /ws/v1/bookings/{bookingId}/handling-events`. One upgrade replaces the 300 connections and requests of a ten-minute poll loop.

Holding a connection open is not free: the server carries an open socket, with its memory and file descriptor, per watching client for as long as the watch lasts, where a polling design holds nothing between requests. That cost is real, and the later problems follow from it: a client that cannot keep up with arriving events, a connection that dies without saying so, and fanning one event out to thousands of sockets. But the cost moves from per-request, paid whether or not anything happened, to per-connection, paid once per watch.

{% include excalidraw.html file="01-poll-vs-push" alt="Two columns for one booking. Polling shows three GET requests returning an unchanged status and a fourth that finally catches the HOLD, found up to thirty seconds late. Push shows one open connection that carries two messages, RECEIVE and HOLD, each sent the instant its handling event is recorded." caption="Figure 1.2: Pull vs. push: the same booking, watched two ways." %}

Detection latency drops from "until the next scheduled poll" to one network hop, and traffic goes from "proportional to how often the client asks" to "proportional to how often something happens." A booking quiet for six hours sends nothing; a booking with five events in five minutes gets five messages, each carrying something new. Pull makes the client pay for ignorance on every request. Push makes the server pay once per fact.

The scenario in numbers is one booking watched for ten minutes with one handling event at minute seven:

| | Pull (2 s poll) | Push (one socket) |
|---|---|---|
| Requests or messages over 10 minutes | 300 | 1, sent when the event occurs |
| Carrying new information | 1 | 1 |
| Wasted | 299 | 0 |
| Worst-case detection latency | about 2 s (the interval) | one network hop |
| 1,000 clients watching 1,000 bookings | 300,000 requests, about 1,000 useful | 1,000 messages, 1,000 useful |

{% include excalidraw.html file="01-polling-cost" alt="A timeline of 300 polls over ten minutes in which only one returns a changed body, with a comparison below: 1,000 polling clients send 300,000 requests for 1,000 real events, while 1,000 open sockets deliver 1,000 messages." caption="Figure 1.3: The cost of polling: 299 wasted requests for every real change, at any scale." %}

The push column scales with events, not with watchers times poll frequency, so the booking service's load becomes a function of what is happening in the shipping domain rather than how anxious its clients are.

## Where real-time matters, and where it does not

Not every piece of booking state deserves a socket. A shipper confirming once that a booking went through needs a single `GET`. A nightly reconciliation job comparing yesterday's bookings against accounting wants a REST query over a date range, not a live feed. A quarterly report has no live dimension.

What earns a socket is an open-ended interest in change over a long or unbounded window: a dashboard open all shift, a broker's queue that must react the moment a hold appears, a mobile app showing shipment progress for hours. The common thread is a client that would otherwise poll.

The same booking can sit on both sides of the line. The shipper who wants one confirmation that `BKG-4471` was accepted needs one round trip. The same shipper's ops dashboard, tracking that booking and two hundred others through delivery, is what a socket is for. The decision is a property of what the client will do with a change and for how long it keeps caring, not of the data.

"It needs to be live" is a starting instinct, not a decision among WebSockets, Server-Sent Events, long-polling and webhooks. Direction, client count and how much state must survive a disconnect decide that.

> **Decision**
>
> Move a watched booking's handling-event feed from pull to push when a client needs to know about a change soon after it happens, for as long as it is watching. Use a plain `GET` for a one-time read and a scheduled query for batch work.

> **🤖 Explore with your agent**
>
> "In examples/part3-handling-events, connect websocat to the handling-events channel at ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events and the same path on port 8081, and list the eventType and occurredAt of every frame each stack pushes. Then work out how many requests a 2-second poller would send over ten minutes to see the same events, and apply this rule: a standing interest in change gets a socket, a one-time read gets a GET."
>
> Check: both stacks push the events in fixtures/handling-events.json in the same order, RECEIVE, LOAD, CUSTOMS, and the poller arithmetic comes to 300 requests.

## Build, run, observe

The Part 3 example serves the feed on both stacks: Quarkus on host port 8080 and Python on 8081. Bring it up and read the first pushed frame by hand with the shared harness:

```bash
cd examples/part3-handling-events
docker compose up --build -d
source ../_lib/lib.sh
ensure_websocat
wait_for_ws localhost:8080 /ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events
ws_first_frame "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
docker compose down -v
```

One connection, no polling: the server pushes a `RECEIVE` handling event the moment the upgrade completes. Run `./verify.sh` to do the same against both stacks and check that the first frame validates against the contract's JSON Schema and agrees field for field.

- Swap `8080` for `8081` to read the same frame from the Python stack.
- Run `docker compose --profile observability up --build` to add Grafana LGTM on `:3000`; the feed is unchanged.

## For deeper coverage

- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026): the latency, freshness, and delivery trade-offs behind "tell me when it changes" versus "what is true right now."
- Dynowski, L. & Dulak, M., *Learning API Styles* (O'Reilly, 2025): where push-based interaction fits among the broader set of API styles this series compares.
- *Cloud Native Design Patterns*, "Communications" and "Event-Driven" chapters: the interaction-style landscape and the event-backbone alternative to polling.
- [RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455): the protocol behind the standing connection described above.
- [MDN: WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket): the browser-native interface a client uses instead of a polling loop.
