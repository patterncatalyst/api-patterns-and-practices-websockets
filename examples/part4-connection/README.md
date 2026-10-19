# Part 4 "Connection Concerns" — the `handlingEvents` channel, hardened

Forks [`examples/part3-handling-events`](../part3-handling-events): the same
[`operations.receiveHandlingEvent`](../../contracts/asyncapi.yaml) channel —
one WebSocket connection per booking, server pushing a `HandlingEvent` every
time one is recorded, replaying the shared fixture on open — now hardened
with the four "keeping a long-lived connection healthy" concerns this part
covers. Quarkus (`quarkus/`, host port `8080`, WebSockets Next) and Python
(`python/`, host port `8081`, native `websockets` + FastAPI on `8082`)
independently implement all four, against the same contract, sharing the
same JWT secret and the same close-code numbers — a client sees identical
behavior regardless of which stack it talks to. `verify.sh` opens
connections against **both** stacks and asserts that live.

## The four concerns and their close codes

| Chapter | Concern | Where | Close code |
|---|---|---|---|
| Ch17 | JWT auth | `quarkus/.../connection/JwtHs256.java`, `python/app/auth.py` | `1008` (policy violation) on any failure — missing, malformed, bad signature, or expired token. Every failure mode collapses to the same code so a prober can't learn which check failed. |
| Ch13 | Error taxonomy | `quarkus/.../HandlingEventConnectionWebSocket#onTextMessage`, `python/app/ws_server.py` | `4400` (app range) — this channel accepts no client-to-server frames, so ANY client frame gets an in-band `{"error":{"code":"BAD_REQUEST","message":"..."}}` envelope first, then the close. |
| Ch12 | Outbound backpressure | `quarkus/.../OutboundBackpressureGuard.java`, `python/app/outbound.py` | `4290` (app range) — the CLOSE policy for a sustained outbound overrun. `DROP` is also implemented (see each app's README) but `CLOSE` is the channel's default. |
| Ch14 | Heartbeats / liveness | Quarkus: `HeartbeatLivenessSweep` (a scheduled, pong-tracked liveness check); Python: the `websockets` library's `ping_interval`/`ping_timeout` keepalive | Quarkus: `4408` (app range, `CloseCodes.LIVENESS_TIMEOUT`) once `example.heartbeat.liveness-timeout` passes with no pong. Python: `1011` (the library's own hardcoded keepalive-failure code) — the two stacks agree on WHEN a silent peer is closed, not the exact numeric code; see the Quarkus app's README Ch14 section. |

Two more codes exist and are shared across both stacks but aren't exercised
by `verify.sh` (no deterministic trigger from outside the process):
`1011` (unmapped server-side exception) and `1001` (graceful shutdown —
every open connection gets this when the process stops).

## The fixture is not duplicated here

