# Part 4 "Production Concerns" — Quarkus backplane (reconnect + fan-out)

Forked from
[`examples/part4-connection/quarkus`](../../part4-connection/quarkus) /
[`examples/part3-handling-events/quarkus`](../../part3-handling-events/quarkus):
the same `handlingEvents` channel
(`operations.receiveHandlingEvent`, [`contracts/asyncapi.yaml`](../../../contracts/asyncapi.yaml)).
This part adds **reconnect resume** (`?afterEventId=`) and **cross-instance
fan-out** behind three interchangeable delivery modes. The Python/`aiokafka`
+ `redis-py` sibling app ([`../python`](../python)) implements the identical
wire/behavior contract — see
[`examples/part4-backplane/PROTOCOL.md`](../PROTOCOL.md) for the single
source of truth both stacks follow.

- **Endpoint:** `ws://localhost:8080/ws/v1/bookings/{bookingId}/handling-events?afterEventId=<id>`
- **Inject (internal/demo only):** `POST /internal/bookings/{bookingId}/handling-events` → `202 Accepted`
- **Mode:** `BACKPLANE_MODE=stateless|kafka|redis` (default `stateless`)
- **Instance identity:** `INSTANCE_ID` (default `quarkus`), logged on every connect and every delivery.

## Design note: the fixture seed never flows through the backplane

