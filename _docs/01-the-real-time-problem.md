---
title: "The Real-Time Problem"
order: 1
part: "Foundations"
description: "What 'push' means, why request/response falls short for a client watching something change, and the real cost of polling for an answer."
duration: "17 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why `GET /bookings/{id}` can answer "what is true right now" but has no channel to say "tell me the moment that changes."
- Quantify the cost of polling the booking service: wasted requests, provisioned-for-peak server capacity, and a latency-vs-staleness trade-off that no fixed or adaptive interval resolves.
- Diagnose which interactions need a standing connection versus a one-time `GET` or a scheduled batch query.
- Trace how a WebSocket's `Upgrade` handshake replaces repeated polling with one connection held open for as long as the client cares to watch.

## Why this matters

Chapter 0 pinned the toolchain and raised the lab without yet explaining why any of it needs a live socket at all. This chapter makes that case against the shipping domain's own numbers: a server has no channel to speak first in a request/response exchange, so a client watching for a change is left guessing at a polling interval, and every guess trades latency against wasted requests with no interval that fixes both. That cost, measured here, is what Chapter 2 spends its own space deciding how to close.

A client watching booking `BKG-4471` move through customs does not need an answer right now — it needs to know the instant the answer changes, and request/response has no way to express that distinction. Every HTTP call is a question the server answers once and forgets; if the client wants to know about a change it has to ask again, and again, most of those questions landing on an answer identical to the one before. This chapter sets up the cost of that pattern against the shipping/cargo domain this site shares with its REST and gRPC siblings, and the next chapter turns the cost into a decision about which push mechanism fits.

## A booking that doesn't move on request

The REST booking service tracks a `Booking` through its lifecycle — `PENDING`, `CONFIRMED`, `IN_TRANSIT`, `DELIVERED` — and along the way records `handling events` against it: a container gated in at a terminal, a customs hold opened, a delivery confirmed at the consignee's dock. A client watching one booking — a shipper's dashboard, a customs broker's queue, an ops team's alert panel — wants to know about each of those events as they happen. `GET /bookings/4471` answers "what is true right now," which is exactly the question it was built to answer, and exactly the wrong shape for "tell me when something changes." The booking's state does not change because the client asked about it. It changes when a container moves, a hold is opened, a signature lands at a dock in NLRTM — events the client has no control over and no way to predict, which is the whole problem with asking.

That lifecycle is a small state machine, and the handling events are what drive it from one state to the next. Each transition is a fact the booking service learns at a moment it chooses, not one the client can time.

{% include excalidraw.html file="01-booking-lifecycle" alt="The Booking lifecycle drawn as a left-to-right state pipeline — PENDING, CONFIRMED, IN_TRANSIT, DELIVERED — tracked by the REST booking service. Beneath it, a lane labeled the handling-event feed shows the events recorded as the booking moves: GATE_IN as it leaves PENDING/CONFIRMED, LOAD and UNLOAD plus a CUSTOMS_HOLD during IN_TRANSIT, and DELIVERY_CONFIRMED at DELIVERED. Dashed connectors tie each event to the state during which it is recorded, and the lane is labeled as pushed over the WebSocket rather than polled for." caption="Figure 1.1 — The booking lifecycle as a state pipeline, with the handling-event feed pushed over the socket beneath it." %}

The only way to approximate "tell me when" using "what is true right now" is to ask "what is true right now" over and over, hoping the gap between one answer and a changed one is short enough to matter. That's polling, and it is the default reach for anyone building against a REST API who hasn't been given another option.

Nothing about the booking service's design is wrong for this to happen. `GET /bookings/4471` is a correct, cacheable, idempotent read of a resource — exactly what a REST API is supposed to offer, and the same contract the sibling REST site builds its whole first part around. The mismatch is on the client's side of the interaction: the client doesn't want a resource read, it wants a subscription, and no amount of refining the resource representation changes that. A richer response body, more fields, a `lastModified` timestamp to compare against — all of that helps a client detect a change slightly faster once it polls, but none of it removes the need to poll in the first place. The booking service can't tell the client about a change it doesn't know the client is waiting for, because request/response gives the server no channel to speak first.

