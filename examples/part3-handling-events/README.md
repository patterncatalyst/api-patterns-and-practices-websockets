# Part 3 "Handling It": the `handlingEvents` channel, two stacks

The reference both-stack implementation of
[`operations.receiveHandlingEvent`](../../contracts/asyncapi.yaml): a client
opens one WebSocket connection per booking at
`/ws/v1/bookings/{bookingId}/handling-events`, and the server pushes a
`HandlingEvent` message every time a handling event is recorded for that
booking's cargo. It's server-to-client only: there's no client-to-server
operation on this channel.

Quarkus (`quarkus/`, host port `8080`) and Python (`python/`, host port
`8081`) independently implement the identical channel, generated from the
**same** `contracts/asyncapi.yaml`, replaying the **same** shared fixture
(`fixtures/handling-events.json`) in order for any `bookingId`. `verify.sh`
opens a connection against **both** stacks, captures the first pushed frame,
and asserts **field semantics against the fixture and the contract-derived
JSON Schema**, beyond a successful socket upgrade.

## The event sequence

Both stacks push the same 3 `HandlingEvent`s from
[`fixtures/handling-events.json`](fixtures/handling-events.json), in this
exact order, on every connection to the channel (the `{bookingId}` path
segment is accepted but not looked up against the fixture here: any value
replays the same fixed sequence; per-booking lookup lands later):

| # | `eventType` | `location` | `occurredAt` | notes |
|---|---|---|---|---|
| 1 | `RECEIVE` | USNYC (New York) | `2026-01-15T08:00:00Z` | cargo received at the origin terminal |
| 2 | `LOAD` | USNYC (New York) | `2026-01-15T14:30:00Z` | loaded onboard voyage `0042E` |
| 3 | `CUSTOMS` | NLRTM (Rotterdam) | `2026-01-18T09:15:00Z` | customs clearance, fee `125.00` |

Every event carries `eventId`, `bookingId`, `cargoId`, `eventType`,
`location`, `occurredAt`, and `registeredAt`; `voyageNumber` (event 2) and
`amount` (event 3) are optional fields present only where the fixture sets
them; both stacks omit absent optional fields from the wire frame rather
than emitting `null`. `verify.sh` checks event `[0]` (`RECEIVE`) field-by-field
against the fixture and schema-validates it on both stacks; the full
3-event sequence is covered by each stack's own conformance test (see
below).

## Generation from the contract

Neither stack hand-maintains a parallel copy of the message shape.
`contracts/asyncapi.yaml` is the single source of truth
(`components.schemas.HandlingEvent`, with `HandlingEventType`, `Location`,
and `Money` pulled in by `$ref`). [`scripts/extract-message-schema.py`](../../scripts/extract-message-schema.py)
inlines those `$ref`s into one self-contained JSON Schema (Draft 2020-12):
the generated, gitignored `build/handling-event.schema.json`, which both
the test suites and `verify.sh` validate every emitted frame against:

```bash
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json
```

- **Python** generates `app/models_generated.py` from that extracted schema
  with `datamodel-code-generator` (AsyncAPI input support is unreliable for
  this contract; the extracted JSON Schema is the reliable generator input).
  See `python/scripts/generate-models.sh` and `python/README.md`. The app
  imports the generated Pydantic v2 `HandlingEvent` model; `app/feed.py`
  validates every fixture event against it and re-serializes with the
  model's own `model_dump_json(exclude_none=True)`, so there is one source
  of truth for both validation and the wire format.
- **Quarkus** hand-keeps `HandlingEvent` (record) and `HandlingEventType`
  (enum) to the contract's field and enum-member names
  (`src/main/java/.../handlingevents/`), with no generator step for this
  stack. `HandlingEventContractTest` validates every fixture-derived event
  against the same extracted schema and asserts `HandlingEventType` carries
  exactly the contract's 8 members, in order.

Both the extracted schema and the generated Python model are build-time
artifacts: gitignored, regenerated on every build (local or container), and
never committed (see `../../.gitignore`, `python/.gitignore`).

## Run it

```bash
cd examples/part3-handling-events
./verify.sh
```

This brings both services up with `docker compose`, waits for each
WebSocket endpoint to accept the upgrade, captures the first pushed frame
from `ws://localhost:8080/ws/v1/bookings/bkg_.../handling-events` (Quarkus)
and `ws://localhost:8081/ws/v1/bookings/bkg_.../handling-events` (Python),
schema-validates each frame, asserts it matches `fixtures/handling-events.json[0]`
(the `RECEIVE` event) field-by-field, then cross-checks that **both stacks'
first frame agree on every field** (comparing parsed JSON fields, not raw
bytes: Jackson and Pydantic don't serialize object keys in the same order,
which is fine), and tears the stack down. Prints `PASS` only if every
assertion holds for **both** stacks.

To poke at it by hand instead, using the shared harness
(`../_lib/lib.sh`):

```bash
docker compose up --build
source ../_lib/lib.sh
ensure_websocat
wait_for_ws localhost:8080 /ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events
ws_first_frame "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
# swap 8080 for 8081 to hit the Python stack instead
docker compose down -v
```

### Ports

| Service | Host port | Purpose |
|---|---|---|
| `quarkus` | `8080` | WS upgrade + the `handlingEvents` channel |
| `python` | `8081` | WS upgrade + the `handlingEvents` channel (native `websockets` library) |
| `python` | `8082` | HTTP: `/healthz`, `/` (FastAPI/uvicorn, app lifecycle only; see `python/README.md`) |

### Observability (opt-in)

The Grafana LGTM stack is off by default so a first boot and CI stay fast.
Both apps are wired for OTLP export but start and serve the channel fine
without a collector listening: Quarkus's OTel SDK stays disabled
(`quarkus.otel.sdk.disabled=true`) and Python's `opentelemetry-distro`
dependency isn't wrapped around the entrypoint yet (that wiring is a later
chapter's job, not this one's; see `python/README.md`).

```bash
./verify.sh --profile observability
# or, by hand:
docker compose --profile observability up --build
```

`verify.sh --profile observability` runs the same checks against the app
stack; the flag only affects whether `lgtm` (Grafana on `:3000`, OTLP on
`:4317`/`:4318`) comes up alongside it.

## Diagram

`../../assets/diagrams/part3-architecture.svg` /
`part3-architecture.excalidraw` (generated with
[`scripts/diagrams/part3-architecture.py`](../../scripts/diagrams/part3-architecture.py)
via `scripts/generate_diagram.py`) show the request/response topology for
this example: a client opening the channel against each stack on its own
port, both stacks reading the same `contracts/asyncapi.yaml`, and both
replaying the same fixture.
