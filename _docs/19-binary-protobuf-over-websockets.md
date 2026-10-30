---
title: "Binary Protobuf over WebSockets"
order: 19
part: "Performance & Optimization"
description: "Carrying binary Protobuf frames over a WebSocket instead of JSON text frames."
duration: "16 min read"
---

## Learning objectives

By the end of this chapter you can:

- Add a second, binary wire encoding for `HandlingEvent` with `contracts/handling-event.proto` as a hand-kept, parity-gated twin of `asyncapi.yaml`, not a second contract.
- Negotiate JSON versus Protobuf through `Sec-WebSocket-Protocol` subprotocol values (`handling-events.v1+json` / `+protobuf`), with JSON as the safe fallback for a client that offers neither.
- Encode and decode `HandlingEvent` identically on Quarkus (`HandlingEventProtoMapper`) and Python (`mapper.to_proto`), keeping timestamps and amounts as plain strings so either encoding decodes to byte-for-byte identical values.
- Run `scripts/check-proto-parity.py` to catch field-name, required/optional, and enum-order drift between the proto and the JSON Schema that `buf lint`/`buf breaking` can't see.
- Explain why a Protobuf field number, not its name, is the wire identity, and why reusing one is a silent data-corruption risk rather than a build-time error.

## Why this matters

Every chapter before this one pushed `HandlingEvent` as JSON: human-readable field names, quoted strings, no compression, one WebSocket TEXT frame (opcode `0x1`) per event. That's the right default: a client opens dev tools, reads the frame, and understands it without a decoder. `examples/part5-performance` forks part4's connection example (dropping JWT auth, backpressure, and heartbeats to isolate one variable) and adds a second wire encoding of the *exact same message*: Protobuf, carried in a WebSocket BINARY frame (opcode `0x2`), negotiated through the same `Sec-WebSocket-Protocol` header this site has used for versioning from the start. `contracts/handling-event.proto` is a hand-kept, parity-gated binary twin of `contracts/asyncapi.yaml`'s `HandlingEvent` schema, and `verify.sh` proves, live against both stacks, that the two encodings decode to identical field values while the Protobuf frame measures roughly 40% smaller: the same non-breaking-evolution discipline already established for the JSON side of this contract applies here too.

## A second wire encoding, not a second contract

The header comment on `contracts/handling-event.proto` states the division of labor directly: "The AsyncAPI document stays the single source of truth for the message's MEANING; this file is the single source of truth for its binary ENCODING." That distinction matters: reaching for Protobuf without it risks standing up a parallel contract that drifts from the one everything else in this site already validates against. `handling-event.proto` doesn't define a new `HandlingEvent`; it defines a second way to put the same seven required fields and two optional fields on the wire:

```protobuf
message HandlingEvent {
  string event_id = 1;
  string booking_id = 2;
  string cargo_id = 3;
  HandlingEventType event_type = 4;
  string location = 5;
  string occurred_at = 6;
  string registered_at = 7;
  optional string voyage_number = 8;
  optional string amount = 9;
}
```

Three things about this message are deliberate choices, not defaults. First, `occurred_at`, `registered_at`, `location`, and `amount` stay plain `string` fields rather than typed Protobuf equivalents like `google.protobuf.Timestamp`: the file's header comment is explicit that this is "specifically so the Protobuf-decoded values are byte-for-byte identical to the JSON values a client already parses." A client that only ever sees one encoding or the other sees the same RFC-3339 timestamp string and the same decimal-string amount either way; nothing downstream needs an `if (usedProtobuf)` branch to normalize a `Timestamp` object back into the string format JSON already carries. Second, `HandlingEventType`'s zero value is `HANDLING_EVENT_TYPE_UNSPECIFIED = 0`, proto3's convention for every enum's unused-on-the-wire default; the server never sends it, but it gives a client a safe fallback if a future member it doesn't recognize yet ever arrives. Third, every enum member after the zero value carries a `HANDLING_EVENT_TYPE_` prefix, required by buf's `ENUM_VALUE_PREFIX` lint rule (`contracts/buf.yaml`, `lint STANDARD`), the same posture the gRPC sibling site's own Protobuf contract uses.

