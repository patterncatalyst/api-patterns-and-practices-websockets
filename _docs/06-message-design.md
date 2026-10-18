---
title: "Message Design"
order: 6
part: "Contract-first for Sockets"
description: "Designing the handling-event message shapes a contract — and both implementations — commit to."
duration: "22 min read"
---

Chapter 5 put `contracts/asyncapi.yaml` in place as the thing both stacks generate from and validate against. This chapter is about what goes inside it: the shape of the `HandlingEvent` message itself, field by field, and the decisions that shape carries that a REST JSON body or a gRPC `.proto` message would make differently — or the same way, for the same reasons. A WebSocket connection has no request/response pair to frame a payload against; every message the server pushes has to carry enough of its own context to be useful standing alone, in whatever order it arrives, to a client that might have missed the one before it. That's what message design means on a socket: not "what fields does this event have" but "what does a client need to know, with nothing else to go on, to act on this message correctly."

## Envelope vs. payload: one flat object, two roles

A lot of WebSocket tutorials reach for an explicit envelope: a wrapper object with a `type`, a `timestamp`, a `correlationId`, and a nested `data` or `payload` field holding the content. The pattern is common enough to name before explaining why `HandlingEvent` doesn't use it. `contracts/asyncapi.yaml` defines one flat schema:

```yaml
HandlingEvent:
  type: object
  properties:
    eventId: {...}
    bookingId: {...}
    cargoId: {...}
    eventType: {...}
    location: {...}
    occurredAt: {...}
    registeredAt: {...}
    voyageNumber: {...}
    amount: {...}
  required: [eventId, bookingId, cargoId, eventType, location, occurredAt, registeredAt]
```

No `data` field, no nested `payload`. `eventId`, `eventType`, `occurredAt`, and `registeredAt` do the job an explicit envelope would otherwise do — identity, discrimination, and timing — but they sit at the same level as `bookingId`, `location`, and `amount`, the fields that describe what happened. "Envelope" and "payload" are roles those nine fields play, not a nesting the JSON has. Figure 6.1 draws the split as a conceptual grouping over one object, because that's what it is: a client parsing this message doesn't unwrap anything to get to the content, it reads one object and finds both kinds of information in it.

{% include excalidraw.html file="06-message-envelope" alt="A single flat JSON object labeled HandlingEvent, with two overlapping conceptual groups drawn inside it rather than as separate nested fields. The envelope-like group contains eventId, eventType, occurredAt, and registeredAt, labeled identity, discriminator, and timing. The payload group contains bookingId, cargoId, location, voyageNumber, and amount, labeled subject and domain content. A dashed bidirectional arrow between the two groups is labeled same object, two roles. A note states there is no separate wrapper object on the wire." caption="Figure 6.1 — The contract keeps one flat message; envelope and payload are roles nine fields play, not a nesting the JSON has." %}

The REST and gRPC sibling sites make a comparable call for a different reason: a REST response's envelope is the HTTP response itself (status code, headers, body), and a gRPC call's envelope is the RPC itself (method name, metadata, status). Neither needs a JSON-level wrapper because the transport already provides one. A WebSocket message has no equivalent — HTTP's status line and headers belong to the one-time upgrade handshake from Chapter 3, not to the frames that follow — so whatever an envelope would carry has to live in the message body if it's needed at all. The contract's answer is to need less of it: a single reused message type (next section) turns most of what a generic envelope buys — "which kind of message is this" — into a single enum field, not a wrapper.

An explicit envelope pays for itself when a channel carries several distinct message families and a dispatcher needs to branch before it knows which schema to parse against — multiple distinct AsyncAPI `messages` on one channel, not variations of one schema. This channel carries exactly one message type, so a wrapper would solve a problem this contract doesn't have, at the cost of an extra object to allocate and unwrap on every message, on both stacks, forever.

## One message or many: the eventType discriminator

`HandlingEventType` is a seven-member enum — `RECEIVE`, `LOAD`, `UNLOAD`, `CUSTOMS`, `CLAIM`, `HOLD`, `DELIVERED` — plus the zero value, `HANDLING_EVENT_TYPE_UNSPECIFIED`, that the server never sends. Every one of those seven kinds rides the same `HandlingEvent` schema; `eventType` is what a consumer switches on to decide what the rest of the message means. `contracts/README.md` names this as a convention: "One reused message shape — `components.messages.HandlingEvent` is defined once and referenced (`$ref`) from both the channel and the operation — never duplicated inline."

