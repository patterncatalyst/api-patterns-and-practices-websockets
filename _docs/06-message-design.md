---
title: "Message Design"
order: 6
part: "Contract-first for Sockets"
description: "One flat handling-event message, a discriminator enum and four field shapes that both stacks deserialize identically."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why `HandlingEvent` is one flat schema instead of an envelope, and name the condition under which an envelope pays for itself.
- Justify an `eventType` discriminator over one AsyncAPI message per event kind.
- Apply four field-shape conventions (prefixed identifiers, dual timestamps, decimal-string `Money`, a never-sent `*_UNSPECIFIED` zero value) and state the failure each prevents.
- Tell a field the schema doesn't define yet from one that is defined but absent on a given message.
- Keep a Java `record` and a Pydantic model deserializing the same message identically.

## Why this matters

A socket has no request and response to frame a payload. Every message the server pushes has to carry enough context to be useful on its own, in whatever order it arrives, to a client that may have missed the one before. Message design on a socket asks what a client needs, with nothing else to go on, to act on this message correctly.

## Envelope and payload: one flat object

Many WebSocket tutorials reach for an explicit envelope: a wrapper with a `type`, a `timestamp`, a `correlationId` and a nested `data` field. REST and gRPC don't need one because the transport supplies it: an HTTP response has a status line and headers, and an RPC has a method name, metadata and status. A WebSocket's status line and headers belong to the one-time upgrade, not to the frames after it. Whatever an envelope would carry has to live in the message body, if it is needed at all.

`contracts/asyncapi.yaml` keeps one flat `HandlingEvent` object. `eventId`, `eventType`, `occurredAt` and `registeredAt` do an envelope's job (identity, discrimination, timing) at the same level as `bookingId`, `location` and `amount`, the fields that say what happened. Envelope and payload are roles the nine fields play, not a nesting the JSON has. A client reads one object and finds both.

{% include excalidraw.html file="06-message-envelope" alt="One flat JSON object, HandlingEvent, with two overlapping groups drawn inside it. The envelope-like group holds eventId, eventType, occurredAt and registeredAt. The payload group holds bookingId, cargoId, location, voyageNumber and amount. A note states there is no wrapper object on the wire." caption="Figure 6.1: the contract keeps one flat message; envelope and payload are roles nine fields play, not a nesting the JSON has." %}

An explicit envelope pays for itself when a channel carries several distinct message families and a dispatcher has to branch before it knows which schema to parse against. That means several AsyncAPI `messages` on one channel, not variations of one schema. This channel carries one message type, so a wrapper would add an object to allocate and unwrap on every message, on both stacks, for nothing.

## One message or many: the eventType discriminator

`HandlingEventType` has seven kinds (`RECEIVE`, `LOAD`, `UNLOAD`, `CUSTOMS`, `CLAIM`, `HOLD`, `DELIVERED`) plus the zero value `HANDLING_EVENT_TYPE_UNSPECIFIED`, which the server never sends. All seven ride the same schema, and `eventType` is what a consumer switches on:

```yaml
      enum:
        - HANDLING_EVENT_TYPE_UNSPECIFIED
        - RECEIVE
        - LOAD
        - UNLOAD
        - CUSTOMS
        - CLAIM
        - HOLD
        - DELIVERED
```

The alternative is one AsyncAPI message per kind (`ReceivedEvent`, `LoadedEvent`, `CustomsEvent`), supported natively through multiple `messages` entries on a channel. It buys per-kind type safety: `LoadedEvent` could require `voyageNumber`, and `CustomsEvent` could omit it.

{% include excalidraw.html file="06-one-vs-many-messages" alt="Two designs side by side. Left, the chosen one: a single HandlingEvent message with arrows fanning to four groups of event kinds, labeled eventType discriminates. Right, the rejected one: a dashed box, one AsyncAPI message per event kind, fanning to dashed per-kind schemas." caption="Figure 6.2: same seven event kinds either way; the discriminator puts the branching in one enum instead of seven schemas." %}

| | One schema and a discriminator | One schema per kind |
|---|---|---|
| Adding an eighth kind | One enum value and one new `switch` arm | A new message definition, a new channel reference and new generated types in both stacks, released together |
| Staying in sync across stacks | One shape | Seven shapes |
| Per-kind required fields | Optional in the shared schema | Required where they apply |

The tightening of per-kind schemas is real, but this domain doesn't need it. Every conditionally required field (`voyageNumber` for `LOAD` and `UNLOAD`, `amount` for `CUSTOMS`) is already optional in the shared schema.

## Field shapes that survive

A deployed client has no way to learn that a field changed meaning, so choose shapes that won't need to. `HandlingEvent` reuses four from the shared glossary of the REST and gRPC books.

