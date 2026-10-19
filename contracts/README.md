# Contracts — the AsyncAPI single source of truth

`asyncapi.yaml` is the WebSockets analog of the REST site's OpenAPI document
and the gRPC site's Protobuf package: the one artifact both stacks generate
from and validate against. It is authored before any chapter example (Ch5)
and kept as a single file (DRQ-014) — not split across
`channels/`/`operations/`/`components/` files — because the contract is small
enough that splitting would add indirection without buying anything. Revisit
only if it grows enough to warrant it.

```
contracts/
  asyncapi.yaml          the contract — one WebSocket channel, one push message
  handling-event.proto   a parallel BINARY encoding of the same message (Part 5)
  buf.yaml               governs handling-event.proto (lint STANDARD, breaking FILE)
  buf.gen.yaml           convenience local stub generation, not a CI dependency
  README.md              this file
```

## What it models

The live handling-event feed described in DRQ-004: a client opens one
WebSocket connection per booking at
`/ws/v1/bookings/{bookingId}/handling-events` and the server pushes a
`HandlingEvent` message every time a handling event (RECEIVE, LOAD, UNLOAD,
CUSTOMS, CLAIM, HOLD, DELIVERED) is recorded for that booking's cargo. It is
server-to-client only — `operations.receiveHandlingEvent` is an
AsyncAPI 3 `action: receive` operation; there is no client-to-server
operation on this channel.

The domain vocabulary is continuous with the REST and gRPC sibling sites'
shared glossary: `Booking`, `Cargo`, `Location` (UN/LOCODE), `Route`, `Leg`,
`Operation`, and Money-as-decimal-string.

## Conventions

- **AsyncAPI 3 shape.** `channels` + `operations` + `components` as separate
  top-level sections, per the 3.x document structure — not the 2.x shape
  where operations live nested under `channels`.
- **Money is a decimal string**, never a float (`components.schemas.Money`),
  matching the REST and gRPC contracts' Money convention.
- **Enum zero value is always `*_UNSPECIFIED`.** `HandlingEventType`'s zero
  member is `HANDLING_EVENT_TYPE_UNSPECIFIED`; the server never sends it, but
  it gives the enum a safe default on deserialization — the same convention
  the gRPC contract's `BookingState` enum uses.
- **Versioned channel path.** `/ws/v1/...` — a breaking change to the message
  shape becomes `/ws/v2/...`, the WebSocket analog of the REST site's
  versioned resource paths and the gRPC site's versioned packages.
- **One reused message shape.** `components.messages.HandlingEvent` is
  defined once and referenced (`$ref`) from both the channel and the
  operation — never duplicated inline.
- **Identifier shapes match the shared glossary.** `bookingId` and `cargoId`
  carry the same `bkg_`/`crg_`-prefix, ULID-shaped identifiers as the REST
  and gRPC contracts' `Booking`/`Cargo` types.

## Validating it

```bash
npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml
```

`6.2.1` is the pinned, current-latest stable release of `@asyncapi/cli` as of
this writing — re-check `npm view @asyncapi/cli version` before bumping the
pin. A lightweight CI step runs this same command from r02 onward (DRQ-012);
the full regenerate-both-stacks-and-fail-on-drift gate (the analog of the
gRPC site's `buf breaking`) is deferred until the examples generate from this
contract.

## Generating stubs

Both stacks generate from this one file:

- **Quarkus (WebSockets Next)** — the endpoint's message types are hand-kept
  in sync with the schemas here until a generator step lands with the
  examples iteration (DRQ-011); the contract is the thing reviewed for
  correctness, not the generated code.
- **Python (FastAPI/Starlette + `websockets`)** — same: Pydantic models
  mirroring `components.schemas` land with the examples iteration.

Until then, `asyncapi validate` is the Ch5 end-to-end anchor (DRQ-011): a
contract that validates and that both stacks will generate from, rather than
a running service.

## Protobuf: a parallel binary encoding

Part 5 (Ch19, "Binary Protobuf over WebSockets") adds a second wire encoding
of the exact same `HandlingEvent` message: `handling-event.proto` (DRQ-025).
`asyncapi.yaml` stays the single source of truth for what the message
*means*; the proto file is the single source of truth for how it looks as
bytes. The two are governed as a pair, not independently:

- **`handling-event.proto`** — proto3, `package shipping.handlingevents.v1`,
  stable field numbers (additive-only, never reused — the same
  non-breaking-evolution discipline Ch7 applies to the JSON contract).
  `occurredAt`/`registeredAt`/`amount`/`location` stay plain `string` fields
  rather than typed Protobuf equivalents (e.g. `google.protobuf.Timestamp`),
  so a value decoded from either encoding is byte-for-byte identical.
- **`buf.yaml`** governs it — `buf lint` (`STANDARD`, with two documented
  exceptions for this site's single-file contract layout — see the comment
  in `buf.yaml`), `buf build`, and `buf breaking` (`FILE`-level compatibility
  from the commit after it's introduced), the same posture as the gRPC
  sibling site's `contracts/buf.yaml`.
- **`scripts/check-proto-parity.py`** closes the gap buf can't: it compiles
  the proto to a descriptor set and diffs its field names, enum members (in
  order), and required/optional split against
  `build/handling-event.schema.json` (the same extracted schema
  `scripts/extract-message-schema.py` already produces from
  `asyncapi.yaml`). `buf breaking` only ever sees the proto side; this
  script is what actually catches `asyncapi.yaml` and `handling-event.proto`
  drifting apart.

  ```bash
  python3 -I scripts/extract-message-schema.py build/handling-event.schema.json
  python3 -I scripts/check-proto-parity.py
  ```

- **Encoding negotiation via subprotocol (DRQ-026).** A client picks JSON or
  Protobuf through `Sec-WebSocket-Protocol`: `handling-events.v1+json` (the
  default — equivalent to the original, encoding-unqualified
  `handling-events.v1`) or `handling-events.v1+protobuf`. This is an
  additive extension of the contract's existing subprotocol value, verified
  with `asyncapi diff` to introduce no breaking change.
- **No generated stubs are committed.** Java lands under `target/`, Python's
  `_pb2.py`/`_pb2_grpc.py`/`_pb2.pyi` are gitignored (see `.gitignore`); each
  stack regenerates its own stubs from `handling-event.proto` at build time,
  the same convention the gRPC sibling site uses for its own `.proto` files.
