---
title: "The Shared Domain"
order: 4
part: "Foundations"
description: "The shipping domain for a live handling-event feed: which nouns travel on the wire, the event vocabulary and the seam with the REST booking service."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Name the `HandlingEvent` fields (`bookingId`, `cargoId`, `eventType`, `location`, `occurredAt`, `registeredAt`, `amount`) and say why each is an identifier or scalar, not a nested object.
- Explain why `Route`, `Leg` and `Operation` are part of the shared domain but never appear on a `HandlingEvent`.
- Explain why `Money` is a decimal string matching `^\d+\.\d{2}$` and not a JSON number.
- State what the socket replaces in the REST booking service and what it doesn't: replay, catch-up and full current state.

## Why this matters

The protocol carries bytes. A client needs to know what a frame means, what it must fetch elsewhere and what happens to events missed during a disconnect. This vocabulary becomes the AsyncAPI contract that both stacks generate from, and it fixes the seam between a live push and the REST booking service that owns state.

## The shipping domain

This series describes one shipping domain from three angles. REST models it as resources, gRPC as Protobuf messages and RPCs, and WebSockets as a stream of events pushed while a booking moves from accepted to delivered.

A `Booking` is an agreement to move some `Cargo` from an origin to a destination along a `Route` of one or more `Leg`s, each a single carrier's movement between two `Location`s identified by UN/LOCODE. The WebSocket series adds the `HandlingEvent`: a record of something that happened to a booking's cargo in the physical world (gated in at a terminal, loaded aboard a vessel, held by customs, delivered to a consignee). It is the one message type the socket sends.

The REST booking service owns the full `Booking` and `Cargo` records. A `HandlingEvent` carries ids, a type, a place and times: enough to tell a client that something changed and what. Current state is a `GET`.

## The live handling-event feed

The feed is one channel, `/ws/v1/bookings/{bookingId}/handling-events`, scoped to one booking per connection. The server pushes a `HandlingEvent` each time one is recorded, in the order it registers them. `contracts/asyncapi.yaml` declares this as an AsyncAPI 3 `action: receive` operation: server to client only. Opening the connection and keeping it open is the whole client contract.

A client watching a booking through customs doesn't ask anything once the socket is open. It is told once per event, as each is recorded. There is no query, no filter and no acknowledgment. A chat socket is bidirectional because both ends speak, and this one isn't because only the booking service's write path has news.

Scope per connection means a client watching five bookings holds five sockets. That costs more file descriptors and handshakes than one multiplexed channel, and in exchange authorization is one decision at connect time ("can this caller watch this `bookingId`") and not a per-message filter on a shared channel. Fan-out at scale revisits the trade.

{% include excalidraw.html file="04-handling-event-feed" alt="Flow diagram: the REST booking service records a HandlingEvent, which triggers a push on the handling-events channel to a watching client. A dashed arrow from the client back to the REST service shows that GET /bookings/{id} still answers requests for full current state." caption="Figure 4.1: The booking service's write path triggers a push. Its read path, GET /bookings/{id}, still answers on request." %}

## The nouns on the wire

| Noun | On the wire | Notes |
|---|---|---|
| Booking | `bookingId`, `^bkg_[0-9A-Za-z]{26}$` | `bkg_` plus a 26-character ULID, the same shape as the channel's `{bookingId}` parameter. No status or route. |
| Cargo | `cargoId`, `^crg_[0-9A-Za-z]{26}$` | One booking can cover several pieces of cargo, and an event is recorded against one. A hold on one container doesn't hold the booking. |
| Location | `location`, `^[A-Z]{2}[A-Z2-9]{3}$` | A bare UN/LOCODE (`USNYC`, `NLRTM`, `SGSIN`), not an object with a name and coordinates. |
| Route, Leg | absent | A route says what was scheduled. An event records what already happened. |
| Operation | absent | The long-running-job pattern from the gRPC series. Every push is a completed fact, so there is no job to poll. |