None of that changes what a client reads. `RECEIVE`, `LOAD`, `UNLOAD`, `CUSTOMS`, `CLAIM`, `HOLD`, and `DELIVERED` are still the seven event types the shared domain model defines; this chapter only changes how those seven strings, and everything that travels alongside them, get serialized into bytes.

## The proto twin and the parity gate that keeps them in sync

A hand-kept `.proto` file mirroring a hand-kept AsyncAPI schema is exactly the kind of pair that drifts apart in a codebase without a gate watching it: someone adds `voyageNumber` to the JSON contract during a later iteration and forgets the proto side, or renumbers a proto field during a refactor without checking whether the JSON side's `required` list still lines up. `buf lint` and `buf breaking` (`contracts/buf.yaml`) catch problems within the `.proto` file itself (an unprefixed enum member, a field renumbered in a way that breaks wire compatibility), but neither one can see across to `asyncapi.yaml` at all. That's the gap `scripts/check-proto-parity.py` closes. It checks three specific things, not a generic diff:

1. **Field names**: every proto field, converted from `lower_snake_case` to `camelCase`, must appear as a property in `build/handling-event.schema.json` (the JSON Schema `scripts/extract-message-schema.py` extracts from `asyncapi.yaml`), and vice versa. No field exists on one side only.
2. **Required vs. optional**: a proto3 field marked `optional` must correspond to a JSON Schema property that is *not* in the schema's `required` list; every other proto field must correspond to a property that *is* required. `voyage_number` and `amount` are the two fields carrying the `optional` keyword, matching the two JSON properties absent from `required`.
3. **Enum membership and order**: `HandlingEventType`'s members, with the `HANDLING_EVENT_TYPE_` prefix stripped (except on the zero value, which both sides spell out in full), must equal `eventType`'s `enum` list in the JSON Schema, in the same declared order.

The script does this by compiling the `.proto` to a `FileDescriptorSet` with `protoc --descriptor_set_out`, then parsing that with the standard `google.protobuf.descriptor_pb2` types; no `grpcio-tools` install required, only `protoc` on `PATH`. It's a static check, stack-independent, and `verify.sh`'s last step runs it on every invocation:

```bash
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json
python3 -I scripts/check-proto-parity.py
```

A passing run prints `check-proto-parity: PASS — 9 fields, 8 enum members match build/handling-event.schema.json`. A field added to one side and not the other, an enum member added out of order, or a field that moves from required to optional on only one side all fail this script with a line naming exactly what disagrees: a failure mode `buf` alone can never see, because `buf` never opens the AsyncAPI document.

## Frame opcodes and subprotocol negotiation

A WebSocket frame's opcode tells the receiving end how to interpret the payload before it decodes a single byte of it: `0x1` means the payload is UTF-8 text, `0x2` means it's an opaque binary blob. JSON has always traveled as a TEXT frame in this site's examples; Protobuf has to travel as BINARY, because a Protobuf message is a sequence of varint-encoded tags and lengths that isn't valid UTF-8 in the general case. The two opcodes aren't an implementation detail a framework hides; a client has to know, before it reads the first byte of a frame, which parser to hand that frame to. That's exactly the problem solved by reusing a mechanism this site already has: the `Sec-WebSocket-Protocol` header, carried on the upgrade handshake, the same one already used for versioning.

`contracts/asyncapi.yaml` already declared one subprotocol value, `handling-events.v1`. This chapter extends it additively with two more:

| Client offers | Server selects (echoed back) | Wire encoding |
|---|---|---|
| `handling-events.v1+protobuf` | `handling-events.v1+protobuf` | Protobuf **binary** frames (opcode `0x2`) |
| `handling-events.v1+json` | `handling-events.v1+json` | JSON **text** frames (opcode `0x1`) |
| `handling-events.v1` (bare) | `handling-events.v1` | JSON **text** frames, equivalent to `+json` |
| nothing | *(none negotiated)* | JSON **text** frames, the pre-Part-5 default |

