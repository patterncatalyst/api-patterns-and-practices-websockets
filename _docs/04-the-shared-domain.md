---
title: "The Shared Domain"
order: 4
part: "Foundations"
description: "The shipping/cargo domain recapped for a live handling-event feed, and the event vocabulary every later chapter reuses."
duration: "20 min read"
---

Chapter 3 decoded a WebSocket frame down to its bytes and found a handling-event payload sitting inside, without stopping to say what any of those bytes meant in the shipping domain. This chapter names it: the nouns the socket pushes, the shape of the feed that carries them, and the seam where a live connection meets the REST booking service it exists to stop polling. Chapter 5 turns this vocabulary into the formal AsyncAPI 3 contract that both stacks generate from; this chapter is the domain underneath that contract, stated once so every later chapter can point back at it instead of re-deriving it.

## The shipping/cargo domain recap

Every site in this series — REST, gRPC, and this one — describes the same shipping/cargo domain from a different angle. The REST site models it as resources a client reads and writes over HTTP. The gRPC site models the same nouns as Protobuf messages passed to typed RPCs. This site cares about one narrow slice of that domain: the stream of events that fire while a booking moves from accepted to delivered, and the live connection a client holds open to watch them arrive.

A `Booking` is the thing a shipper creates and a client ultimately watches: an agreement to move some `Cargo` from an origin to a destination, following a `Route` made of one or more `Leg`s, each leg a single carrier's movement between two `Location`s identified by UN/LOCODE. None of that is new material — it is the same glossary the REST and gRPC sibling sites already define and that this site's `contracts/README.md` names explicitly as shared vocabulary. What is new here is the piece this site adds to that glossary: the `HandlingEvent`, a record of something that happened to a booking's cargo in the physical world — gated in at a terminal, loaded aboard a vessel, held by customs, delivered to a consignee — and the one message type this socket ever sends.

The REST booking service owns the full `Booking` and `Cargo` records: their current state, their history, every field a dashboard might want to render. This feed does not duplicate that ownership. A `HandlingEvent` carries a `bookingId`, a `cargoId`, what kind of event this is, and where and when it happened — enough to tell a watching client that something changed and what, and no more than that. Reconstructing the booking's full current state, if a client needs more than the event itself conveys, is still a job for a `GET` against the booking service, not something this feed re-implements as a side effect of pushing events. That division of labor shapes everything below: which nouns travel on the wire, what the event vocabulary means, and where the seam with the REST booking service runs.

## The live handling-event feed

A handling-event feed is a single WebSocket channel, `/ws/v1/bookings/{bookingId}/handling-events`, scoped to exactly one booking per connection. A client opens one connection per booking it wants to watch — there is no multiplexed "all my bookings" channel in this contract — and the server pushes one `HandlingEvent` message every time a new event is recorded against that booking's cargo, in the order the server registers them. `contracts/asyncapi.yaml` declares this as an AsyncAPI 3 `action: receive` operation: server-to-client only. The client never sends a message back on this channel; opening the connection and keeping it open is the entire client-side contract.

That one-directional shape is a direct consequence of what Chapter 1 established about this interaction. A client watching `bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A` through customs does not need to ask the server anything once the socket is open — it needs to be told, and told exactly once per event, the instant each one is recorded. There is no query to run over this channel, no filter to request, no acknowledgment the server is waiting on before it sends the next message. Compare that to a chat application's WebSocket, which is bidirectional because both ends have something to say; this feed is one-directional because only one end — the booking service's write path — ever has new information, and the client's only job is to receive it.

The feed's scope-per-connection design has a direct consequence that matters before Chapter 10 builds a client around it: a client watching five bookings holds five sockets open, not one socket carrying five bookings' worth of events multiplexed together. That costs more file descriptors and more handshakes up front than a single shared channel would, in exchange for a simpler authorization story — a connection's access decision is "can this caller watch this one `bookingId`," answered once at connect time, rather than a per-message filter re-evaluated on every event crossing a shared channel. Chapter 18 revisits this trade-off when fan-out to many simultaneous watchers becomes the chapter's subject; here it is named as the shape this contract commits to.

