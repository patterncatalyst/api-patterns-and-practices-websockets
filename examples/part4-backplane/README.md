# Part 4 "Production Concerns": reconnect + scale-out backplane

Forks [`examples/part4-connection`](../part4-connection) /
[`examples/part3-handling-events`](../part3-handling-events): the same
`handlingEvents` channel
(`operations.receiveHandlingEvent`, [`contracts/asyncapi.yaml`](../../contracts/asyncapi.yaml)),
now adding **reconnect resume** (`?afterEventId=`) and **cross-instance
scale-out fan-out** behind three interchangeable backplane modes. Quarkus
(`quarkus/`, WebSockets Next) and the Python sibling (`python/`, native
`websockets` + FastAPI) implement the identical wire/behavior contract: see
[`PROTOCOL.md`](./PROTOCOL.md) for the single source of truth both stacks
follow, and each stack's own README for its implementation notes.

## The three scenarios

| Chapter | Concern | Mode | What `verify.sh` proves |
|---|---|---|---|
| Ch15 | Reconnect, visible gap | `stateless` (default) | A client disconnects, an event is injected during the gap, the client reconnects with `?afterEventId=<last seen>`: the gap event is **lost** (no broker, no history). |
| Ch16 | Reconnect, replay | `kafka` | Same sequence, but the gap event **is delivered** after reconnect (replayed from the shared Kafka topic), deduped by `eventId`. |
| Ch18 | Scale-out fan-out | `kafka` or `redis` | An event injected through instance **B**'s internal endpoint reaches a client connected to instance **A**, proven once per backplane, for both stacks. |

## Backplane modes: Kafka vs. Redis

| | `stateless` (default) | `kafka` | `redis` |
|---|---|---|---|
| Fan-out across instances | No (local connections only) | Yes | Yes |
| `afterEventId` resume | Ignored (no history) | Replays gap-era events after it | Ignored (no history) |
| Durability | None | Topic retention | None (live only) |
| Latency / complexity | N/A | Higher (topic/partition/offset bookkeeping) | Lower (pure pub/sub) |
| When to reach for it | Never in production (this is the "before" picture) | Need replay/resume or at-least-once delivery guarantees | Need low-latency fan-out and can tolerate losing in-flight messages on disconnect |

This is the advantage case for moving off a single stateless instance:
Kafka buys durability and replay at the cost of running (and reasoning
about) a log; Redis buys nearly all of the cross-instance fan-out with a
fraction of the operational surface, at the cost of giving up replay
entirely. Neither is "better" in the abstract: the contrast is the point.

## Instance topology

Four app instances are always running (compose profiles only control which
**broker** comes up, not which app instances; see `compose.yaml`'s header
comment):

| Service | WS port | HTTP port (inject + health) | `INSTANCE_ID` |
|---|---|---|---|
| `quarkus-a` | `8080` | `8080` (same port) | `quarkus-a` |
| `quarkus-b` | `8083` | `8083` (same port) | `quarkus-b` |
| `python-a` | `8081` | `8082` | `python-a` |
| `python-b` | `8084` | `8085` | `python-b` |

Every instance logs `delivered eventId=<id> bookingId=<id>
instance=<INSTANCE_ID>` on every push (`PROTOCOL.md` "Instance identity"):
`verify.sh`'s fan-out proof greps instance A's own container log for this
line, confirming A's *server* did the delivering, not only A's client.

## Run it

```bash
cd examples/part4-backplane
./verify.sh
```

This runs three sequential `docker compose up`/`down` cycles in one
self-contained script:

1. **Default profile** (`BACKPLANE_MODE=stateless`, no broker): the
   visible-gap proof, both stacks.
2. **`--profile kafka`** (`BACKPLANE_MODE=kafka`): the replay proof, then
   the fan-out proof over Kafka, both stacks.
3. **`--profile redis`** (`BACKPLANE_MODE=redis`): the fan-out proof over
   Redis, both stacks.