Both stacks declare the identical preference order, JSON before Protobuf, so a client that offers more than one value gets the same encoding regardless of which stack it's talking to. Quarkus's `application.properties` spells the list directly: `quarkus.websockets-next.server.supported-subprotocols=handling-events.v1,handling-events.v1+json,handling-events.v1+protobuf`, and Vert.x picks the first entry in that list the client also offered. Python's `ws_server.py` reimplements the same rule by hand in `_select_subprotocol`, because the `websockets` library's own default negotiation aborts the handshake (HTTP 400) when a client offers no subprotocol at all: a behavior this channel's design explicitly avoids, since a plain browser WebSocket or a `websocat` call with no `--protocol` flag has to keep working and fall through to JSON, not get rejected outright.

{% include excalidraw.html file="19-two-encodings-one-message" alt="A client box negotiates Sec-WebSocket-Protocol against a server. An ink emphasis box shows the negotiation choosing either plus json or plus protobuf, echoed back on the 101 response. Below, two branches: the left carries a JSON text frame, opcode 0x1, sendText, shown as a 247 byte JSON object literal; the right carries a Protobuf binary frame, opcode 0x2, sendBinary, shown as a compact byte sequence at 149 bytes, 39.7 percent smaller. A ghost box at the bottom states that verify.sh decodes both and asserts the field values are identical." caption="Figure 19.1: one HandlingEvent, two wire encodings negotiated by subprotocol; the frame opcode tells the receiving end which decoder to use before it reads a single byte." %}

Both the extension of the subprotocol value and the addition of the Protobuf path to `asyncapi.yaml` are additive, verified with `asyncapi diff` to confirm no breaking change: the same non-breaking-evolution discipline established for every other contract change this site has made.

## Encoding and decoding on both stacks

Both stacks keep one small mapper module whose only job is converting between the application's native record/model and the generated Protobuf message, operating on the same string values the JSON encoding already produces. On the Quarkus side, `HandlingEventProtoMapper.toProto` builds a `HandlingEventOuterClass.HandlingEvent.Builder` field by field, calling `.toString()` on each `Instant`, the identical ISO-8601 representation Jackson's `JavaTimeModule` produces for the JSON path, since both rely on `DateTimeFormatter.ISO_INSTANT` underneath. On the Python side, `mapper.to_proto` works from `event.model_dump(mode="json", exclude_none=True)` rather than native Python types, for the same reason stated directly in the module's docstring: operating on JSON-mode values means "every value placed into... the proto message is the EXACT same string the JSON encoding already carries."

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

Both mappers do the same enum-prefix translation `check-proto-parity.py` already verifies statically: `HandlingEventType`'s bare contract values (`RECEIVE`, `LOAD`, ...) map to the proto enum's `HANDLING_EVENT_TYPE_`-prefixed members and back, with the all-prefixed `UNSPECIFIED` value handled as a special case on both sides.

The send path is where each stack's two encodings fork, and it's where WebSockets Next's dispatch model matters. `HandlingEventPerformanceWebSocket`'s class Javadoc documents it directly: WebSockets Next's build-time bytecode generator picks text-vs-binary dispatch from the `@OnOpen` method's *static declared return type* (`Multi<Buffer>`/`Multi<byte[]>` wires to binary, anything else wires to text-with-Jackson), not from each item's runtime type. A single `@OnOpen` method can't declare "`Multi<HandlingEvent>` when this connection negotiated JSON, `Multi<byte[]>` when it negotiated Protobuf," because the framework commits to one dispatch path for the method's whole lifetime before the method body ever runs. The technique for per-connection encoding choice is to bypass the auto-dispatch: return `Uni<Void>` and call `WebSocketConnection#sendText`/`#sendBinary` explicitly, chosen once per connection after reading `connection.subprotocol()`; both are plain sender methods available regardless of how the connection negotiated:

{% include codetabs.html langs="Quarkus|Python" %}

```java
@OnOpen
public Uni<Void> onOpen(@PathParam String bookingId) {
    String subprotocol = connection.subprotocol();
    boolean useProtobuf = SUBPROTOCOL_PROTOBUF.equals(subprotocol);
    List<HandlingEvent> events = feed.events();

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
    protobuf = _is_protobuf(websocket)
    for event in sequence():
        if protobuf:
            await websocket.send(to_proto(event).SerializeToString())
        else:
            await websocket.send(event.model_dump_json(exclude_none=True))
```