The alternative — one AsyncAPI message schema per event kind, `ReceivedEvent`, `LoadedEvent`, `CustomsEvent`, and so on — is a real design, supported natively via multiple `messages` entries on one channel. It buys per-kind type safety: a `LoadedEvent` schema could make `voyageNumber` required since every LOAD event has one, while a `CustomsEvent` schema could omit the field entirely instead of leaving it nullable. Figure 6.2 puts the two approaches side by side.

{% include excalidraw.html file="06-one-vs-many-messages" alt="Two groups compared side by side. On the left, this contract's choice: a single HandlingEvent message box with solid arrows fanning down to four category boxes, RECEIVE, LOAD/UNLOAD, CUSTOMS/CLAIM, and HOLD/DELIVERED, labeled eventType discriminates. On the right, a rejected alternative: a dashed box labeled one AsyncAPI message per event kind, with dashed arrows fanning down to four dashed schema boxes, ReceivedEvent, LoadedEvent, CustomsEvent, and three more schemas. A note below states the same seven event kinds exist either way, and that adding an eighth kind is one new enum value under the chosen design versus a new channel message under the rejected one, in both stacks." caption="Figure 6.2 — Same seven event kinds either way; the discriminator puts the branching in one enum instead of seven schemas." %}

The cost of per-kind schemas shows up at the edges this contract cares most about: evolution and cross-stack consistency. Adding an eighth event kind to the discriminated design is one new enum value and one new `switch`/`match` arm in code already written to expect the discriminator to grow — the kind of additive change Chapter 7 treats as safe by default. Adding an eighth kind to the per-schema design is a new message definition, a new channel reference, and new generated types in both stacks, landing on the same release. DRQ-002 requires both stacks to deserialize this feed identically; one discriminated schema gives them one thing to stay in sync on, where seven schemas give them seven. The per-kind field tightening is real, but this domain doesn't need it badly enough to pay for it: every conditionally required field (`voyageNumber` for LOAD/UNLOAD, `amount` for CUSTOMS or CLAIM) is already optional in the one shared schema, which is the next section's subject.

## Field shapes that survive: IDs, timestamps, Money, enums

Message design is mostly about choosing field shapes that won't need to change meaning later, because a client already deployed against the old meaning has no way to find out it changed. `HandlingEvent` reuses four shapes from the series' shared glossary rather than inventing socket-specific ones.

**Identifiers carry their type in the string.** `eventId` matches `^evt_[0-9A-Za-z]{26}$`, `bookingId` matches `^bkg_[0-9A-Za-z]{26}$`, `cargoId` matches `^crg_[0-9A-Za-z]{26}$`. A bare ULID or UUID is indistinguishable from any other ULID in the codebase; a client that logs an unprefixed ID, or pastes one into the wrong variable, finds out it mixed up a booking and a cargo only when a lookup fails downstream, if it fails at all. The `evt_`/`bkg_`/`crg_` prefix makes the mistake visible in the string itself — the same convention the REST and gRPC sibling sites use for `Booking.id` and `Cargo.id`, carried onto the socket so all three transports share one set of identifiers.

**Timestamps are two fields, not one, because they answer two different questions.** `occurredAt` is when the handling event physically happened; `registeredAt` is when the system recorded it. The contract is explicit that these differ whenever registration is delayed — a paper manifest keyed in after the fact is the example it gives — and that `registeredAt >= occurredAt` always holds. Collapsing these into one `timestamp` field forces a choice between two true facts, and whichever one a client assumes it's getting, it will eventually be wrong for a delayed event — not a corner case in a domain with paper manifests and customs holds.