The 3-event fixture ([`../../part3-handling-events/fixtures/handling-events.json`](../../part3-handling-events/fixtures/handling-events.json))
is sent directly by `HandlingEventBackplaneWebSocket#onOpen`,
**unconditionally, in every mode** — it never touches a `Backplane`
implementation at all. Only what happens *after* that seed — the
`afterEventId`-filtered replay (kafka only) and then the live tail — comes
from whichever `Backplane` is active. This matches the Python sibling
exactly (see that app's README "Design note") and keeps "a fresh connection
always has a deterministic baseline" true regardless of mode, independent of
whatever the Kafka topic or Redis channel happens to be carrying.

## Backplane modes

| Mode | `afterEventId` | Fan-out | Notes |
|---|---|---|---|
| `stateless` (default) | ignored | local connections on the SAME instance only | `StatelessBackplane` — an injected event that reaches no local connection is gone forever (the Ch15 gap proof). |
| `kafka` | replays INJECTED events after it (or, if not found — e.g. it names a fixture-seed id — replays the entire injected history) | every instance (distinct consumer group per `INSTANCE_ID`) | `KafkaBackplane` — see its Javadoc for the full replay algorithm and why "not found" is the *expected* case for a fixture id. |
| `redis` | ignored (no history) | every subscribed instance, live only | `RedisBackplane` — Pub/Sub, no durability. |

`BackplaneRouter` holds all three beans always-constructed and dispatches to
the active one by `backplane.mode` (`BACKPLANE_MODE` env). `LocalDelivery` is
the one place that actually pushes a frame to a connection and logs the
required line:

```
delivered eventId=<id> bookingId=<id> instance=<INSTANCE_ID>
```

**Must be non-blocking.** `LocalDelivery#deliver` uses `connection.sendText(...)`
(a `Uni`), never `sendTextAndAwait` — confirmed live: `RedisBackplane`'s
Pub/Sub callback runs on a Vert.x event-loop thread, where a blocking send
throws `IllegalStateException: The current thread cannot be blocked`. The
Kafka `@Incoming` consumer and the stateless direct-call path both happen to
run on a worker thread (blocking would have been "safe" for them), but since
`LocalDelivery` has no way to know which caller it's on, it is always
non-blocking — the one fix needed after the first live Redis run.

## Kafka wiring

`quarkus-messaging-kafka` (SmallRye Reactive Messaging), topic
`handling-events`, keyed by `bookingId`. Each instance's consumer group is
derived from its own `INSTANCE_ID`
(`mp.messaging.incoming.handling-events-in.group.id`) — **fan-out, not
load-balancing**: every instance gets every record, which is what lets
instance A's client see an event injected through instance B.
`auto.offset.reset=earliest` means a freshly started instance replays the
whole topic (within retention) into memory before any client connects, so
replay has the full picture. Value (de)serialization uses
`io.quarkus.kafka.client.serialization.ObjectMapperSerializer`/`Deserializer`
(`HandlingEventSerializer`/`HandlingEventDeserializer`) — the same Jackson
shape as the WebSocket frame.

`quarkus.kafka.devservices.enabled=false` keeps `./mvnw test` and a
stateless-mode boot from requiring Docker — confirmed live: the app starts in
under a second with `BACKPLANE_MODE=stateless` and no Kafka broker reachable
at all, logging background `NetworkClient` connection-refused warnings that
never block startup or affect stateless behavior (the `@Incoming`/`@Outgoing`
channels are wired statically regardless of mode, per SmallRye's annotation
model — see `BackplaneRouter`'s Javadoc).

## Redis wiring

`quarkus-redis-client`'s `ReactiveRedisDataSource.pubsub(String.class)`,
channel `handling-events:{bookingId}`. `RedisBackplane#onConnect` lazily
subscribes to a booking's channel the first time a local client connects for
it (subscribe-once, kept for the app's lifetime). Events are JSON text on the
wire (same Jackson shape as everywhere else). `quarkus.redis.devservices.enabled=false`
for the same "don't require Docker for stateless" reason as Kafka.

## Running it

```shell
./mvnw quarkus:dev
```

Dev UI: <http://localhost:8080/q/dev/>.

## Running the conformance test

Forked verbatim from part3/part4-connection — regenerate the contract-derived
schema first:

```shell
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./mvnw -q test
```

## Packaging

```shell
./mvnw package
BACKPLANE_MODE=stateless INSTANCE_ID=quarkus-a java -jar target/quarkus-app/quarkus-run.jar
```

Container image from the **repo root** (the build context needs to reach
`examples/part3-handling-events/fixtures/`):

```shell
docker build -f examples/part4-backplane/quarkus/Containerfile \
  -t part4-backplane-quarkus .
docker run --rm -p 8080:8080 \
  -e BACKPLANE_MODE=stateless -e INSTANCE_ID=quarkus-a \
  part4-backplane-quarkus
```

## Self-verify — confirmed live this session

All three scenarios below were run against the packaged jar (not just unit
tests), using `examples/_lib/lib.sh`'s `websocat`-based harness plus `curl`
for the inject endpoint.

**Stateless mode** (`BACKPLANE_MODE=stateless`, no broker):
- Booted in under a second with no Kafka/Redis reachable.
- A connected client received the 3-event fixture baseline.
- A `POST .../handling-events` inject was delivered to the still-connected
  client.
- **Ch15 gap proof:** connected, disconnected, injected an event during the
  gap, reconnected with `?afterEventId=<last fixture id>` — the gap event was
  **NOT** delivered (stateless loses it, as spec'd).

**Kafka mode** (`BACKPLANE_MODE=kafka`, single `apache/kafka:4.3.1` container
via plain `docker run`, no compose):
- Same gap scenario, but the gap event **WAS** delivered exactly once after
  reconnect (replay, no duplicate) — confirmed via the "not found → replay
  entire injected history" path (the reconnecting client's `afterEventId` was
  a fixture-seed id, which by design never appears in the Kafka-sourced
  buffer).
- **Ch18 cross-instance fan-out:** a client connected to instance A
  (`INSTANCE_ID=quarkus-a`, port 8080) received an event injected through
  instance B's (`INSTANCE_ID=quarkus-b`, port 8083) `POST` endpoint — log
  line confirmed `instance=quarkus-a` on the delivery, proving the event
  crossed instances via the shared topic.

**Redis mode** (`BACKPLANE_MODE=redis`, single `redis:8.10.2-alpine`
container via plain `docker run`):
- Same cross-instance fan-out proof as kafka: instance A's client received an
  event injected through instance B. This run is what surfaced and confirmed
  the fix to the blocking-send bug described above (the first attempt threw
  `IllegalStateException` on the Redis Pub/Sub event-loop thread; the second
  attempt, after switching `LocalDelivery` to the non-blocking `sendText`,
  passed cleanly).

No scenario was faked or assumed — every PASS above is from an actual packaged-jar
run in this session, including the one bug found and fixed along the way.
The combined `verify.sh` (Wave 3b) is expected to automate this across both
stacks via compose profiles; this module's own manual runs give high
confidence that automation will pass unchanged.

## Observability

`quarkus-opentelemetry` is on the classpath but the OTel SDK is disabled by
default (`quarkus.otel.sdk.disabled=true`) — same convention as part3/part4-connection.

## Related guides

- [WebSockets Next](https://quarkus.io/guides/websockets-next-reference)
- [SmallRye Reactive Messaging — Kafka](https://quarkus.io/guides/kafka-reactive-getting-started)
- [Redis client](https://quarkus.io/guides/redis)
- [OpenTelemetry](https://quarkus.io/guides/opentelemetry)