Python's native `websockets` library needs none of that: `ServerConnection.send` already dispatches on the Python value's own type at the call site (`bytes` sends a BINARY frame, `str` sends a TEXT frame), so `_replay` branches once per connection on `websocket.subprotocol` and calls `send` with whichever type the chosen path produces. The asymmetry between the two stacks here is a direct consequence of *when* each framework decides the frame type: Quarkus decides it once, at build time, from a type signature; `websockets` decides it per call, at runtime, from the argument's own type. Neither is wrong, but a chapter that only showed the Python side would make binary dispatch look trivial, and one that only showed the Quarkus side would make it look like Protobuf requires framework surgery. It requires neither, in general; it requires knowing which dispatch model the framework in front of you uses.

The second finding worth carrying into any new Protobuf integration is a naming collision, not a dispatch one. `handling-event.proto` declares no `option java_outer_classname`, so `protoc` derives one from the file name: `handling-event.proto` → `HandlingEvent`. That collides with the `HandlingEvent` *message* declared inside the same file, so `protoc` falls back to its standard collision rule and appends `OuterClass`, producing `shipping.handlingevents.v1.HandlingEventOuterClass`, with the actual message nested as `HandlingEventOuterClass.HandlingEvent`. `HandlingEventProtoMapper`'s own Javadoc explains why this wasn't patched away with a Java-only `java_outer_classname` option: the `.proto` file is shared, parity-gated infrastructure also consumed by Python's `grpcio-tools` generation, and adding a Java-specific option purely to shorten one import in one file wasn't judged worth touching governed infrastructure for. A generated class named `FooOuterClass.Foo` whenever a `.proto` file and its top-level message share a name is `protoc`'s standard collision rule at work, not a sign of a broken build.

## What Protobuf costs: CPU and readability

The size win this chapter leads with isn't free, and the trade is one to name precisely rather than wave at. The most visible cost is readability: a JSON TEXT frame can be read directly in a browser's network inspector, logged to stdout, or piped through `jq` without any tooling beyond what's already installed. A Protobuf BINARY frame is opaque bytes until something with the `.proto` schema decodes it: `verify.sh` carries its own throwaway stub generation step purely to turn a captured binary frame back into something `assert_eq` can compare against. Every environment that needs to inspect a Protobuf frame during development or incident response needs that schema and a decoder nearby, where a JSON frame needs nothing but eyes.