Every scenario uses a freshly generated `bookingId` (even though all four
instances share one physical Kafka topic and one Redis instance): each
`Backplane` implementation filters strictly by `bookingId`, so distinct ids
are what keep the Kafka-replay and the two fan-out proofs from
cross-contaminating each other, and the two stacks from contaminating each
other, on that shared broker.

Prints `PASS` only if all three scenarios hold for both stacks on their
applicable profile(s).

### Observability (opt-in)

Same convention as part3/part4-connection, off by default so a first boot
and CI stay fast:

```bash
docker compose --profile observability up --build
```

### k6 smoke load

[`k6/smoke.js`](k6/smoke.js) is a smoke-level load script (3 VUs, 1
iteration each, no ramp) against the **default (stateless) profile's**
single always-up instance per stack. This channel has no auth gate
(PROTOCOL.md), so no token is needed. It only proves the channel itself is
alive and streams the 3 fixture frames correctly shaped; it doesn't
exercise replay or fan-out (those stay covered by `verify.sh`, which brings
up the brokers and runs for several minutes).

```bash
docker compose up --build -d quarkus-a python-a

# against Quarkus (:8080)
k6 run -e K6_WS_URL="ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
       k6/smoke.js

# against Python (:8081)
k6 run -e K6_WS_URL="ws://localhost:8081/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
       k6/smoke.js

docker compose down -v --remove-orphans
```

No local `k6`? Use the pinned image instead (same one the CI gate uses,
`docker.io/grafana/k6:2.3.0`, see the version matrix):

```bash
docker run --rm --network host \
  -e K6_WS_URL="ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
  -v "$(pwd)/k6:/scripts" \
  docker.io/grafana/k6:2.3.0 run /scripts/smoke.js
```

**CI context:** the `contracts.yml` workflow's `k6-smoke` job runs this
script against both the `quarkus-a` and `python-a` instances on every
push/PR: a k6 threshold failure (any failed check) fails that job, and
thus the PR (gated, not merely opt-in). The job brings up only
the default-profile `*-a` instances (no broker), runs the smoke script, and
tears the stack down afterward.

## A documented, benign race (kafka replay)

`PROTOCOL.md` and each stack's own README call out a narrow timing window on
reconnect: a client can, in rare cases, see the same gap-era event once from
the replay burst and once from the live tail (Quarkus's always-on Kafka
consumer and its per-connection `replayFor` snapshot are not synchronized
against each other). `verify.sh` dedups by `eventId` per the project's
harness convention for this: a raw frame count of 1 **or** 2 for that one
event both count as PASS (0 means it was lost; more than 2 would mean
something is wrong). The Python implementation's per-connection Kafka
consumer (buffer-to-snapshot, then resume exactly where it left off)
doesn't have this race at all: in practice its count is always 1.

## Diagram

[`../../assets/diagrams/part4-backplane-architecture.svg`](../../assets/diagrams/part4-backplane-architecture.svg) /
`part4-backplane-architecture.excalidraw` (generated with
[`scripts/diagrams/part4-backplane-architecture.py`](../../scripts/diagrams/part4-backplane-architecture.py)
via `scripts/generate_diagram.py`) show a client connected to instance A,
the test harness injecting an event through instance B, the shared backplane
fanning it across to A, and A delivering it to its own client, plus the
reconnect inset contrasting stateless loss against Kafka replay.

## Generated artifacts

Same convention as part3/part4-connection: `build/handling-event.schema.json`
(extracted from `contracts/asyncapi.yaml`) and `python/app/models_generated.py`
(generated from that schema) are build-time-only, gitignored, and
regenerated on every build, never committed.

## Related guides

- [WebSockets Next](https://quarkus.io/guides/websockets-next-reference)
- [SmallRye Reactive Messaging: Kafka](https://quarkus.io/guides/kafka-reactive-getting-started)
- [Redis client](https://quarkus.io/guides/redis)
- [`aiokafka`](https://aiokafka.readthedocs.io/)
- [`redis-py` asyncio client](https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html)
