# Part 4 example: Python native `websockets` + FastAPI, reconnect + backplane fan-out

Forks `examples/part4-connection/python` and implements
`examples/part4-backplane/PROTOCOL.md`: the shared wire/behavior contract
both this stack and its Quarkus sibling (`../quarkus/`) implement
identically, so one combined `verify.sh` can assert both and a client
connected to one stack's instance A can see an event injected through the
same stack's instance B.

| Chapter | Concern | Where |
| --- | --- | --- |
| Ch15 | Reconnect (visible gap, stateless) | `app/ws_server.py`, `app/backplane/stateless_backplane.py` |
| Ch16 | Reconnect (`?afterEventId=` replay via Kafka) | `app/backplane/kafka_backplane.py` |
| Ch18 | Scale-out fan-out: stateless/kafka/redis | `app/backplane/` |

The channel (`/ws/v1/bookings/{bookingId}/handling-events`) pushes the same
three `HandlingEvent`s (RECEIVE, LOAD, CUSTOMS) as Part 3/Part 4-connection,
reusing the shared fixture byte-for-byte
(`../../part3-handling-events/fixtures/handling-events.json`) as the
deterministic seed baseline on **every** connection, in **every** backplane
mode: this example is about connection/backplane concerns, not new message
content.

## Architecture

Two listeners, one process, one event loop (`app/main.py`), sharing one
`Backplane` instance:

- **`app/ws_server.py`**: the WebSocket endpoint, native `websockets`
  library. Listens on `WS_HOST:WS_PORT` (default `0.0.0.0:8081`).
- **`app/http_app.py`**: a small FastAPI app (`/healthz`, `/`, and the
  `POST /internal/bookings/{bookingId}/handling-events` inject endpoint),
  run under uvicorn on `HTTP_HOST:HTTP_PORT` (default `0.0.0.0:8082`).
- **`app/backplane/`**: the `Backplane` abstraction and its three
  implementations, selected by `BACKPLANE_MODE`:
  - `stateless_backplane.StatelessBackplane` (default): in-process
    `asyncio.Queue` fan-out only; no cross-instance delivery.
  - `kafka_backplane.KafkaBackplane`: a shared `handling-events` topic via
    `aiokafka`; durable, replayable, powers `?afterEventId=` resume.
  - `redis_backplane.RedisBackplane`: a shared `handling-events:{bookingId}`
    Pub/Sub channel via `redis.asyncio`; live fan-out only, no replay.

## Design note: seed baseline vs. the backplane (resolving PROTOCOL.md's ambiguity)

PROTOCOL.md specifies the wire contract precisely but leaves one
implementation detail implicit: exactly how the "deterministic baseline"
(Seed events) interacts with Kafka's "replay events after `afterEventId`
(or, if absent, from the live tail)". This implementation resolves it as
follows, and the Quarkus sibling should match it:

- **The 3 fixture seed events are delivered directly from `app/feed.py` on
  every connection, in every backplane mode**, never through the
  backplane. This keeps the deterministic baseline byte-for-byte identical
  across stateless/kafka/redis (see `app/ws_server.py`'s `_deliver_loop`).
- **The backplane (topic/channel) carries only injected events**, never the
  seed. This is what makes `afterEventId=<the last seed event's id>`
  meaningful in kafka mode even though that id was never produced to Kafka:
  `KafkaBackplane.subscribe` buffers the topic's full history up to the
  subscribe-time snapshot, looks for `after_event_id` in it, and, when not
  found (as for a seed-event id, or any id produced before the backplane
  existed), falls back to replaying **everything currently in the topic**,
  which is exactly the gap-era injected event(s) in the
  stateless-gap-then-kafka-replay scenario. See
  `app/backplane/kafka_backplane.py`'s module docstring for the full
  rationale.
- `redis`/`stateless` modes ignore `after_event_id` entirely (no history to
  replay; PROTOCOL.md calls this out explicitly for redis, and stateless is
  the mode that demonstrates the gap).

## Backplane modes

Selected by `BACKPLANE_MODE` (default `stateless`):

```bash
BACKPLANE_MODE=stateless   # default — no broker, no cross-instance fan-out
BACKPLANE_MODE=kafka       # KAFKA_BOOTSTRAP_SERVERS, KAFKA_TOPIC (default handling-events)
BACKPLANE_MODE=redis       # REDIS_URL (default redis://localhost:6379/0)
```

## Inject endpoint

```
POST /internal/bookings/{bookingId}/handling-events
Content-Type: application/json

{"eventId": "evt_...", "bookingId": "bkg_...", "cargoId": "crg_...",
 "eventType": "DELIVERED", "location": "NLRTM",
 "occurredAt": "...", "registeredAt": "..."}
```

Returns `202 Accepted`. Publishes to the active backplane (kafka topic /
redis channel) in broker modes, or delivers directly to this instance's
local connections in stateless mode. Internal/demo endpoint: not part of
the public AsyncAPI contract.

## Instance identity

`INSTANCE_ID` (default `python-a`) is logged on every connection accept and
every event delivery, exact shape (PROTOCOL.md):

```
delivered eventId=<id> bookingId=<id> instance=<INSTANCE_ID>
```

## Close codes

| Code | Meaning |
| --- | --- |
| `4400` | Malformed client message (this channel is still server-push-only) |
| `1011` | Unexpected server-side error |
| `1001` | Server going away (shutdown: handled by the `websockets` library's default `Server.close()`) |
| `1000` | Normal close |

Auth (`1008`) and backpressure (`4290`) from `part4-connection` are **not**
re-exercised here (PROTOCOL.md). This example focuses on the backplane.

## Build-time model generation

`app/models_generated.py` is **generated, gitignored, never committed**:

```bash
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./scripts/generate-models.sh
```

## Run it

```bash
uv sync --group dev
./scripts/generate-models.sh
uv run pytest                 # schema conformance + backplane unit tests

# stateless (default)
uv run python -m app.main

# kafka
BACKPLANE_MODE=kafka KAFKA_BOOTSTRAP_SERVERS=localhost:9092 uv run python -m app.main

# redis
BACKPLANE_MODE=redis REDIS_URL=redis://localhost:6379/0 uv run python -m app.main

# second instance (same mode, shared broker for kafka/redis)
INSTANCE_ID=python-b WS_PORT=8084 HTTP_PORT=8085 BACKPLANE_MODE=kafka uv run python -m app.main
```

## Self-verify: what was proven live

All three modes were started and driven with real client connections and
real HTTP injects against this checkout, beyond unit tests:

- **`uv sync --group dev`**: resolves and installs cleanly on Python 3.15.0
  (uv-managed), including `aiokafka==0.14.0` (built cleanly from sdist) and
  `redis==8.1.0`.
- **`./scripts/generate-models.sh`**: generates `app/models_generated.py`
  from `contracts/asyncapi.yaml`.
- **`uv run pytest`**: **13 passed** (schema conformance, error-envelope
  shape, `create_backplane` mode selection, `StatelessBackplane` in-process
  pub/sub incl. no-subscriber-drop and no-cross-booking-delivery).
- **stateless mode, standalone** (`BACKPLANE_MODE=stateless`,
  `INSTANCE_ID=python-a`, ports 8081/8082): connected a client, confirmed
  the seeded RECEIVE frame (schema-validated); `POST` inject while connected
  → the connected client received it, with the exact
  `delivered eventId=... bookingId=... instance=python-a` log line.
  **Stateless gap test**: connect → disconnect → inject a gap event while
  disconnected → reconnect with `?afterEventId=<last seed eventId>` →
  **confirmed the gap event was not delivered** (stateless loses gap-era
  events, by design).
- **kafka mode, standalone** (a real `apache/kafka:4.3.1` container, no
  mocks): same gap test: connect → disconnect → inject a gap event →
  reconnect with `?afterEventId=<last seed eventId>` → **confirmed the gap
  event was delivered, exactly once, with no duplicate** (verified both
  against a topic with prior test history, the fallback-replay path, and
  against a freshly named topic, which delivered precisely 3 seed + 1 gap
  frame, nothing more). `KafkaBackplane` buffers the topic's history up to
  the subscribe-time snapshot first, then decides the replay slice, which
  keeps the replay deterministic even when the last historical record sits
  right at the live-tail boundary; see `app/backplane/kafka_backplane.py`.
- **redis mode, standalone** (a real `redis:8.10.2-alpine` container, no
  mocks), **two instances** (`python-a` on 8081/8082, `python-b` on
  8084/8085, same Redis): connected a client to instance A, injected via
  instance B's `POST /internal/.../handling-events`, and **confirmed
  instance A's client received the event**, with instance A's log showing
  `delivered eventId=... bookingId=... instance=python-a`, proving the
  event crossed instances via the Redis Pub/Sub backplane (the fan-out
  proof).
- All containers and processes started for this verification were torn down
  afterward; nothing was left running.

Nothing here was deferred to the combined `verify.sh`. Docker was available
in this environment, so all three modes (including the two-instance
cross-instance fan-out proof) were exercised against real brokers rather
than left as "implemented to spec, unverified."

## Container build

Build from the **repo root** (the context needs to reach `contracts/` and
the shared fixture under `examples/part3-handling-events/`):

```bash
docker build -f examples/part4-backplane/python/Containerfile \
  -t ch18-backplane-python .
docker run --rm -p 8081:8081 -p 8082:8082 \
  -e BACKPLANE_MODE=kafka -e KAFKA_BOOTSTRAP_SERVERS=kafka:9092 \
  ch18-backplane-python
```

## Pinned versions

| Tool / package | Version |
| --- | --- |
| Python | 3.15 (3.15.0 locally) |
| uv | 0.13.1 |
| fastapi | 0.146.0 |
| websockets | 17.2 |
| uvicorn[standard] | 0.54.0 |
| aiokafka | 0.14.0 |
| redis (redis-py, asyncio client) | 8.1.0 |
| opentelemetry-distro | 0.66b1 (declared; not yet wired into the entrypoint, same scope note as Part 3/Part 4-connection) |
| datamodel-code-generator (dev) | 0.86.0 |
| jsonschema (dev) | 4.26.0 |
| pytest (dev) | 9.1.1 |
| UBI base image | `registry.access.redhat.com/ubi10/python-314-minimal:10.2-1791928506` |
| Kafka (test broker, not a runtime dep) | apache/kafka:4.3.1 |
| Redis (test broker, not a runtime dep) | redis:8.10.2-alpine |
