# Part 5 "Performance" — JSON vs. Protobuf on the same channel

Forks [`examples/part4-connection`](../part4-connection): the same
[`operations.receiveHandlingEvent`](../../contracts/asyncapi.yaml) channel —
one WebSocket connection per booking, server pushing the shared fixture
(`../part3-handling-events/fixtures/handling-events.json`, byte for byte) —
but drops part4's four connection concerns (JWT auth, backpressure, error
taxonomy, heartbeats) to isolate what this part is actually about (Ch19,
"Binary Protobuf over WebSockets"; Ch20, "Optimizing throughput"): **wire
encoding**, not connection hardening. Quarkus (`quarkus/`, host port `8090`,
WebSockets Next) and Python (`python/`, host port `8091` + HTTP `8092`,
native `websockets` + FastAPI) independently implement the identical
negotiation against the same contract and the same
[`contracts/handling-event.proto`](../../contracts/handling-event.proto), so
the two stacks are directly comparable. `verify.sh` opens connections
against **both** stacks with **both** encodings and asserts that live.

## Why this exists

A client decoding JSON already pays for human-readable field names, string
quoting, and no compression — fine for low-volume feeds, wasteful at scale.
Protobuf is a second wire encoding of the *exact same message shape*: same
field VALUES (RFC-3339 timestamps, decimal-string amounts — see
`contracts/handling-event.proto`'s header comment), smaller bytes. This part
proves both things live, not just asserts them in prose: the decoded field
values are identical across encodings, and the Protobuf frame measures
strictly smaller than the JSON frame for the same event, on both stacks.

## Encoding negotiation (DRQ-026)

A client picks the wire encoding via the `Sec-WebSocket-Protocol` upgrade
header, offering one of the three values `contracts/asyncapi.yaml` declares.
Both stacks declare the SAME preference order, so a client offering more
than one value gets the same encoding regardless of which stack it talks
to — see `quarkus/README.md` and `python/README.md` for each side's
negotiation code:

| Client offers | Server selects (echoed back) | Wire encoding |
|---|---|---|
| `handling-events.v1+protobuf` | `handling-events.v1+protobuf` | Protobuf **binary** frames (opcode `0x2`) |
| `handling-events.v1+json` | `handling-events.v1+json` | JSON **text** frames (opcode `0x1`) |
| `handling-events.v1` (bare) | `handling-events.v1` | JSON **text** frames — equivalent to `+json` |
| nothing | *(none negotiated)* | JSON **text** frames — the pre-Part-5 default; **JSON wins when both are offered and the server has no bare-preference reason to pick otherwise** |

## The proto contract

[`contracts/handling-event.proto`](../../contracts/handling-event.proto)
(package `shipping.handlingevents.v1`) is the single source of truth for the
binary encoding — the AsyncAPI document stays the single source of truth for
the message's MEANING. Both sides are generated, never committed:

- **Quarkus:** `io.github.ascopes:protobuf-maven-plugin` compiles it at
  `generate-sources` into `target/generated-sources/` (see
  `quarkus/README.md`'s "Protobuf generation" section for the generated
  class name's `OuterClass` collision note).
- **Python:** `scripts/generate-proto.sh` compiles it with `grpcio-tools`'
  bundled `protoc` into `app/handling_event_pb2.py`(+`.pyi`).

[`scripts/check-proto-parity.py`](../../scripts/check-proto-parity.py) is
the static drift gate: it compiles the `.proto` to a descriptor set and
diffs field names, required/optional, and enum membership/order against
`build/handling-event.schema.json` (extracted from `contracts/asyncapi.yaml`
by `scripts/extract-message-schema.py`) — catching a field renamed or
dropped on one side only, or an enum member added out of order, that `buf
lint`/`buf breaking` can't see (neither looks at the JSON side of the
contract). `verify.sh`'s last step runs this gate live.

## Measured frame sizes (confirmed live)

Compact (no-pretty-print) JSON vs. serialized Protobuf, same fixture
events, same field values — Protobuf runs **~40% smaller** (see each app's
own README for the full per-event table; `verify.sh` measures the RECEIVE
event's two frame sizes on every run and asserts the Protobuf one is
strictly smaller, not just "close"):

| Event | JSON (bytes) | Protobuf (bytes) | Reduction |
|---|---:|---:|---:|
| `evt_...T5E8` (RECEIVE) | 247 | 149 | 39.7% |
| `evt_...U6F9` (LOAD) | 267 | 156 | 41.6% |
| `evt_...V7G0` (CUSTOMS) | 265 | 157 | 40.8% |

## Run it

```bash
cd examples/part5-performance
./verify.sh
```

This brings both services up with `docker compose`, then for **each**
stack (Quarkus `:8090`, Python `:8091`):

1. Opens the channel offering `+json`, reads the first frame as TEXT,
   schema-validates it against the contract-derived JSON Schema, and
   asserts `eventType=RECEIVE` plus `eventId`/`bookingId` match the
   fixture.
2. Opens the channel offering `+protobuf`, captures the first frame as
   BINARY, decodes it with a `handling_event_pb2` stub generated once from
   `contracts/handling-event.proto`, converts it to the same JSON-shaped
   dict, schema-validates THAT, and asserts **every field value is
   identical** to the JSON path's — one message, two encodings, not two
   messages that happen to both validate independently.
3. Asserts the Protobuf frame is strictly smaller than the JSON frame.
4. Hand-rolls the WebSocket opening handshake (no client library) to
   confirm the server echoes back the exact subprotocol it was offered, for
   both encodings.

Then runs `python3 -I scripts/check-proto-parity.py` once (stack-
independent — it's a static contract-vs-contract check) and asserts it
exits 0.

Prints `PASS` only if every assertion above holds for **both** stacks.

### Ports

| Service | Host port | Purpose |
|---|---|---|
| `quarkus` | `8090` | WS upgrade + the `handlingEvents` channel (JSON/Protobuf by subprotocol) |
| `python` | `8091` | WS upgrade + the `handlingEvents` channel (native `websockets` library) |
| `python` | `8092` | HTTP: `/healthz`, `/` (FastAPI/uvicorn, app lifecycle only) |

### Observability (opt-in)

Same convention as part3/part4 — off by default so a first boot and CI stay
fast:

```bash
./verify.sh --profile observability
# or, by hand:
docker compose --profile observability up --build
```

## Diagram

[`../../assets/diagrams/part5-performance-architecture.svg`](../../assets/diagrams/part5-performance-architecture.svg) /
`part5-performance-architecture.excalidraw` (generated with
[`scripts/diagrams/part5-performance-architecture.py`](../../scripts/diagrams/part5-performance-architecture.py)
via `scripts/generate_diagram.py`) show one `HandlingEvent` negotiating a
wire encoding via `Sec-WebSocket-Protocol`, the two resulting frames
(JSON text, opcode `0x1`, vs. Protobuf binary, opcode `0x2`), and the
decode-to-identical-values / smaller-bytes outcome `verify.sh` proves live.

## Generated artifacts

`build/handling-event.schema.json` (extracted from `contracts/asyncapi.yaml`),
`python/app/models_generated.py` (JSON model), and both stacks' Protobuf
stubs (`quarkus/target/generated-sources/...`,
`python/app/handling_event_pb2.py`(+`.pyi`)) are build-time-only, gitignored,
and regenerated on every build — never committed. `verify.sh` additionally
generates a throwaway Protobuf stub of its own (into a `mktemp -d` directory,
cleaned up on exit) purely to decode captured binary frames during the
self-verify run — distinct from, but compiled from the same
`contracts/handling-event.proto` as, each stack's own build-time stub.
