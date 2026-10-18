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
  asyncapi.yaml   the contract — one WebSocket channel, one push message
  README.md       this file
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