## The cost of polling

Every poll costs the same whether or not it finds anything: a TCP connection (or a reused one from a pool), a TLS handshake amortized across the connection's lifetime, an HTTP request line and headers, authentication checked against the booking service, a database read or cache lookup for the booking's current row, a JSON body serialized, and that body sent back over the wire. None of that work depends on whether the booking changed since the last poll. A `GET` that finds `IN_TRANSIT` unchanged for the fortieth time in a row does the same work as the one that finally finds `DELIVERED`.

Multiply that by watchers. One customs broker watching one booking every two seconds for ten minutes sends 300 requests to observe, at most, a handful of real events — usually one or two handling events in that window, sometimes zero. A thousand brokers each watching their own booking at the same interval turns that into 300,000 requests for roughly a thousand events worth reporting, a ratio of waste that doesn't improve with more watchers or a longer window; it only compounds. The booking service has to provision for peak polling load — the worst case where every client is asking at once — not for the much smaller volume of load that carries information. Database connections, request-handling threads, and load-balancer capacity all get sized for noise.

None of that capacity is reclaimable at the moment it matters most. A customs hold that triggers a wave of interest — a broker refreshing manually, a shipper's dashboard dropping to a 1-second interval because someone is watching closely now — lands on top of the steady-state polling load already saturating the booking service, at the exact moment that service is also handling the workflow that opened the hold in the first place. Polling concentrates load where attention concentrates, which is also where correctness matters most.

## Latency vs. freshness

Shortening the poll interval trades one cost for another. A client polling every 10 seconds misses a handling event by up to 10 seconds — the gap between the event happening and the next poll catching it. Drop the interval to 1 second and the gap shrinks, but the request volume rises by 10x for every client doing it, and the booking service now serves ten times the empty answers to shave a few seconds off detection time it still can't guarantee: the event could land right after a poll, the full interval away from the next one. There is no interval that delivers both low latency and low waste, because the interval is a guess about when something will happen, made by a client with no information about when that something will happen. A hold can open thirty seconds after the last poll or thirty milliseconds before the next one; the client has no way to know which, so it has to guess short enough to feel responsive and live with the request volume that guess produces.

Staleness is the other side of the same trade. A dashboard polling every 30 seconds shows a booking's status as of the last successful poll, which might be correct or might be thirty seconds behind a hold that already opened. The gap is invisible to the client — nothing in a `200 OK` with an unchanged body says "this might already be wrong by the time you read it" — so every poll-driven view carries a margin of staleness nobody has measured, let alone communicated to whoever's reading the dashboard.

Backing off the interval under load makes both problems worse at once. A booking service under heavy polling traffic is a natural candidate for rate limiting or a longer suggested interval in a `Retry-After` header, and a client that respects either one buys the service some relief at the direct cost of its own freshness — the exact moment the system is busiest, usually because something real is happening across many bookings at once, is the moment staleness grows for every client watching one. There is no interval, fixed or adaptive, that decouples the client's freshness from the server's load; the two move in opposite directions along the same knob.

## What push changes

A WebSocket inverts who initiates. Instead of the client asking "did anything change" on a schedule it has to guess, the client opens one connection and the booking service's event stream sends a message the instant a handling event is recorded against that booking — `GATE_IN`, `CUSTOMS_HOLD`, `DELIVERY_CONFIRMED` — because sending it is a side effect of the event happening, not a response to being asked. No request carries the question "did anything change," because the server already knows the answer and pushes it when it becomes true instead of waiting to be asked.