**Identifiers carry their type.** `eventId` matches `^evt_[0-9A-Za-z]{26}$`, `bookingId` matches `^bkg_[0-9A-Za-z]{26}$` and `cargoId` matches `^crg_[0-9A-Za-z]{26}$`. A bare ULID looks like any other ULID, so a client that swaps a booking and a cargo finds out only when a lookup fails downstream. The prefix makes the mistake visible in the string, and all three transports share one set of identifiers.

**Two timestamps answer two questions.** `occurredAt` is when the event physically happened and `registeredAt` is when the system recorded it. `registeredAt` is always greater than or equal to `occurredAt`, and they differ whenever registration is delayed, such as a paper manifest keyed in later. One `timestamp` field forces a choice between two true facts, and whichever a client assumes will be wrong for a delayed event.

**Money is a decimal string.** `amount` matches `^\d+\.\d{2}$`: `"125.00"`, not the JSON number `125.00` and not integer cents:

```yaml
      pattern: '^\d+\.\d{2}$'
      examples:
        - '125.00'
```

JSON numbers are IEEE 754 doubles, and binary floating point can't represent most decimal fractions exactly. A numeric `Money` field looks fine in every manual test and drifts by fractions of a cent under traffic. A string never asks a float to hold the value; parsing into `BigDecimal` or Python's `Decimal` is the consumer's job.

**Enums get an explicit zero value.** JSON has no default for an enum, yet a deserializer in a language with enums has to pick something when it meets a value it doesn't recognize. If that is the first declared member, an unrecognized or missing value silently becomes whatever is declared first. A documented `UNSPECIFIED` that the server never sends makes one appearing client-side unambiguous evidence of a bug, a contract mismatch or a corrupted message, not a `RECEIVE` event relabeled by accident.

**Optional fields stay absent, not defaulted.** `voyageNumber` is absent on `CUSTOMS` and `CLAIM` and present on `LOAD` and `UNLOAD`. `amount` is absent unless the event carries a charge. A sentinel like `""` or `"0.00"` is a trap: a client summing every `amount` would fold a stray `"0.00"` from each `CUSTOMS` event into the total as a real zero-dollar charge, which is a different fact from "no charge".

The fixture both stacks replay shows the optional fields where they apply, a `LOAD` with a voyage and a `CUSTOMS` with a fee:

```json
  {
    "eventId": "evt_01HZY3M2W9Y5E8R7C3P0D1U6F9",
    "bookingId": "bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A",
    "cargoId": "crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5",
    "eventType": "LOAD",
    "location": "USNYC",
    "voyageNumber": "0042E",
    "occurredAt": "2026-01-15T14:30:00Z",
    "registeredAt": "2026-01-15T14:30:03Z"
  },
  {
    "eventId": "evt_01HZY3M3X0Z6F9S8D4Q1E2V7G0",
    "bookingId": "bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A",
    "cargoId": "crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5",
    "eventType": "CUSTOMS",
    "location": "NLRTM",
    "amount": "125.00",
    "occurredAt": "2026-01-18T09:15:00Z",
    "registeredAt": "2026-01-18T09:15:10Z"
  }
```

Compare a message that makes the opposite choice on each point:

| Choice | Failure it invites |
|---|---|
| `"type": "load"` with no `UNSPECIFIED` member | A future event kind has no safe fallback: a strict deserializer throws, a lenient one picks an arbitrary default and says nothing |
| Bare UUIDs for `id`, `booking`, `cargo` | Swapping `booking` and `cargo` produces no symptom until a lookup against the wrong collection fails |
| One `when` instead of `occurredAt` and `registeredAt` | No way to tell afterward which moment it means |
| `"loc": "Rotterdam"` instead of a UN/LOCODE | Ambiguous (which facility) and unparseable against the `Location` pattern |
| `"charge": 125.0` as a JSON number | The float drift above, now summed across thousands of events |

## Text now, Protobuf alongside

The message declares `contentType: application/json`, and the decimal-string `Money`, prefixed IDs and string-named enum values all assume a text format. JSON is debuggable with browser dev tools or `wscat`, every language has a parser loaded, and a schema mismatch fails loudly. Protobuf wins on message size and parse cost, which matter once throughput or latency budgets do.

`contracts/handling-event.proto` already encodes the same fields in binary, and the `Sec-WebSocket-Protocol` value `handling-events.v1+protobuf` selects it. The shapes survive the move with one change: the enum zero value becomes a varint `0`, readable by name only in the `.proto` file. The `evt_` prefix still protects code from mixing up ids, but nobody reads it off a binary capture the way they read it in a dev tools Network tab. The timestamps, `amount` and `location` stay plain `string` fields rather than `google.protobuf.Timestamp`, so a value decoded from either encoding is byte-for-byte the same string.