The second cost is a build-time dependency neither stack needed before this chapter: a `protoc` compiler (or `grpcio-tools`' bundled copy of one) has to run before the application code that references the generated classes can even compile. Quarkus wires this through `io.github.ascopes:protobuf-maven-plugin` at the `generate-sources` phase; Python's `scripts/generate-proto.sh` runs `python -m grpc_tools.protoc` by hand before the app imports `handling_event_pb2`. Neither is expensive to run, but both add a moving part to the build pipeline that can be stale or missing on a machine that's never built this project before, and, as the `OuterClass` naming collision shows, a generator's own conventions can leak into application code in ways a hand-written JSON model never would.

What Protobuf buys back for those two costs is smaller bytes and, generally, less CPU spent parsing them: a binary format with integer field tags skips the string-scanning, escaping, and whitespace a JSON parser has to do, and the numbers this chapter measures (below) bear that out for size. This example doesn't measure CPU directly: that parsing-cost difference shows up as a number, not just an assertion, once throughput optimization measures latency under real load. But the frame-size reduction alone matters on its own for a high-volume feed: fewer bytes per event means less bandwidth, lower latency on a congested link, and more headroom before a server's outbound buffer backs up under backpressure limits. A low-volume feed, or one where a human needs to read the frame without tooling, has no reason to pay either cost: Protobuf is additive capability for a feed that's outgrown JSON's overhead, not a wholesale replacement for it.

## Field numbers are the real contract

JSON's property names and Protobuf's field numbers do the same job, telling a decoder which value is which, but they fail differently when a schema evolves, and that difference is the reason this chapter's parity gate exists at all. A JSON key is a string, repeated on every single frame; renaming `"eventType"` to `"handlingEventType"` is a one-line change to a schema and every decoder that reads the new key name, with no ambiguity about which value is which as long as the key string itself is unambiguous. A Protobuf field has no name on the wire at all: only a tag, a small integer packed alongside the wire type in the length-delimited encoding. `event_type = 4` means "the fourth field, declared with this specific number" is what identifies the value on the wire; the field's *name* (`event_type`) exists only in the `.proto` source and the code generated from it, never in the bytes a client receives.

{% include excalidraw.html file="19-field-numbers-vs-key-names" alt="Two columns. The left, labeled JSON, lists seven properties as quoted string keys sent with every frame: eventId, bookingId, cargoId, eventType, location, occurredAt, registeredAt, each annotated as a key literal sent every frame, with a note that renaming a key is free. The right, labeled Protobuf, lists the same seven fields as numbered tags 1 through 7 with their snake case names, each annotated as a one-byte tag with no name on the wire, with a note that field numbers are the wire identity, additive only, same as Chapter 7's JSON discipline. A caption states that check-proto-parity.py fails the build the moment either side adds, removes, or reorders a field the other side doesn't also carry." caption="Figure 19.2: a JSON key can be renamed freely because the string itself is the identity; a Protobuf field number can never move or be reused, because the integer tag, not the field's name, is the wire identity." %}

That difference is exactly why `contracts/handling-event.proto`'s header comment states the field-numbering rule in such direct terms: "Field numbers are additive-only: once assigned, a number is never reused or renumbered, even if the field it names is later removed." Reusing field 8 for a new field after `voyage_number` is deprecated would mean an old binary message, serialized before the change, decodes under the new schema as if it carried the new field's value: a data-corruption bug with no parse error to flag it, because the wire format has no way to tell "this is `voyage_number`'s old bytes" from "this is the new field's bytes" once they share a tag. `buf breaking` (`contracts/buf.yaml`, `FILE`-level compatibility) is the automated gate against exactly that mistake, governing `handling-event.proto` the same way the gRPC sibling site's own `buf breaking` gate governs its contract.

This is the same non-breaking-evolution discipline already established for the JSON side of this contract: add a field, add an enum member, never repurpose or remove something an already-connected client reads, stated here in terms specific to how Protobuf breaks: not by renaming a key (which Protobuf barely has, on the wire), but by renumbering or reusing a tag. A team adopting Protobuf without internalizing that field numbers, not field names, are the thing that must never move is the team that reuses a deprecated number six months later and ships a decoder that misreads old data as a different field with no warning. The parity gate this chapter introduced doesn't prevent that mistake by itself (`buf breaking` is the tool watching for it), but it does guarantee that whatever numbering scheme the proto side settles on, it never drifts out of step with what the JSON schema requires or allows, so a change reviewed on one side can't invalidate an assumption baked into the other without either gate catching it.

## On the wire

`examples/part5-performance/verify.sh` is the harness that turns every claim in this chapter from a comment in a `.proto` file into something asserted against two live processes. For each stack (Quarkus on `:8090`, Python on `:8091`) it runs the identical four-step check:

```
=== verifying stack 'quarkus' at localhost:8090/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events ===
--- JSON path (+json subprotocol): first frame is TEXT, schema-valid, RECEIVE ---
lib.sh: quarkus JSON frame size: 247 bytes
--- Protobuf path (+protobuf subprotocol): first frame is BINARY, decodes to the SAME values ---
lib.sh: quarkus Protobuf frame size: 149 bytes
lib.sh: ok — quarkus JSON vs Protobuf field values: JSON and Protobuf decoded field values are identical
--- Size: Protobuf frame strictly smaller than the JSON frame ---
lib.sh: ok — quarkus: Protobuf (149B) < JSON (247B), 39.7% smaller
--- Subprotocol echo: server echoes the offered subprotocol in the 101 response ---
```

First, `verify.sh` offers `handling-events.v1+json`, reads the first frame as TEXT with `websocat`, and schema-validates it against `build/handling-event.schema.json`: the same schema every other chapter's JSON path validates against. Second, it reopens the connection offering `handling-events.v1+protobuf`, captures the first frame as BINARY, decodes it with a Protobuf stub generated once from `contracts/handling-event.proto`, converts the decoded message into the same JSON-shaped dict `proto_to_dict`/`HandlingEventProtoMapper.fromProto` would produce, and schema-validates *that* against the identical schema, proving the Protobuf path produces a value indistinguishable in shape from the JSON path, not merely something that happens to parse. Third, it asserts every field value from the two decoded frames is deeply equal, via `assert_json_objects_eq`: one message, two encodings, not two independently-valid messages that happen to agree by coincidence. Fourth, it asserts the Protobuf byte count is strictly smaller than the JSON byte count for the same event, computing and printing the exact reduction percentage.

The measured sizes for the three event types the fixture carries hold the same shape across the board: RECEIVE's single `voyageNumber`/`amount`-less event shrinks from 247 to 149 bytes (39.7%); LOAD, which carries a voyage number, from 267 to 156 (41.6%); CUSTOMS, which carries an amount instead, from 265 to 157 (40.8%). The reduction doesn't come from any one field; it comes from every field paying JSON's per-key string-literal tax and paying none of it in Protobuf's tag-plus-length encoding.

Finally, `verify.sh` hand-rolls the WebSocket opening handshake with Python's stdlib `socket` module (no client library, only raw HTTP) to confirm the server echoes back the exact subprotocol value it was offered, for both `+json` and `+protobuf`, on both stacks. That closes the loop on subprotocol negotiation: not only does each encoding decode correctly, the negotiation that selects between them round-trips through the handshake the way the contract says it should. Run it from the repo root:

```bash
bash examples/part5-performance/verify.sh
```

A passing run prints one final line: both stacks negotiate both subprotocols, decode to identical field values, measure the Protobuf frame strictly smaller, echo the correct subprotocol, and pass the static proto-vs-JSON-Schema parity gate: four independent claims, one `PASS`.

## Where this goes next

This chapter added a second wire encoding to one channel and proved, live, that it's both smaller and faithful to the same contract JSON already carries. What it didn't measure is the thing a smaller frame exists to improve: whether a server pushing thousands of these events per second notices the difference in CPU, memory, or sustained throughput, and where the bottleneck sits once wire size stops being the limiting factor. Throughput optimization picks that question up directly: tuning a socket server for throughput once it carries real load, on top of the exact same `+protobuf`/`+json` choice this chapter built, so the size win proven here becomes a measured latency and messages-per-second number rather than a byte count alone.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Protobuf is a second wire encoding of the same message, not a second contract: <code>contracts/handling-event.proto</code> mirrors <code>asyncapi.yaml</code>'s <code>HandlingEvent</code> field-for-field, keeping timestamps and amounts as plain strings so a value decoded from either encoding is byte-for-byte identical, and <code>scripts/check-proto-parity.py</code> closes the one gap <code>buf lint</code>/<code>buf breaking</code> can't see: proto-vs-JSON-Schema drift in field names, required/optional split, or enum order. A client selects the encoding via <code>Sec-WebSocket-Protocol</code> (<code>+json</code> default, <code>+protobuf</code> opt-in): reusing the same subprotocol mechanism this site already uses for versioning, not a new negotiation scheme. <code>verify.sh</code> proves the trade live on both stacks: the Protobuf frame measures ~40% smaller for every fixture event and decodes to field values identical to the JSON path, at the cost of a build-time <code>protoc</code> dependency and a frame no longer readable without a schema and a decoder. Reach for it when a feed's volume makes JSON's per-key string overhead a real cost, not as a default replacement for the JSON path every other chapter in this site already uses, and never by reusing a proto field number once it's shipped: a reused tag is a silent misread, not a type error, which is exactly what buf's breaking-change gate and this chapter's field-number discipline exist to prevent.</p></div>

## For deeper coverage

- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026): encoding formats and schema evolution behind the additive-only field-numbering rule `contracts/handling-event.proto` enforces.
- Clément Jean, *gRPC Go for Professionals* (Packt, 2023): the Protocol Buffers language, field numbering, and schema evolution this chapter's `.proto` contract is built on.
- *Cloud Native Design Patterns*, "Protocols in Depth" chapter: binary-versus-text wire tradeoffs for a contract served over more than one encoding.
- *Cloud Native Design Patterns*, "Versioning & Evolution" chapter: the non-breaking-change discipline this chapter applies to a proto contract alongside the existing AsyncAPI one.
- [Protocol Buffers documentation](https://protobuf.dev/): the proto3 language reference behind `handling-event.proto`'s field numbers, `optional` keyword, and enum conventions.