**Money is a decimal string, never a float.** `amount` matches `^\d+\.\d{2}$` — `"125.00"`, not `125.00` as a JSON number and not `12500` as integer cents. `contracts/README.md` calls this the WebSocket analog of the REST and gRPC sites' Money-as-decimal-string convention, for the same reason the gRPC site's Chapter 3 gives for `string amount` over `double amount` in Protobuf: JSON numbers are IEEE 754 doubles, and `0.1 + 0.2` not equaling `0.3` in nearly every mainstream language is the famous symptom of a general problem — binary floating point can't represent most decimal fractions exactly. A `Money` field that's a JSON number looks fine in every manual test and drifts by fractions of a cent under real traffic, on a value that has a name on an invoice. A decimal string sidesteps the problem by never asking a float to hold the value; parsing it into a fixed-point type (`BigDecimal`, Python's `Decimal`) is the consuming code's job, not the wire format's.

**Enums get an explicit, never-sent zero value.** `HandlingEventType`'s zero member is `HANDLING_EVENT_TYPE_UNSPECIFIED`, matching the `*_UNSPECIFIED` convention the gRPC site's `BookingState` enum uses, for the same reason: JSON has no notion of an enum's default, but a deserializer in a language with enums has to pick something when it meets a value it doesn't recognize, and "the first declared member" is a common default that turns an unrecognized or missing value into whatever happens to be declared first, with no signal that a substitution occurred. Naming that slot `UNSPECIFIED` and documenting that the server never sends it makes an `UNSPECIFIED` showing up client-side unambiguous evidence of a bug — a contract mismatch, a bad fallback, a corrupted message — rather than a real `RECEIVE` event relabeled by accident.

**Optional fields stay nullable, not defaulted to a stand-in value.** `voyageNumber` is absent for events that aren't tied to a voyage — `CUSTOMS`, `CLAIM` — and present for `LOAD`/`UNLOAD`; `amount` is absent unless the event itself carries a charge. Neither is required in the schema, and neither has a sentinel default like `""` or `"0.00"` standing in for "not applicable." A sentinel value is a trap for exactly the kind of code this chapter is trying to prevent: a client that sums every `amount` field across a stream of events, without checking for absence first, folds a stray `"0.00"` from every CUSTOMS event into the total as if it were a real zero-dollar charge — a different fact from "this event has no charge."

## Text vs. binary on the wire: JSON now, Protobuf in Ch19

`contracts/asyncapi.yaml` declares `contentType: application/json` on the `HandlingEvent` message, and every design decision in this chapter — the decimal-string `Money`, the string-prefixed IDs, the string-named enum values — assumes a text format underneath it. That's a choice for this point in the book, not an assumption that JSON is the only format a `HandlingEvent` could ever take. Chapter 19 revisits this exact message, unchanged in meaning, re-encoded as Protobuf, and most of the shapes this chapter defends don't survive the move unchanged.

A Protobuf `Money` settles the string-vs-float argument the same way — `string amount = 1` — but a Protobuf enum's zero value isn't a readable string like `"HANDLING_EVENT_TYPE_UNSPECIFIED"` on the wire; it's a VARINT-encoded `0`, and the human-readable name exists only in the `.proto` file and the generated code around it. An ID prefix like `evt_` stops paying for itself as clearly once the field is binary-framed rather than eyeballed in a dev tools Network tab — it still protects against mixing up an `eventId` and a `cargoId` in code, but a client debugging a raw binary capture doesn't get to read `"evt_01HZY3..."` off the wire the way it can with JSON today. And the two timestamp fields, ISO 8601 strings here, become a `google.protobuf.Timestamp` — two fixed-width integers instead of a parsed string — the same well-known-type substitution the gRPC site's Chapter 4 covers.

None of that argues for Protobuf now. JSON is debuggable with nothing more than browser dev tools or `wscat`, every language already has a JSON parser loaded, and a schema mismatch fails loudly instead of as an opaque byte-offset error. Protobuf's wins — smaller messages, no per-field name repeated on every message, no text-scanning parse — matter most at a scale and latency budget this book hasn't reached yet. Chapter 19 re-specifies this same `HandlingEvent` as a `.proto` message and benchmarks it against the JSON form this chapter builds on, field shape by field shape.

## Nullability, defaults, and forward-compatibility

`HandlingEvent` draws a hard line between two kinds of absence that are easy to conflate and expensive to conflate wrong: a field missing because this schema version never defined it, and a field present in the schema but legitimately unset on this message. `voyageNumber` and `amount` are the second kind — defined, typed, sometimes absent, checked as a normal code path, not an error case. The `required` list — `eventId`, `bookingId`, `cargoId`, `eventType`, `location`, `occurredAt`, `registeredAt` — keeps that checking bounded: those seven fields are guaranteed on every message this contract's version ever produces, so a client reads them without a null check, and everything outside that list needs one.

The first kind of absence — a field this version of the schema doesn't know about yet — is what Chapter 7 is about, and the design choice that sets it up is made here: every field in `HandlingEvent` is additive-safe to introduce later because the message already treats unset fields as routine, not exceptional. A hypothetical `containerTemperature` field, added for a future refrigerated-cargo use case, arrives optional, absent on every event that predates it, and a client that already treats `voyageNumber`'s absence as normal has no new failure mode to learn. A schema that instead treated every field as always-present would have no established pattern for a new field's absence on old messages, and "does this client crash on a message from the new version" becomes a live question every time the schema grows. Designing for nullability from the first message is what makes Chapter 7's versioning a continuation of an existing habit, not a retrofit.

## Designing for the two stacks

DRQ-002 requires the Quarkus WebSockets Next stack and the Python FastAPI/`websockets` stack to deserialize this feed identically — not "compatibly," identically: the same message, parsed on both stacks, produces the same field values, the same enum member, the same notion of which fields are present. That's easiest to meet when the message design itself does the work, rather than leaving it to a mapping layer on one side to paper over a shape mismatch.

A Java `record` and a Pydantic `BaseModel` land on the same representation almost without trying when the wire shapes are already the lowest common denominator across both type systems: a string stays a string (neither stack parses `amount` into a float — both keep it as `BigDecimal`/`Decimal` from a string), an enum unknown to one side degrades to `UNSPECIFIED` instead of throwing, and a missing optional field becomes `null`/`None` rather than a type-specific sentinel. Jackson and Pydantic both support all three behaviors out of the box; the discipline is specifying them explicitly instead of relying on each library's unannotated default, which differs between them (Jackson defaults to failing on an unrecognized enum value; Pydantic's default depends on how the field is typed).