[`../part3-handling-events/fixtures/handling-events.json`](../part3-handling-events/fixtures/handling-events.json)
is the single source of truth for both this part's apps, reused byte for
byte (see each app's README for exactly how its build pulls it in). Part 4
is about connection concerns, not new message content — the `HandlingEvent`
shape and the 3-event RECEIVE/LOAD/CUSTOMS sequence are unchanged from
part3.

## Run it

```bash
cd examples/part4-connection
./verify.sh
```

This brings both services up with `docker compose` (shared `WS_JWT_SECRET`,
see `compose.yaml`), then for **each** stack:

1. Mints one shared-secret JWT and opens the channel with it — asserts the
   first frame is the fixture's `RECEIVE` event and schema-validates it
   against the contract-derived JSON Schema.
2. Asserts four distinct token failures (no token, a garbage string, an
   expired token, a bad-signature token) are all rejected — no data, close
   `1008`.
3. Sends a malformed client frame on an otherwise-authenticated connection
   and asserts both the in-band `BAD_REQUEST` envelope arrives AND the
   connection closes with `4400` — via a small Python probe
   (`websockets`-library based), since `websocat` can't observe close
   codes reliably.
4. Spins up a **one-off** instance of that stack's image with its
   backpressure threshold forced down to the value that trips
   deterministically on the very first fixture burst, and asserts the
   connection closes with `4290` before any frame is delivered. Quarkus's
   threshold is `0` (its guard trips on `pending > threshold`, so `0`
   fails before the first send); Python's is `1`, **not** `0` — Python's
   `OutboundQueue` sits on `asyncio.Queue`, where `maxsize<=0` means
   *unbounded*, the opposite of a deterministic trigger (confirmed
   empirically while building this harness). `1` works because all 3
   fixture events are enqueued synchronously before the drain task ever
   runs, so the second `enqueue()` always overflows a `maxsize=1` queue.

5. Spins up a second pair of **one-off** instances (Step 6) with their
   ping/liveness windows forced down to a few seconds, opens each with a
   hand-rolled raw-socket client (plain `socket`, no WebSocket library)
   that completes the opening handshake and then sends absolutely nothing
   else — no pong, no close — and asserts the server itself closes that
   genuinely silent peer within a short, bounded wait. Neither `websocat`
   nor the `websockets` client library used elsewhere in this harness can
   manufacture that condition (both answer pings automatically at the
   protocol level, which both apps' own READMEs note) — the raw socket
   sidesteps that limitation.

**The naive Quarkus approach (auto-ping-interval + Vert.x idle-timeout
alone) does NOT detect a dead peer — confirmed live while building this
harness**, and is why Quarkus's real detector is a dedicated bean,
`HeartbeatLivenessSweep`, not just those two settings. Vert.x's
`http.idle-timeout` resets on BOTH read and write activity, and the
server's own outbound ping is write activity on that same connection — so
a server that keeps pinging a silent peer keeps resetting its own idle
clock, and idle-timeout alone never fires for a peer that only fails to
answer (a raw-socket probe against that configuration stayed open past 75
seconds, where the Python stack's equivalent probe correctly closed at its
documented ~40s window). `HeartbeatLivenessSweep` instead stamps a
per-connection pong timestamp on open and on every pong, and a
`@Scheduled` sweep requests a close (`4408`) on any connection whose last
pong is older than a configurable threshold — no dependence on any
transport-level idle timer. The TCP socket itself doesn't drop the instant
that threshold is crossed: closing a WebSocket is a two-way handshake, and
a peer the sweep just proved isn't responding won't acknowledge that
either, so Vert.x waits out its own ~10s closing-handshake grace before
forcibly tearing the connection down — Step 6's timeout budget accounts
for this. See `quarkus/README.md`'s Ch14 section and
`HeartbeatLivenessSweep`'s Javadoc for the full design.

Prints `PASS` only if every REQUIRED assertion (auth accept + all 4 reject
modes, the error-taxonomy envelope + `4400`, the `4290` backpressure close
on at least one deterministic one-off run per stack, AND the Ch14 silent
peer closing within the short detection window on both stacks) holds.

### Ports

| Service | Host port | Purpose |
|---|---|---|
| `quarkus` | `8080` | WS upgrade + the `handlingEvents` channel (JWT via `?token=`) |
| `python` | `8081` | WS upgrade + the `handlingEvents` channel (native `websockets` library) |
| `python` | `8082` | HTTP: `/healthz`, `/` (FastAPI/uvicorn, app lifecycle only) |

The one-off backpressure containers `verify.sh` spins up for Step 5 run on
`18080` (Quarkus) and `18091` (Python); the one-off heartbeat containers for
Step 6 run on `18082` (Quarkus) and `18092` (Python) — all four so they
don't collide with the primary stack, which stays up throughout the run.

### Env knobs

| Env var | Stack | Default | Purpose |
|---|---|---|---|
| `WS_JWT_SECRET` | both | `dev-secret-change-me` (image default); `compose.yaml` overrides to a dedicated shared test value | HS256 signing secret |
| `EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS` | Quarkus | `32` | outbound in-flight send cap |
| `EXAMPLE_BACKPRESSURE_POLICY` | Quarkus | `CLOSE` | `CLOSE` or `DROP` |
| `OUTBOUND_QUEUE_MAXSIZE` | Python | `32` | outbound queue depth (`<=0` is **unbounded**, not zero-capacity — see above) |
| `OUTBOUND_BACKPRESSURE_POLICY` | Python | `close` | `close` or `drop` |
| `QUARKUS_WEBSOCKETS_NEXT_SERVER_AUTO_PING_INTERVAL` | Quarkus | `20` | ping interval |
| `EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT` / `EXAMPLE_HEARTBEAT_SWEEP_INTERVAL` | Quarkus | `45s` / `5s` | `HeartbeatLivenessSweep`'s dead-peer threshold / how often it checks — the ACTUAL Ch14 detector (not `QUARKUS_HTTP_IDLE_TIMEOUT`, which doesn't detect a silent peer at all — see above) |
| `WS_PING_INTERVAL_S` / `WS_PING_TIMEOUT_S` | Python | `20` / `20` | heartbeat interval / timeout (same ~40s window) |

### Observability (opt-in)

Same convention as part3 — off by default so a first boot and CI stay fast:

```bash
./verify.sh --profile observability
# or, by hand:
docker compose --profile observability up --build
```

### k6 smoke load (DRQ-023)

[`k6/smoke.js`](k6/smoke.js) is a deliberately SMOKE-level load script (3
VUs, 1 iteration each, no ramp) — it mints one shared-secret JWT, opens the
channel, asserts the upgrade succeeds and the 3 fixture frames arrive
correctly shaped, holds briefly, then closes. It is NOT a stress/load test;
treat it as a fast liveness gate, not a capacity benchmark.

```bash
docker compose up --build -d quarkus python
TOKEN="$(cd python && uv run python -m app.mint_token)"

# against Quarkus (:8080)
k6 run -e K6_WS_URL="ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
       -e K6_TOKEN="$TOKEN" k6/smoke.js

# against Python (:8081)
k6 run -e K6_WS_URL="ws://localhost:8081/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
       -e K6_TOKEN="$TOKEN" k6/smoke.js

docker compose down -v --remove-orphans
```

No local `k6`? Use the pinned image instead (same one the CI gate uses,
`docker.io/grafana/k6:2.3.0` — see Ch0's version matrix):

```bash
docker run --rm --network host \
  -e K6_WS_URL="ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
  -e K6_TOKEN="$TOKEN" \
  -v "$(pwd)/k6:/scripts" \
  docker.io/grafana/k6:2.3.0 run /scripts/smoke.js
```

**CI context:** the `contracts.yml` workflow's `k6-smoke` job runs this
script against BOTH stacks on every push/PR — a k6 threshold failure (any
failed check) fails that job, and thus the PR (DRQ-023's "gated", not
merely opt-in). The job mints its own token the same way shown above and
tears the stack down afterward.

## Diagram

[`../../assets/diagrams/part4-connection-architecture.svg`](../../assets/diagrams/part4-connection-architecture.svg) /
`part4-connection-architecture.excalidraw` (generated with
[`scripts/diagrams/part4-connection-architecture.py`](../../scripts/diagrams/part4-connection-architecture.py)
via `scripts/generate_diagram.py`) show the client opening the channel
against each stack with a token on the upgrade URL, the auth gate both
stacks apply before any fixture frame is sent, the error/close-code paths
(`1008`/`4400`/`4290`/`4408`), the heartbeat loop, and the
outbound-backpressure guard sitting in front of the fixture replay.

## Generated artifacts

Same as part3: `build/handling-event.schema.json` (extracted from
`contracts/asyncapi.yaml`) and `python/app/models_generated.py` (generated
from that schema) are build-time-only, gitignored, and regenerated on every
build — never committed.