{% include excalidraw.html file="04-domain-model" alt="Domain model diagram: Booking has Cargo and follows a Route made of Legs, each Leg between two Locations. HandlingEvent is recorded against a Cargo, belongs to a Booking by id, occurred at a Location and optionally carries a Money amount. It is the only noun the feed pushes. The rest travel inside it as ids and values." caption="Figure 4.2: The domain model. A HandlingEvent names a booking, cargo and location by id and carries only plain values." %}

## Event vocabulary

`HandlingEventType` has eight members in `contracts/asyncapi.yaml`:

| Member | What it records |
|---|---|
| `HANDLING_EVENT_TYPE_UNSPECIFIED` | The zero value. Never sent by the server. It gives the enum a safe default on deserialization, the `*_UNSPECIFIED` convention the gRPC series uses. |
| `RECEIVE` | Cargo is received into custody at the origin. |
| `LOAD` | Cargo is loaded aboard a vessel for a leg. |
| `UNLOAD` | Cargo is unloaded at an intermediate or final port. |
| `CUSTOMS` | Cargo is held or cleared by a customs authority. |
| `CLAIM` | The consignee or agent claims cargo at destination. |
| `HOLD` | Cargo is held for a reason other than customs: documentation, payment, damage inspection. |
| `DELIVERED` | Cargo reaches its final destination. |

It is the value a deserializer falls back to when the field is missing or a member it doesn't know yet arrives, so "unspecified" is a checkable state, not a null that crashes a `switch`. A client that sees `HANDLING_EVENT_TYPE_UNSPECIFIED` has a malformed message or a schema that evolved past it. It is not an eighth kind of event.

Two fields carry time, and the gap between them is meaningful. `occurredAt` is when the event physically happened and `registeredAt` is when the system recorded it, never earlier. A customs hold opened at 9:12 local time might be keyed in hours later from a paper manifest. A client computing how stale its view is needs `occurredAt`, and one auditing when the system learned of it needs `registeredAt`.

`voyageNumber` appears only on events tied to a sailing, typically `LOAD` and `UNLOAD`. Its absence on `CUSTOMS` or `CLAIM` is correct.

## Money as a decimal string

`amount`, when present, is a `Money` string matching `^\d+\.\d{2}$`, like `"125.00"`, never a JSON number. The REST JSON Schema and the gRPC `Money` type make the same choice, for a reason that doesn't depend on transport.

JSON numbers are IEEE 754 doubles, and a double can't represent every decimal fraction: `0.1 + 0.2` doesn't equal `0.3`. The number `245.00` round-trips today, but some mix of client language, library and downstream arithmetic eventually drifts by a cent, and the wire format can't assert "this must be exact". A string means exactly `245.00` and is parsed by a decimal type on whichever side reads it.

The feed carries no currency code. Amounts are in the booking's quoted currency, which this feed isn't the system of record for. A client that renders a currency symbol takes the currency from the booking it already holds.

## The seam with the REST booking service

The REST booking service is the one place a `Booking`'s and `Cargo`'s current state lives. The feed is not a second database or a cache to query for what is true now. The correct client sequence is to `GET` the booking once, open the socket to learn every change from that point on, and never `GET` again to ask whether something changed.

The contract defines no replay, no "everything since event X" and no persisted history. A client that disconnects doesn't get missed events back from this contract. It re-fetches current state with the same `GET` it used to seed its view and resumes watching. Two answers to that gap come later, one stateless and one Kafka-backed. The contract promises a live push of what happens next, not a log to rewind.

The seam also runs through authorization. The server description carries a bearer token as the `token` query parameter and advertises the `handling-events.v1` subprotocol. Whatever issues the token has to agree the caller may watch that `bookingId` before the handshake completes, and that decision should consult the same permissions the booking service applies to `GET /bookings/{bookingId}`. A customs broker who can't read a booking over REST has no business watching its events. The contract treats the token as opaque.

## On the wire

