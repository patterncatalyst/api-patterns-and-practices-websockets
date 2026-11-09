---
title: "Binary Protobuf over WebSockets"
order: 19
part: "Performance & Optimization"
description: "A binary Protobuf encoding of the same message, negotiated by subprotocol, about 40 percent smaller than the JSON text frame."
duration: "12 min read"
---

## Learning objectives

By the end of this chapter you can:

- Add a second, binary encoding of `HandlingEvent` with `contracts/handling-event.proto` as a parity-gated twin of the AsyncAPI schema, not a second contract.
- Negotiate JSON or Protobuf through `Sec-WebSocket-Protocol`, with JSON as the fallback.
- Send text or binary frames per connection on Quarkus and Python.
- Catch drift between the proto and the JSON Schema with `scripts/check-proto-parity.py`.
- Explain why a Protobuf field number, not its name, is the wire identity, and why reusing one corrupts data silently.

## Why this matters

`HandlingEvent` so far travels as JSON in a TEXT frame (opcode `0x1`): readable in dev tools, with the field names repeated in every frame. `examples/part5-performance` adds a second encoding of the same message, Protobuf in a BINARY frame (opcode `0x2`), negotiated by the `Sec-WebSocket-Protocol` header the channel already uses for versioning. It drops JWT auth, backpressure and heartbeats so the encoding is the only variable. Both decode to identical field values, and the Protobuf frame measures about 40% smaller.

## A second encoding, not a second contract

The AsyncAPI document stays the source of truth for what the message means. `contracts/handling-event.proto` is the source of truth for its binary encoding. It carries the same seven required fields and two optional ones:

| Field | Number | Notes |
|---|---|---|
| `event_id`, `booking_id`, `cargo_id` | 1, 2, 3 | Prefixed ULID strings |
| `event_type` | 4 | `HandlingEventType` enum |
| `location` | 5 | UN/LOCODE string |
| `occurred_at`, `registered_at` | 6, 7 | RFC 3339 strings |
| `voyage_number` | 8 | `optional string` |
| `amount` | 9 | `optional string` |

Timestamps, locations and amounts stay plain `string` rather than `google.protobuf.Timestamp`, so a value decoded from either encoding is byte-for-byte what JSON carries and no client branches on which encoding it received. The enum's zero value is `HANDLING_EVENT_TYPE_UNSPECIFIED = 0`, proto3's convention. The server never sends it, but it gives a client a safe default for a member added later. Every other member carries a `HANDLING_EVENT_TYPE_` prefix, which buf's `ENUM_VALUE_PREFIX` lint rule requires.

## The parity gate

Two hand-kept descriptions of one message drift. Someone adds `voyageNumber` to the JSON contract and forgets the proto, or renumbers a proto field without checking that the JSON `required` list still lines up. `buf lint` and `buf breaking` check the `.proto` file itself, but they never open `asyncapi.yaml`.

A **parity gate** compares the proto and the JSON Schema extracted from the AsyncAPI document, and fails on any disagreement.

`scripts/check-proto-parity.py` checks three things:

1. **Field names.** Every proto field, converted from `lower_snake_case` to `camelCase`, is a property of `build/handling-event.schema.json`, and the reverse.
2. **Required or optional.** A proto3 `optional` field maps to a property absent from `required`. Every other field maps to a required one.
3. **Enum membership and order.** The enum's members, with the `HANDLING_EVENT_TYPE_` prefix removed except on the zero value, equal `eventType`'s `enum` list in the same order.

The script compiles the proto to a `FileDescriptorSet` with `protoc --descriptor_set_out` and reads it with `google.protobuf.descriptor_pb2`. It needs `protoc` on `PATH`, not `grpcio-tools`.

```bash
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json
python3 -I scripts/check-proto-parity.py
```

A passing run prints `check-proto-parity: PASS` with the field and enum-member counts. A failure names what disagrees.

## Mapping on both stacks