{% include excalidraw.html file="04-handling-event-feed" alt="Flow diagram showing the REST booking service recording a HandlingEvent when something happens to a booking's cargo, that event triggering a push over the /ws/v1/bookings/{bookingId}/handling-events channel, and a watching client receiving the HandlingEvent message. A dashed arrow from the watching client back to the REST booking service shows that GET /bookings/{id} still answers a request for the booking's full current state; the socket adds a push path without replacing that endpoint." caption="Figure 4.1 — The handling-event feed: the REST booking service's write path triggers a push; its read path, GET /bookings/{id}, still answers on request." %}

## The nouns, and which ones travel on the wire

Not every noun in the shared glossary appears the same way in a `HandlingEvent` message. Some are carried as identifiers, some as plain values, and some — `Route`, `Leg`, and `Operation` — are part of the domain this feed lives inside but never appear in the message shape at all, because they belong to the booking service's fuller representation, not to a single event's record of what happened.

**Booking** appears only as `bookingId`, a string matching `^bkg_[0-9A-Za-z]{26}$` — the `bkg_` prefix plus a 26-character ULID, the same identifier shape the channel path itself uses as its `{bookingId}` parameter. The message never repeats the booking's status, its route, or any other field the booking service owns; it names which booking the event belongs to and nothing more about that booking.

**Cargo** appears the same way, as `cargoId` matching `^crg_[0-9A-Za-z]{26}$`. One booking can cover more than one piece of cargo, and a handling event is recorded against one specific piece — a hold opened on one container in a multi-container shipment doesn't imply the whole booking is held, which is exactly why `cargoId` is a field distinct from `bookingId` rather than redundant with it.

**Location** is a UN/LOCODE string matching `^[A-Z]{2}[A-Z2-9]{3}$` — `USNYC`, `NLRTM`, `SGSIN` are the contract's own examples. This is narrower than how `Location` might appear elsewhere in the shared glossary as a fuller object (a name, a country, coordinates); here it is exactly the identifier, carrying the same UN/LOCODE shape the README names as continuous with the REST and gRPC sites' `Location` type, without the surrounding object. A `HandlingEvent` says where something happened in the one form a client needs to show it on a map or a manifest line: the code itself.

**Route**, **Leg**, and **Operation** are domain nouns this site shares with its siblings but that this contract does not carry. A `Route`'s legs and carriers explain how a booking's cargo is scheduled to move; a `HandlingEvent` records that something already happened, not what was scheduled to happen next, so a leg's carrier or a route's full itinerary has no field to occupy on this message. `Operation` — the async long-running-job pattern the gRPC sibling site uses for work like route recomputation — has no analog on this feed at all, because every `HandlingEvent` push is already the completed fact, not a job a client polls to see finished. Readers who want a route's shape or an async job's lifecycle find them defined where they are owned: the REST and gRPC sites' own chapters.

{% include excalidraw.html file="04-domain-model" alt="Domain model diagram with Booking and Cargo on the left, Route and Leg in the center, Location on the right, and HandlingEvent at the bottom center connecting to all of them: Booking has one or more Cargo, Booking follows a Route, Route is composed of Legs, each Leg has an origin and destination Location, HandlingEvent is recorded against a Cargo and belongs to a Booking by id, HandlingEvent occurred at a Location, and HandlingEvent optionally carries a Money amount. A note states HandlingEvent is the only noun this feed pushes; the rest travel inside it as ids and values, never as nested objects." caption="Figure 4.2 — The domain model: what a HandlingEvent names, versus what it carries as plain identifiers and values." %}

## Event vocabulary

`HandlingEventType` is the enum naming what kind of event occurred, and `contracts/asyncapi.yaml` defines exactly eight members:

| Member | What it records |
|---|---|
| `HANDLING_EVENT_TYPE_UNSPECIFIED` | The zero value. Never sent by the server — it exists only so the enum has a safe default on deserialization, the same `*_UNSPECIFIED`-zero-value convention the gRPC site's `BookingState` enum uses. |
| `RECEIVE` | Cargo is received into custody at the origin — gated in at a terminal, handed off from a shipper. |
| `LOAD` | Cargo is loaded aboard a vessel for a leg of its route. |
| `UNLOAD` | Cargo is unloaded from a vessel at an intermediate or final port. |
| `CUSTOMS` | Cargo is held or cleared by a customs authority. |
| `CLAIM` | Cargo is claimed at destination by the consignee or their agent. |
| `HOLD` | Cargo is placed on hold for a reason other than customs — a documentation issue, a payment hold, a damage inspection. |
| `DELIVERED` | Cargo reaches its final destination and the booking's handling is complete. |