{% include codetabs.html langs="Quarkus|Python" %}

```java
// Quarkus WebSockets Next — a record mirrors the flat schema directly
public record HandlingEvent(
    String eventId,
    String bookingId,
    String cargoId,
    HandlingEventType eventType,
    String location,
    Instant occurredAt,
    Instant registeredAt,
    String voyageNumber,   // null when absent — no sentinel
    String amount          // kept as String; BigDecimal parsing is explicit, not automatic
) {
    @JsonCreator
    public static HandlingEvent fromJson(/* ... */) { /* ... */ }
}

public enum HandlingEventType {
    @JsonEnumDefaultValue HANDLING_EVENT_TYPE_UNSPECIFIED,
    RECEIVE, LOAD, UNLOAD, CUSTOMS, CLAIM, HOLD, DELIVERED
}
```

```python
# Python — Pydantic mirrors the same flat schema, same optionality
class HandlingEventType(str, Enum):
    HANDLING_EVENT_TYPE_UNSPECIFIED = "HANDLING_EVENT_TYPE_UNSPECIFIED"
    RECEIVE = "RECEIVE"
    LOAD = "LOAD"
    UNLOAD = "UNLOAD"
    CUSTOMS = "CUSTOMS"
    CLAIM = "CLAIM"
    HOLD = "HOLD"
    DELIVERED = "DELIVERED"

class HandlingEvent(BaseModel):
    event_id: str = Field(alias="eventId")
    booking_id: str = Field(alias="bookingId")
    cargo_id: str = Field(alias="cargoId")
    event_type: HandlingEventType = Field(
        alias="eventType",
        default=HandlingEventType.HANDLING_EVENT_TYPE_UNSPECIFIED,
    )
    location: str
    occurred_at: datetime = Field(alias="occurredAt")
    registered_at: datetime = Field(alias="registeredAt")
    voyage_number: str | None = Field(alias="voyageNumber", default=None)
    amount: str | None = None  # left as str; Decimal(amount) is explicit at use sites
```