Each stack keeps one small mapper that converts between its native model and the generated Protobuf message, working on the same string values JSON produces. Quarkus calls `.toString()` on each `Instant`, the ISO-8601 form Jackson's `JavaTimeModule` produces. Python works from `model_dump(mode="json", exclude_none=True)` so every value placed in the message is the string the JSON encoding already carries.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    static HandlingEventOuterClass.HandlingEvent toProto(HandlingEvent event) {
        HandlingEventOuterClass.HandlingEvent.Builder builder = HandlingEventOuterClass.HandlingEvent.newBuilder()
                .setEventId(event.eventId())
                .setBookingId(event.bookingId())
                .setCargoId(event.cargoId())
                .setEventType(toProtoEventType(event.eventType()))
                .setLocation(event.location())
                .setOccurredAt(event.occurredAt().toString())
                .setRegisteredAt(event.registeredAt().toString());
        if (event.voyageNumber() != null) {
            builder.setVoyageNumber(event.voyageNumber());
        }
        if (event.amount() != null) {
            builder.setAmount(event.amount());
        }
        return builder.build();
    }
```
```python
def to_proto(event: HandlingEventModel) -> HandlingEventProto:
    """Validated model -> Protobuf message, field VALUES byte-for-byte
    identical to the JSON encoding."""
    data = event.model_dump(mode="json", exclude_none=True)
    kwargs = {
        "event_id": data["eventId"],
        "booking_id": data["bookingId"],
        "cargo_id": data["cargoId"],
        "event_type": _event_type_to_proto(data["eventType"]),
        "location": data["location"],
        "occurred_at": data["occurredAt"],
        "registered_at": data["registeredAt"],
    }
    if "voyageNumber" in data:
        kwargs["voyage_number"] = data["voyageNumber"]
    if "amount" in data:
        kwargs["amount"] = data["amount"]
    return HandlingEventProto(**kwargs)
```

Both mappers translate the bare contract values (`RECEIVE`, `LOAD`) to the prefixed proto enum members and back.

## Frame opcodes and subprotocol negotiation

The opcode tells a receiver how to read a payload before it decodes a byte: `0x1` is UTF-8 text, `0x2` is an opaque binary blob. Protobuf's varint tags and lengths aren't valid UTF-8 in general, so it has to travel as BINARY, and a client must know which parser to hand each frame to. The `Sec-WebSocket-Protocol` header carries that on the upgrade. The contract's `handling-events.v1` is extended with two values:

| Client offers | Server selects | Wire encoding |
|---|---|---|
| `handling-events.v1+protobuf` | `handling-events.v1+protobuf` | Protobuf binary frames (`0x2`) |
| `handling-events.v1+json` | `handling-events.v1+json` | JSON text frames (`0x1`) |
| `handling-events.v1` (bare) | `handling-events.v1` | JSON text frames |
| nothing | none negotiated | JSON text frames |

Both stacks use the same preference order, JSON before Protobuf, so a client that offers several values gets the same encoding from either. Quarkus lists it in `quarkus.websockets-next.server.supported-subprotocols`, and Vert.x picks the first entry the client also offered. Python reimplements the rule in `_select_subprotocol`, because the `websockets` default aborts the handshake with HTTP 400 when a client offers no subprotocol, and a plain browser WebSocket or `websocat` with no `--protocol` has to fall through to JSON. The change is additive, confirmed with `asyncapi diff`.

{% include excalidraw.html file="19-two-encodings-one-message" alt="A client negotiates Sec-WebSocket-Protocol with a server, which chooses plus json or plus protobuf and echoes it on the 101 response. Two branches follow: a JSON text frame at 247 bytes with opcode 0x1, and a Protobuf binary frame at 149 bytes with opcode 0x2, 39.7 percent smaller." caption="Figure 19.1: One HandlingEvent, two wire encodings negotiated by subprotocol. The frame opcode tells the receiver which decoder to use before it reads a byte." %}

## Sending text or binary per connection

The two stacks decide the frame type at different moments. WebSockets Next picks text or binary dispatch at build time, from the `@OnOpen` method's static return type: `Multi<Buffer>` or `Multi<byte[]>` becomes binary, anything else becomes text with Jackson. One method can't declare `Multi<HandlingEvent>` for JSON connections and `Multi<byte[]>` for Protobuf ones. The way around the auto-dispatch is to return `Uni<Void>` and call `sendText` or `sendBinary` explicitly, once per connection, after reading `connection.subprotocol()`.

Python's `websockets` decides per call, from the argument's type: `bytes` sends a BINARY frame, `str` a TEXT frame. One branch per connection is enough.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    @OnOpen
    public Uni<Void> onOpen(@PathParam String bookingId) {
        String subprotocol = connection.subprotocol();
        boolean useProtobuf = SUBPROTOCOL_PROTOBUF.equals(subprotocol);
        List<HandlingEvent> events = feed.events();

        Log.infof("handling-events connection opened bookingId=%s subprotocol=%s encoding=%s; replaying %d fixture event(s)",
                bookingId, subprotocol, useProtobuf ? "protobuf" : "json", events.size());

        Uni<Void> chain = Uni.createFrom().voidItem();
        for (HandlingEvent event : events) {
            chain = useProtobuf
                    ? chain.chain(() -> connection.sendBinary(HandlingEventProtoMapper.toProto(event).toByteArray()))
                    : chain.chain(() -> connection.sendText(event));
        }
        return chain;
    }
```
```python
async def _replay(websocket: ServerConnection) -> None:
    """Pushes the fixture's three HandlingEvents, each as either a Protobuf
    BINARY frame (`ws.send(bytes)`) or a JSON TEXT frame (`ws.send(str)`),
    depending on the subprotocol negotiated for this connection
    (`websocket.subprotocol`, set by `_select_subprotocol` during the
    handshake), never both on the same connection.
    """
    protobuf = _is_protobuf(websocket)
    logger.info(
        "handling-events: replaying fixture subprotocol=%s encoding=%s",
        websocket.subprotocol or "(none)",
        "protobuf" if protobuf else "json",
    )
    for event in sequence():
        if protobuf:
            await websocket.send(to_proto(event).SerializeToString())
        else:
            await websocket.send(event.model_dump_json(exclude_none=True))
```

