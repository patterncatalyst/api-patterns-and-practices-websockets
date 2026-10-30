# part4-backplane: shared wire/behavior protocol

Both stacks (Quarkus WebSockets Next on 8080, Python native `websockets` on 8081,
FastAPI health on 8082) implement this **identically** so one `verify.sh` can
assert both and so a client connected to one stack's instance A sees an event
injected through the same stack's instance B. This file is the single source of
truth for the behavior that is *not* already fixed by `contracts/asyncapi.yaml`.

## The channel (unchanged from the contract)

`GET` (upgrade) `/ws/v1/bookings/{bookingId}/handling-events`. The server pushes
`HandlingEvent` messages exactly as defined by `contracts/asyncapi.yaml`: no new
fields, no envelope. Reconnect/offset state is carried in the URL and in the
server, never by mutating the message. (Keeps the contract + drift gate intact.)

## Resume parameter (stateless vs kafka)

- On (re)connect a client MAY pass `?afterEventId=<eventId>`: the `eventId` of
  the last `HandlingEvent` it already received.
- **stateless mode (default profile):** `afterEventId` is ignored. The
  server delivers only events that occur after the connection opens. Events that
  happened during a disconnect gap are **lost** (the visible-gap proof).
- **kafka mode (`--profile kafka`):** the server has the booking's event
  history from the Kafka topic (within retention). On connect it replays the
  events **after** `afterEventId` (or, if absent, from the live tail), then
  continues live. The client dedups by `eventId`; net effect = every gap-era
  event delivered **exactly once**, no duplicates.

## Backplane modes (fan-out)

An injected event (see below) is delivered to every connected client watching
that booking, **regardless of which server instance they are connected to**.

- **kafka** (`--profile kafka`): instances share a Kafka topic
  (`handling-events`, keyed by `bookingId`). Durable + replayable (powers
  kafka-mode resume too). Each instance consumes and forwards to its local
  connections.
- **redis** (`--profile redis`): instances share a Redis Pub/Sub channel
  (`handling-events:{bookingId}`). Live fan-out only, **no replay** (the
  contrast: simplicity/latency vs Kafka's durability/replay). In redis mode,
  `afterEventId` resume behaves as stateless (no history).
- **stateless** (default, no broker): an injected event reaches only clients on
  the **same** instance; cross-instance fan-out does not happen, which is
  exactly what the backplane solves.

## Inject endpoint (how tests publish events)

`POST /internal/bookings/{bookingId}/handling-events` with a `HandlingEvent` JSON
body (schema-valid per the contract). The server publishes it to the active
backplane (Kafka topic / Redis channel) in broker modes, or delivers it to local
connections in stateless mode. Returns `202 Accepted`. This is an internal/demo
endpoint (documented as not part of the public contract).

## Instance identity (how the A/B fan-out proof works)

Each server instance reads `INSTANCE_ID` from the env (e.g. `quarkus-a`,
`python-b`) and logs it with every connection accept and every event delivery:
`delivered eventId=<id> bookingId=<id> instance=<INSTANCE_ID>`. `verify.sh`
connects a client to instance **A**, injects an event through instance **B**'s
inject endpoint, and asserts A's client received it, proving the event crossed
instances via the backplane.

## Close codes (shared, consistent with part4-connection)

`1001` going away (shutdown) · `1011` unexpected server error · `4400` malformed
client message · `1000` normal. (Auth/backpressure/liveness codes from
part4-connection are not re-exercised here; this app focuses on the backplane.)

## Seed events

Both stacks seed each booking's stream from the shared fixture
`examples/part3-handling-events/fixtures/handling-events.json` (RECEIVE, LOAD,
CUSTOMS) so a fresh connection has a deterministic baseline, then tests inject
further events to exercise gaps, replay, and cross-instance fan-out.

## Ports / instances (compose)

- `quarkus-a` 8080, `quarkus-b` 8083 · `python-a` 8081 (health 8082),
  `python-b` 8084 (health 8085). Distinct `INSTANCE_ID` per service.
- Brokers behind profiles: `--profile kafka` (apache/kafka 4.3.1, KRaft),
  `--profile redis` (redis 8.10.2-alpine). Healthcheck-gated before app start.