## Nullability and forward compatibility

Two kinds of absence are easy to conflate and expensive to conflate wrong: a field the schema version never defined, and a field defined but unset on this message. `voyageNumber` and `amount` are the second kind: typed, sometimes absent, a normal code path. The `required` list bounds the checking. Those seven fields are on every message, so a client reads them without a null check, and every other field needs one.

The first kind of absence is a newer schema reaching an older client. Because the message already treats unset fields as routine, a new optional field such as a hypothetical `containerTemperature` arrives absent on every older event, and a client that handles `voyageNumber`'s absence has no new failure mode to learn. A schema that treated every field as always present would have no habit for a new field's absence, and each addition would raise whether old clients crash.

## Two stacks, one message

Both stacks must deserialize the feed identically: the same field values, the same enum member and the same set of present fields. That is easiest when the wire shapes are already the common denominator of both type systems.

- Strings stay strings. Neither stack parses `amount` into a float.
- Absent optional fields become `null` in Java and `None` in Python, not a type-specific sentinel. Both stacks omit them from the frame instead of sending `null`.
- Enum handling is where the libraries diverge, so state the behavior explicitly instead of trusting each default. Jackson fails on an unrecognized enum string unless configured to fall back to a default member (`@JsonEnumDefaultValue` with `READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE`), and Pydantic rejects it unless a validator or default says otherwise. The examples configure neither fallback, so both stacks reject a value outside the contract's enum instead of relabeling it.

The Quarkus side is a record that mirrors the schema field for field. `@JsonInclude(NON_NULL)` omits absent optionals:

```java
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HandlingEvent(
        String eventId,
        String bookingId,
        String cargoId,
        HandlingEventType eventType,
        String location,
        Instant occurredAt,
        Instant registeredAt,
        String voyageNumber,
        String amount) {
}
```

On the Python side the Pydantic `HandlingEvent` is generated from the schema extracted from the contract and regenerated on every build. It isn't hand-edited, so its optionality can't drift from the contract.

> **Decision**
>
> Keep `HandlingEvent` as one flat, reused message discriminated by `eventType`: prefixed IDs, two timestamps, `Money` as a decimal string, an explicit `*_UNSPECIFIED` zero value, and every field optional unless every event kind has it. Reach for a multi-schema envelope only when a channel carries distinct message families with no shared shape to discriminate within.

> **🤖 Explore with your agent**
>
> "Review contracts/asyncapi.yaml and examples/part3-handling-events/fixtures/handling-events.json against the message-design rules: every id prefixed (evt_, bkg_, crg_), occurredAt and registeredAt both present with registeredAt not earlier than occurredAt, amount a decimal string, optional fields absent instead of defaulted, and no wrapper object. Report each violation with its line, or say there are none, then run ./verify.sh in examples/part3-handling-events."
>
> Check: the review lists no violations and `./verify.sh` prints `PASS:`.

## Build, run, observe

The message lives in `contracts/asyncapi.yaml`, and both stacks replay `fixtures/handling-events.json` from the shared example in `examples/part3-handling-events`:

```bash
npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml
cd examples/part3-handling-events
./verify.sh
```

`verify.sh` brings up Quarkus on port 8080 and Python on 8081, captures the first frame each pushes on `/ws/v1/bookings/{bookingId}/handling-events`, validates it against the schema extracted from the contract, and checks that both stacks' frames agree field by field. It prints `PASS:` when they do. Both stacks omit absent optional fields from the frame instead of emitting `null`.

- Change `eventId` in the fixture to a value without the `evt_` prefix: it breaks the contract pattern, the Python stack's generated model raises a validation error when it loads the fixture, and the Quarkus contract test rejects the event against the extracted schema.
- Set `amount` on the `CUSTOMS` event to `"125"`: it breaks the `Money` pattern and is rejected the same way.

## For deeper coverage

- Gregor Hohpe & Bobby Woolf, *Enterprise Integration Patterns* (Addison-Wesley, 2003): the Message, Message Envelope and Document Message patterns behind the roles-not-nesting argument.
- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022): field-level design conventions (identifiers, enumerations, nullability), applied here to one asynchronous message.
- *Cloud Native Design Patterns*, "API Metadata" chapter: the discriminator-versus-schema-per-kind trade-off, generalized across an API surface.
- *Cloud Native Design Patterns*, "Event-Driven" chapter: designing one event shape to survive the event's own evolution.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `components.schemas` and `components.messages` sections `HandlingEvent` is defined under.