One naming gotcha. `handling-event.proto` declares no `java_outer_classname`, so `protoc` derives `HandlingEvent` from the file name, collides with the message of the same name, and appends `OuterClass`. The generated class is `shipping.handlingevents.v1.HandlingEventOuterClass`, with the message nested inside it. The proto is shared with the Python `grpcio-tools` generation, so no Java-only option was added to shorten one import.

## What Protobuf costs

| Cost | Detail |
|---|---|
| Readability | A BINARY frame is opaque bytes without the schema. A JSON frame reads in a network inspector or through `jq` |
| Build step | `protoc` must run before the code that uses the generated classes compiles: `io.github.ascopes:protobuf-maven-plugin` at `generate-sources` on Quarkus, `scripts/generate-proto.sh` (`python -m grpc_tools.protoc`) on Python |
| Generator conventions | Generated names such as `OuterClass` leak into application code |

What it buys is fewer bytes and, usually, less CPU to parse them, since integer tags skip the string scanning and escaping JSON needs. Only size is measured here, not CPU. The frame saving matters for a high-volume feed: less bandwidth, lower latency on a congested link, and more headroom before outbound backpressure triggers. A low-volume feed, or one a human reads without tooling, shouldn't pay either cost.

## Field numbers are the contract

A JSON key is a string repeated in every frame, so renaming `eventType` is a schema edit with no ambiguity. A Protobuf field has no name on the wire, only a tag packed with the wire type. `event_type = 4` is identified by the 4. The name lives only in the `.proto` source and generated code.

{% include excalidraw.html file="19-field-numbers-vs-key-names" alt="Two columns. The JSON column lists seven properties as quoted string keys sent in every frame, noting that renaming a key is free. The Protobuf column lists the same seven fields as numbered tags 1 through 7 with no names on the wire, noting that field numbers are the identity and additive only." caption="Figure 19.2: A JSON key can be renamed freely because the string is the identity. A Protobuf field number can never move or be reused, because the integer tag is the wire identity." %}