The `*_UNSPECIFIED` member is easy to misread as "an event type nobody picked." It is the opposite: it is the value a deserializer falls back to if a field is missing or a future member this schema doesn't yet know about arrives, so that "unspecified" is always a distinguishable, checkable state rather than a null that crashes a switch statement or a client treating an unrecognized event as whatever the zero integer happens to map to. A client branching on `eventType` should treat `HANDLING_EVENT_TYPE_UNSPECIFIED` as a signal that something is wrong with the message or that the schema evolved out from under it, never as a seventh ordinary kind of event alongside the other seven.

Two fields on `HandlingEvent` carry time, and the gap between them is itself domain-meaningful rather than incidental: `occurredAt` is when the event physically happened, `registeredAt` is when the system recorded it, and `registeredAt` is always greater than or equal to `occurredAt`. A customs hold opened at a port at 9:12 AM local time might not reach a keyboard until a paper manifest is processed hours later; the contract keeps both timestamps rather than collapsing them into one, because a client computing "how stale is my view of this booking" needs `occurredAt`, while a client auditing "when did our system learn about this" needs `registeredAt`, and conflating them would answer neither question correctly.

`voyageNumber` is present only on events tied to a specific sailing — typically `LOAD` and `UNLOAD` — and absent on events like `CUSTOMS` or `CLAIM` that have no voyage to reference. A client checking for `voyageNumber` on a `CUSTOMS` event and finding it missing is reading the contract correctly, not encountering a bug.

## Money as a decimal string

`amount`, when present on a `HandlingEvent`, is typed as `Money` — a string matching `^\d+\.\d{2}$`, like `"125.00"`, never a JSON number. This is the same convention the REST site's JSON Schema and the gRPC site's Protobuf `Money` type both commit to, carried over to this feed's AsyncAPI schema rather than re-decided from scratch, because the reason behind it doesn't change with the transport.

JSON numbers are IEEE 754 doubles, and a double cannot represent every decimal fraction exactly — `0.1 + 0.2` famously fails to equal `0.3` in a floating-point representation, because neither `0.1` nor `0.2` has an exact binary fraction. A customs duty of `"245.00"` serialized as the JSON number `245.00` round-trips correctly today, on this parser, in this language; the risk isn't that it breaks immediately, it's that some combination of client language, serialization library, and downstream arithmetic eventually introduces a cent of drift that nothing in the wire format would have caught, because the wire format itself — a JSON number — has no way to assert "this must be exact." A string sidesteps the question entirely: `"245.00"` means exactly `245.00`, parsed by a decimal type on whichever side reads it, with no binary representation in between to lose precision to.

This feed never carries a currency code alongside `Money`: the contract's own schema description states the amount is reported in the booking's quoted currency, which this feed is not the system of record for. A client that needs to render `"245.00"` with a currency symbol gets the currency from the booking it already holds, not from this event. That is one more instance of the same division of labor that keeps surfacing in this chapter: this feed pushes notice that something happened and a minimal set of values describing it, and leans on the booking service for the fuller context those values are interpreted against.

## How the socket relates to the REST booking service: the seam

Chapter 1 made the case against polling the booking service for a status that has not changed; this section says precisely what replaces the poll and what does not. The REST booking service remains the one place a `Booking`'s and `Cargo`'s full current state lives — this feed is not a second database holding a competing copy of that state, and it is not a cache that a client could query for "what is true right now" instead of calling the booking service. A client's correct sequence is: call the booking service once to get the booking's current state, open the handling-event socket to learn about every change from that point forward, and never call the booking service again to check whether something changed — that single question is what the socket answers instead.

That division draws a sharp line around what this feed is for. A client that disconnects and reconnects does not get the events it missed replayed automatically from this contract alone — `contracts/asyncapi.yaml` defines no replay or catch-up semantics, no "give me everything since event X" operation, and no persisted history a client can request. A client that needs to reconcile a gap left by a disconnect calls the booking service's own read endpoint to re-fetch current state, the same call it made to seed its initial view, and resumes watching the socket from there. Chapter 15 and Chapter 16 return to this exact gap and build two different answers to it — one stateless, one Kafka-backed — but this chapter's job is only to state what the contract as written does and doesn't promise: a live push of what happens next, not a durable log a client can rewind.