A customs hold on one piece of cargo, with a duty amount and no voyage number:

```json
{
  "eventId": "evt_01HZY3M1V8X4D7Q6B2N9C0T5E8",
  "bookingId": "bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A",
  "cargoId": "crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5",
  "eventType": "CUSTOMS",
  "location": "USNYC",
  "occurredAt": "2026-03-14T09:12:00Z",
  "registeredAt": "2026-03-14T09:14:33Z",
  "amount": "245.00"
}
```

| Field | Meaning |
|---|---|
| `eventId` | This event's id, `evt_` plus a ULID. Unique, never reused. |
| `bookingId` | Matches the channel's `{bookingId}` path parameter. A client only receives events for the booking it connected to. |
| `cargoId` | The piece of cargo, distinct from the booking. |
| `eventType` | One of the eight members. `CUSTOMS` is held or cleared by customs. |
| `location` | UN/LOCODE. `USNYC` is New York/Newark. |
| `occurredAt` | When the hold was physically opened. |
| `registeredAt` | When the system recorded it, here 2 minutes 33 seconds later. |
| `voyageNumber` | Absent, because customs isn't tied to a sailing. Omitted, not `null` or an empty string. |
| `amount` | `"245.00"`, a decimal string with no currency code. |

> **Decision**
>
> The feed carries one noun, `HandlingEvent`, and everything else in the glossary stays with the REST booking service, referenced by id or value. `bookingId` and `cargoId` stay identifiers, `Location` stays a bare UN/LOCODE, and `Route`, `Leg` and `Operation` never appear. Events stay small and cheap to push, and one system answers for what a `Booking` looks like. The cost is that a client wanting more than an event's fields goes back to the booking service, and a client that misses events during a disconnect gets no replay from this contract.

> **🤖 Explore with your agent**
>
> "Read `contracts/asyncapi.yaml` and the fixture `examples/part3-handling-events/fixtures/handling-events.json`. Check that every fixture event has only the fields `components.schemas.HandlingEvent` defines, and that `bkg_`, `crg_`, `evt_`, `location` and `amount` match their patterns. Then list which of `Route`, `Leg` and `Operation` appear on a message (the rule is none) and which state a reconnecting client must fetch from the REST booking service instead of expecting a replay."
>
> Check: the reply reports no extra fields and no pattern mismatches, and says a reconnecting client calls `GET /bookings/{bookingId}`.

## Build, run, observe

Both stacks replay the same three events from `fixtures/handling-events.json` for any `bookingId`. From the repo root:

```bash
cd examples/part3-handling-events
docker compose up --build -d
source ../_lib/lib.sh
ensure_websocat
ws_first_frame "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
docker compose down -v
```

The first frame is the `RECEIVE` event at USNYC with every required field and no `voyageNumber` or `amount`. Both stacks omit absent optional fields instead of sending `null`. Quarkus is on 8080 and Python on 8081, so run the same command against 8081 to compare. `./verify.sh` checks the first frame field by field against the fixture and the schema extracted from the contract on both stacks, then checks that both stacks agree, and prints `PASS:` on success.

- Use a different `bookingId` in the path: the same three events replay, because per-booking lookup isn't implemented here.
- Read the third fixture event: `CUSTOMS` at NLRTM carries the amount `125.00` as a string.

## For deeper coverage

- Vlad Khononov, *Learning Domain-Driven Design* (O'Reilly, 2021): modeling a bounded context's vocabulary and deciding what a message carries versus references by id.
- Eric Evans, *Domain-Driven Design: Tackling Complexity in the Heart of Software* (Addison-Wesley, 2003): the case for the ownership boundary drawn around the booking service.
- *Cloud Native Design Patterns*, "DDD & Hexagonal Architecture" chapter: placing a service boundary and keeping a contract's shape independent of its protocol.
- [JSON Schema](https://json-schema.org/): the pattern constraints on `bookingId`, `cargoId`, `location` and `amount`.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `action: receive` operation and `components.schemas`.