The proto's header states the rule: field numbers are additive only, and a number is never reused or renumbered, even after its field is removed. Reuse field 8 for a new field after `voyage_number` is deprecated, and an old binary message decodes under the new schema as the new field's value. There is no parse error, because the wire can't tell the old bytes from the new. `buf breaking` at `FILE` level is the check for that mistake. The parity gate keeps the proto from drifting away from what the JSON schema requires or allows, and `buf breaking` watches renumbering. Add fields and enum members, and never repurpose or remove one a connected client reads.

> **Decision**
>
> Protobuf is a second wire encoding of the same message, not a second contract. Mirror `asyncapi.yaml` field for field, keep timestamps and amounts as strings so both encodings decode to the same values, and gate drift with the parity check beside `buf lint` and `buf breaking`. Let the client choose through `Sec-WebSocket-Protocol`, `+json` by default and `+protobuf` opt-in. Use it when a feed's volume makes JSON's per-key overhead a real cost, not as a replacement for the JSON path. Never reuse a shipped field number.

> **🤖 Explore with your agent**
>
> "In examples/part5-performance, add an optional `carrier_code` string as field 10 in contracts/handling-event.proto and a matching optional `carrierCode` property in the AsyncAPI schema, then update HandlingEventProtoMapper on Quarkus and mapper.to_proto on Python. Do not reuse or renumber any existing field, and keep the value a plain string so the +json and +protobuf frames decode to identical values."
>
> Check: `python3 -I scripts/check-proto-parity.py` prints PASS, then `bash examples/part5-performance/verify.sh` still compares the two encodings as identical on ports 8090 and 8091.

## Build, run, observe

```bash
bash examples/part5-performance/verify.sh
```

For each stack (Quarkus on `:8090`, Python on `:8091`), `verify.sh` offers `handling-events.v1+json` and schema-validates the first TEXT frame. It reopens with `handling-events.v1+protobuf`, decodes the BINARY frame with a stub generated from the proto, converts it to the same JSON-shaped dict, and checks that every field equals the JSON path. It then checks that the Protobuf frame is strictly smaller and that a raw handshake echoes the offered subprotocol for both `+json` and `+protobuf`. The parity gate runs last. The script prints `ok, ` per check and `PASS: ` at the end.

```
lib.sh: quarkus JSON frame size: 247 bytes
lib.sh: quarkus Protobuf frame size: 149 bytes
lib.sh: ok, quarkus: Protobuf (149B) < JSON (247B), 39.7% smaller
```

The three fixture event types shrink by the same margin:

| Event | JSON | Protobuf | Smaller |
|---|---|---|---|
| `RECEIVE` | 247 bytes | 149 bytes | 39.7% |
| `LOAD` (has a voyage number) | 267 bytes | 156 bytes | 41.6% |
| `CUSTOMS` (has an amount) | 265 bytes | 157 bytes | 40.8% |

The saving comes from every field paying JSON's per-key string cost and Protobuf's one-byte tag instead.

- Offer no subprotocol: the first frame is TEXT JSON, and the handshake still succeeds.
- Add a field to the proto and not to the JSON Schema: the parity check fails naming the field.
- Change the order of the enum members on one side: the parity check fails on order.

## For deeper coverage

- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026): encoding formats and schema evolution behind the additive-only field-numbering rule.
- Clément Jean, *gRPC Go for Professionals* (Packt, 2023): the Protocol Buffers language, field numbering and schema evolution.
- *Cloud Native Design Patterns*, "Protocols in Depth" chapter: binary versus text wire trade-offs for a contract served in more than one encoding.
- *Cloud Native Design Patterns*, "Versioning & Evolution" chapter: the non-breaking-change discipline applied to a proto contract beside the AsyncAPI one.
- [Protocol Buffers documentation](https://protobuf.dev/): the proto3 language reference for field numbers, `optional` and enum conventions.