The connection itself starts as an ordinary HTTP request. A client opens `GET /bookings/4471/events` with an `Upgrade: websocket` header, the server answers `101 Switching Protocols`, and from that point the TCP connection stops speaking HTTP request/response and starts carrying WebSocket frames in both directions over the same socket. That one upgrade replaces the 300 separate connections-and-requests a ten-minute poll loop would have made; the handshake cost is paid once, not once per check. Chapter 3 walks the upgrade handshake and the frame format in full — this chapter only needs the shape of the trade: one connection, held open, instead of many short ones repeated on a schedule.

Holding a connection open is not free — a server now carries one open socket, and the memory and file-descriptor cost that comes with it, per watching client for as long as that client cares to watch, where a poll-based design holds nothing between requests. That's a real cost, and it's the one later chapters spend real space on: Chapter 12 covers backpressure when a client can't keep up with the events arriving, Chapter 14 covers heartbeats to detect a connection that died without saying so, and Chapter 18 covers fanning one event out to thousands of open connections without the server doing thousands of times the work. None of that erases the win this chapter is making the case for — it reframes the cost from per-request, paid whether or not anything happened, to per-connection, paid once for as long as the watch lasts.

{% include excalidraw.html file="01-poll-vs-push" alt="Side-by-side comparison of a client watching booking BKG-4471 by polling the REST booking service versus holding a WebSocket connection open. The polling side shows four GET requests in a row returning an unchanged status, then one GET finally catching a CUSTOMS_HOLD change, with a note that the real change is found zero to thirty seconds after it happened. The push side shows one connection held open with no traffic, then two messages pushed the instant each handling event — GATE_IN and CUSTOMS_HOLD — is recorded, with a note that every change is seen within one network hop with no gap." caption="Figure 1.2 — Pull vs. push: the same booking, watched two ways." %}

This moves the detection latency from "however long until the next scheduled poll" to "one network hop," and it moves the request volume from "proportional to how often the client is willing to ask" to "proportional to how often something happens in the domain." A booking that goes quiet for six hours between gate-in and the next handling event sends nothing over the socket in that window — no 300 empty polls, no load on the booking service to answer them — and a booking with five events in five minutes gets five messages, each one carrying something the client didn't have before. Volume now tracks information instead of tracking a guessed interval, which is the inversion this chapter is about: pull makes the client pay for ignorance on every request, push makes the server pay once per fact.

## Where real-time matters, and where it doesn't

Not every piece of booking state deserves a socket. A shipper checking a booking's status once, to confirm it went through, has no ongoing interest to hold a connection open for — a single `GET` answers it correctly and closes. A nightly reconciliation job comparing yesterday's bookings against an accounting system doesn't care about the millisecond a hold opened; it wants a batch of records once a day, which a REST query over a date range serves better than a socket ever could. A report generated once a quarter has no "live" dimension at all.

What earns a socket is an open-ended interest in change over an unbounded or long window: a dashboard that stays open on an ops team's screen all shift, a customs broker's queue that needs to react the moment a hold appears, a mobile app showing a shipment's progress to a customer who has it open intermittently for hours. The common thread is a client that would otherwise poll — one that needs to know about a change soon after it happens and has no way to predict when that will be.

The same booking can sit on both sides of that line depending on who's asking and why. The shipper who created `BKG-4471` and wants one confirmation that it was accepted needs a single request-response round trip, nothing held open. The same shipper's ops dashboard, tracking that booking alongside two hundred others through delivery, is exactly the client a socket is for — not because the booking is special, but because the relationship between client and data changed from a one-time check to a standing interest. The decision isn't a property of the booking service or the data it holds; it's a property of what the client intends to do with a change once it arrives, and for how long it intends to keep caring.

Chapter 2 turns "soon after it happens" into harder criteria — one-way or two-way, how many clients, how much state needs to survive a disconnect — because "it needs to be live" is a starting instinct, not yet a decision between WebSockets, Server-Sent Events, long-polling, and webhooks.

## On the wire

Put concrete numbers against the same scenario — one booking, watched for ten minutes, with one handling event at minute seven — and the gap between pull and push stops being an abstraction.

A client polling every 2 seconds sends 300 requests over that window. A representative run of request logs against the booking service looks like this:

```
GET /bookings/4471 HTTP/1.1          → 200 OK   {"status":"IN_TRANSIT", ...}   (unchanged)
GET /bookings/4471 HTTP/1.1          → 200 OK   {"status":"IN_TRANSIT", ...}   (unchanged)
GET /bookings/4471 HTTP/1.1          → 200 OK   {"status":"IN_TRANSIT", ...}   (unchanged)
...  294 more identical responses ...
GET /bookings/4471 HTTP/1.1          → 200 OK   {"status":"CUSTOMS_HOLD", ...} (changed — minute 7)
...  2 more identical responses ...
```

Of 300 requests, 299 return a body byte-for-byte identical to the previous one. Each still costs a full connection reuse, an auth check, a database read, and a JSON body over the wire — the server did real work to tell the client nothing new. One request out of 300 carries the information the client was watching for; the other 299 are pure overhead paid to not miss it.

| | Pull (2s poll) | Push (one socket) |
|---|---|---|
| Requests/messages over 10 min, 1 booking | 300 | 1 (sent when the event occurs) |
| Requests/messages carrying new information | 1 | 1 |
| Wasted requests | 299 | 0 |
| Worst-case detection latency | ~2s (the poll interval) | one network hop |
| Scaling with 1,000 clients watching 1,000 bookings | 300,000 requests, ~1,000 useful | 1,000 messages, 1,000 useful |

{% include excalidraw.html file="01-polling-cost" alt="Diagram showing a timeline of polling requests against one booking over ten minutes: four polls return unchanged results, a run of 296 more are elided, and one final poll catches the change, with a callout stating 300 requests were sent to watch one booking for ten minutes and 299 returned a body identical to the one before, zero new information for the full request/response cost. Below, a side-by-side comparison shows 1,000 clients polling at the same interval producing 300,000 requests for 1,000 real events, against a push equivalent of 1,000 open sockets delivering 1,000 messages total." caption="Figure 1.3 — The cost of polling: 299 wasted requests for every real change, at any scale." %}

The push column's message count scales with events, not with watchers times poll frequency. That's the structural difference a socket buys: the booking service's load becomes a function of how much is happening in the shipping domain, not a function of how anxious the clients watching it are.

## Where this goes next

Polling a REST resource for a status that hasn't changed costs real requests, real server capacity, and a latency-vs-staleness trade with no good answer, because the client is guessing at an interval instead of being told. A WebSocket replaces the guess with a standing connection the server uses to push a handling event the moment it's recorded, and the cost of that connection scales with real events instead of request volume. That's the case for push in general — it says nothing yet about which push mechanism fits a given interaction. A one-way status feed, a two-way negotiation, a client behind a strict proxy that can't hold a long-lived connection, and a background job that wants a callback instead of a live view all want different answers, and WebSockets isn't the only one. Chapter 2 lays WebSockets, Server-Sent Events, long-polling, and webhooks side by side against explicit criteria and picks among them for the shipping domain's actual interactions, the same way the REST and gRPC sibling sites turn their opening chapter's vocabulary into a decision framework in their second.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>The handling-event feed for a watched booking moves from pull to push: a client that needs to know about a status change soon after it happens, for as long as it's watching, gets a standing connection instead of a poll loop. Chapter 2 picks the specific mechanism — WebSockets, SSE, long-polling, or webhooks — against the shipping domain's actual interactions.</p></div>

## For deeper coverage

- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026) — the latency, freshness, and delivery trade-offs behind "tell me when it changes" versus "what is true right now."
- Dynowski, L. & Dulak, M., *Learning API Styles* (O'Reilly, 2025) — where push-based interaction fits among the broader set of API styles this series compares.
- *Cloud Native Design Patterns* — "Communications" and "Event-Driven" chapters — the interaction-style landscape and the event-backbone alternative to polling.
- [RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455) — the protocol behind the standing connection this chapter argues for.
- [MDN: WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket) — the browser-native interface a client uses instead of a polling loop.