The seam also runs through authorization. The channel's connection parameters — the server description in `contracts/asyncapi.yaml` — carry a bearer token as a query parameter and advertise the `handling-events.v1` subprotocol; a connection to `/ws/v1/bookings/{bookingId}/handling-events` is a request to watch one specific booking's events, and whatever system issues that token has to agree the caller is allowed to watch that specific `bookingId` before the handshake completes. That authorization decision almost certainly consults the same identity and permission data the REST booking service already checks on its own `GET /bookings/{bookingId}` — a customs broker who can't read a booking over REST has no business watching its events over a socket either. Chapter 17 is where the token format and validation logic get a real specification; this contract treats the token as an opaque string, because naming the seam here doesn't require closing it yet.

## On the wire

Here is one real `HandlingEvent` message exactly as `contracts/asyncapi.yaml` shapes it — a customs hold recorded against one piece of cargo, with a duty amount attached and no voyage number, because a customs event isn't tied to a specific sailing:

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
| `eventId` | This event's own identifier, `evt_` prefix plus a ULID. Unique per event, never reused. |
| `bookingId` | The booking this event belongs to. Matches the channel's `{bookingId}` path parameter — a client only ever receives events for the booking it connected to watch. |
| `cargoId` | The specific piece of cargo the event was recorded against, distinct from the booking as a whole. |
| `eventType` | One of the eight `HandlingEventType` members. `CUSTOMS` here — cargo held or cleared by a customs authority. |
| `location` | A UN/LOCODE string naming where the event happened. `USNYC` is the Port of New York/Newark. |
| `occurredAt` | When the hold was physically opened, in the shipping yard's own clock. |
| `registeredAt` | When the system recorded it — two minutes and 33 seconds after `occurredAt` here, a realistic gap for an event keyed in shortly after it happened rather than in the same instant. |
| `voyageNumber` | Absent. `CUSTOMS` events aren't tied to a specific sailing, so this field is correctly omitted rather than sent as `null` or an empty string. |
| `amount` | `"245.00"` — a customs duty assessed against this event, as a decimal string, no currency code, interpreted against the booking's own quoted currency. |

Every field name, every enum member, and every pattern above is copied directly from `components.schemas` in `contracts/asyncapi.yaml` — there is no field on this message that chapter prose introduces and the contract doesn't.

## Where this goes next

This chapter named the nouns in prose: `Booking` and `Cargo` as identifiers, `Location` as a UN/LOCODE string, `Money` as a decimal string, `HandlingEventType`'s eight members, and the seam that keeps the REST booking service as the single source of truth this feed never duplicates. Chapter 5 takes that same vocabulary and gives it a formal AsyncAPI 3 contract — the file this chapter has already been quoting from directly, `contracts/asyncapi.yaml` — and shows how both the Quarkus and Python stacks generate their message types from one `components.schemas.HandlingEvent` definition rather than two independently hand-written ones. Chapter 6 then works through message design questions this chapter deferred, like why `HandlingEvent` stays flat instead of nesting a `Location` or `Money` object, and Chapter 7 covers what happens to this exact schema the day a new field needs to be added without breaking a client built against today's shape.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>This feed carries one noun, <code>HandlingEvent</code>, and treats everything else in the shared shipping/cargo glossary as context the REST booking service owns and this socket only references by id or value. <code>bookingId</code> and <code>cargoId</code> stay as identifiers rather than growing into embedded <code>Booking</code> and <code>Cargo</code> objects, <code>Location</code> stays a bare UN/LOCODE string rather than a richer object, and <code>Route</code>, <code>Leg</code>, and <code>Operation</code> don't appear on this message at all. That keeps every event small and cheap to push at the volume a live feed implies, and it keeps exactly one system — the booking service — answerable for what a <code>Booking</code> or <code>Cargo</code> currently looks like. The cost is real: a client that wants more than an event's own fields has to go back to the booking service for it, and a client that misses events during a disconnect gets no replay from this contract alone. Both are trade-offs accepted for a feed whose only job is telling a watching client that something changed, the instant it did — not re-deriving or caching the fuller state the booking service already owns correctly.</p></div>