Both sides default an unrecognized `eventType` to `HANDLING_EVENT_TYPE_UNSPECIFIED` instead of raising — `@JsonEnumDefaultValue` on the Java side, a model default on the Python side — so a client running slightly behind the contract's enum growth degrades to "I don't recognize this event kind" instead of crashing the connection. Both keep `amount` as a wire-shaped string instead of eagerly parsing it into a numeric type at deserialization time, keeping the one failure mode (a malformed decimal string) at the call site that converts it, not at every message's construction.

## On the wire

A real `HandlingEvent` push, matching the contract exactly:

```json
{
  "eventId": "evt_01HZY3M1V8X4D7Q6B2N9C0T5E8",
  "bookingId": "bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A",
  "cargoId": "crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5",
  "eventType": "LOAD",
  "location": "NLRTM",
  "occurredAt": "2026-03-14T08:12:00Z",
  "registeredAt": "2026-03-14T08:14:33Z",
  "voyageNumber": "MSC-0417W",
  "amount": "125.00"
}
```

Field by field: `eventId` is this event's own identity, prefixed and ULID-shaped so it sorts chronologically and reads unambiguously in a log. `bookingId` and `cargoId` name what the event is about, prefixed so neither can be mistaken for the other or for `eventId`. `eventType` is `"LOAD"` — a string enum member, not an integer code, so the message is self-describing without a lookup table. `location` is a bare UN/LOCODE string, `"NLRTM"` — no nested `{ "code": "NLRTM", "name": "Rotterdam" }`, because the code is the identifier and a display name is a presentation concern for a lookup table the client already has, not for every event. `occurredAt` and `registeredAt` differ by two minutes here, the ordinary case where a scanner or terminal operator triggers the event and the system records it shortly after. `voyageNumber` and `amount` are present because this LOAD carries a voyage and a handling charge; both would be absent on a CUSTOMS or CLAIM event that doesn't.

A poorly designed variant of the same event, keeping the same facts but making every choice this chapter argues against:

```json
{
  "type": "load",
  "id": "a1b2c3d4-...",
  "booking": "a9f0e1d2-...",
  "cargo": "b3c4d5e6-...",
  "when": "2026-03-14T08:12:00Z",
  "loc": "Rotterdam",
  "voyage": "MSC-0417W",
  "charge": 125.0
}
```

Every change costs something a client eventually pays for. `type: "load"` with no `UNSPECIFIED` member means an unrecognized future event kind has no safe fallback — a strict deserializer throws, a lenient one picks an arbitrary default with no record that it did. `id`, `booking`, and `cargo` are bare UUIDs with no prefix, so a bug that swaps `booking` and `cargo` produces no visible symptom until a lookup against the wrong collection fails downstream. Collapsing `occurredAt`/`registeredAt` into one `when` throws away a distinction the domain depends on — there's no way to tell, after the fact, which moment it refers to. `loc: "Rotterdam"` is a display name instead of a UN/LOCODE, ambiguous (which Rotterdam facility) and unparseable against the shared glossary's `Location` pattern. And `charge: 125.0` is a JSON number — the exact representation problem the Money section opens with, now live in a message a client is going to sum across a feed of thousands.

## Where this goes next

Every design choice in this chapter was made with one eye on Chapter 7: the discriminated `eventType` enum, the optional `voyageNumber`/`amount` fields, and the required-vs-optional split are what make it possible to add an eighth event kind, a new optional field, or a stricter validation rule without breaking a client that's already connected. Chapter 7 names that explicitly — what counts as an additive, safe change versus a breaking one, how the `/ws/v1/...` channel path's version relates to the schema's own evolution, and what a client should do with a field it doesn't recognize.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Keep `HandlingEvent` as one flat, reused message discriminated by `eventType`, with IDs that carry a type prefix, two timestamps instead of one, Money as a decimal string, an explicit `*_UNSPECIFIED` enum zero value, and every non-identity field optional unless every event kind truly has it. None of these are socket-specific inventions — they're the REST and gRPC sibling sites' domain conventions carried onto a channel that has no request/response pair to lean on instead. Reach for a multi-schema envelope only when a channel carries distinct message families with no shared shape to discriminate within; this feed has one family, and the discriminator already does the job a wrapper would.</p></div>
