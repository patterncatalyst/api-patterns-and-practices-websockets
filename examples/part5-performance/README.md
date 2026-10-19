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

## k6 (DRQ-023/DRQ-027)

Two scripts under [`k6/`](k6/), pinned to **k6 2.3.0** — same pin as Part
4's `k6/smoke.js` scripts (contracts/README.md, Ch0 version matrix). Both
use the stable `k6/ws` module: it has no dedicated subprotocols field, so
the `Sec-WebSocket-Protocol` is offered as a plain request header, and it
dispatches a distinct `binaryMessage` event (ArrayBuffer payload) for
Protobuf's binary frames, confirmed against the pinned release's own source
(`github.com/grafana/k6` tag `v2.3.0`,
`internal/js/modules/k6/ws/ws.go:215-218`) — no need for
`k6/experimental/websockets` here.

### `k6/smoke.js` — GATED, CI

Smoke-level only (3 VUs, 1 iteration each, no ramp — the same shape as
`examples/part4-*/k6/smoke.js`): against **one** stack at a time, each VU
opens the channel twice — offering `+json`, then `+protobuf` — and asserts
the upgrade, the subprotocol echo, and that the 3 fixture frames arrive on
the wire opcode the negotiated encoding promises (TEXT for `+json`, BINARY
for `+protobuf`). A failed check fails the k6 run, and thus the PR, the
same DRQ-023 contract Part 4's smoke jobs already use.

```bash
docker compose up --build -d quarkus python

K6_WS_URL="ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
  k6 run k6/smoke.js   # Quarkus

K6_WS_URL="ws://localhost:8091/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
  k6 run k6/smoke.js   # Python
```

Env vars: `K6_WS_URL` (required — selects the stack), `K6_SUBPROTOCOL`
(optional — exercise only `handling-events.v1+json` or
`handling-events.v1+protobuf` in a given invocation; default: both).
**Confirmed live** against both stacks (this project's own CI runner,
2026-10-19): 54/54 checks passed on Quarkus `:8090` and 54/54 on Python
`:8091` — both JSON-as-TEXT and Protobuf-as-BINARY, both stacks.

### `k6/benchmark.js` — comparative, LOCAL only

**Not** part of the CI gate — DRQ-027: absolute throughput is
host-dependent, which would make a flaky CI threshold. Run it by hand
against a stack on your own machine; its printed comparison is what Ch20
cites. Runs three scenarios **concurrently** against the same target —
`json`, `protobuf`, and `json_deflate` (JSON + `compression: "deflate"`,
i.e. permessage-deflate, RFC 7692) — each a `ramping-vus` executor that
repeatedly opens a fresh connection, reads the 3 fixture frames, and
closes, as fast as it can for the sustained-load window.

```bash
docker compose up --build -d quarkus python

K6_WS_URL="ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
PART5_BENCH_VUS=5 PART5_BENCH_DURATION=15s \
  k6 run k6/benchmark.js
```

Env vars: `K6_WS_URL` (target stack), `PART5_BENCH_VUS` (per-scenario VU
count, default 5), `PART5_BENCH_DURATION` (per-scenario sustained-load
duration, default 15s). **Not** named `K6_VUS`/`K6_DURATION` — those are
k6-reserved env vars that, if set, silently discard this script's
`options.scenarios` for a single default scenario (confirmed live: k6 logs
`"env" level configuration overrode scenarios configuration entirely` and
then fails outright, since this script has no default-exported function).

To also push these metrics into the project's LGTM stack (DRQ-006,
`docker compose --profile observability up`), add k6's built-in
OpenTelemetry metrics output on the command line — no script change
needed:

```bash
K6_OTEL_GRPC_EXPORTER_INSECURE=true K6_OTEL_GRPC_EXPORTER_ENDPOINT=localhost:4317 \
  k6 run -o opentelemetry k6/benchmark.js
```

(Confirmed only that pinned k6 2.3.0 ships this output — `k6 run --help`'s
Outputs section lists `k6 run -o opentelemetry`; a live LGTM round-trip for
this script was not separately exercised. The console summary below is the
path actually run end to end.)

**What this does NOT measure:** this channel replays its 3 fixture events
on connect and then stays idle (no further pushes) — there is no sustained
in-connection stream, so "messages/sec" below is connection-churn
throughput (connects/sec × 3), not a steady push rate. And for
`json_deflate`: `k6/ws` (gorilla/websocket) **transparently inflates** a
compressed frame before handing its bytes to the script — there is no
k6/ws API to read the on-the-wire compressed length. That scenario's
bytes-per-frame is expected to read identically to the plain `json` row;
it proves nothing about deflate's wire savings. What it DOES prove is
whether the extension was negotiated at all (read from the echoed
`Sec-WebSocket-Extensions` response header).

**Real numbers, captured live on this project's dev box (2026-10-19,
`PART5_BENCH_VUS=2`, `PART5_BENCH_DURATION=8s`, each stack freshly
restarted and given time for the OS's ephemeral TCP port range to drain
`TIME_WAIT` before measuring — see the caveat below):**

| Stack | Encoding | bytes/frame (avg / p90) | connects (success %) | frames/sec |
|---|---|---:|---:|---:|
| Quarkus `:8090` | json | 259.7B / 267.0B | 9868/11967 (82.5%) | 2114.2/s |
| Quarkus `:8090` | protobuf | 154.0B / 157.0B | 9911/12001 (82.6%) | 2123.4/s |
| Quarkus `:8090` | json+deflate | 259.7B / 267.0B | 9718/11806 (82.3%) | 2082.0/s |
| Python `:8091` | json | 259.7B / 267.0B | 7952/7952 (100.0%) | 1703.9/s |
| Python `:8091` | protobuf | 154.0B / 157.0B | 7943/7943 (100.0%) | 1701.9/s |
| Python `:8091` | json+deflate | 259.7B / 267.0B | 7908/7908 (100.0%) | 1694.4/s |

The **bytes/frame column was identical across every run of this benchmark**
regardless of load (it's the fixture frame size, not a function of
throughput) — Protobuf measures **40.7% smaller** (154.0B vs. 259.7B avg),
consistent with the per-event table above. `json+deflate`'s bytes/frame
reads the same as plain `json` in every run, exactly as the caveat above
predicts.

**permessage-deflate negotiation differed by stack, reproduced across every
run**: Python's `websockets` server negotiated the extension on every
successful connect (`negotiated: 7908/7908` in the run above); Quarkus's
WebSockets Next (Undertow) **never** negotiated it in any run of this
benchmark (`negotiated: 0` out of 11806–18292 attempts across three
separate runs) — a real, reproducible difference between the two stacks'
WebSocket server implementations, not a fluke of one run.

**Connect success rate is a local-host artifact, not an encoding effect**:
at this benchmark's default pace (no think time — each VU reconnects as
fast as it can), the three scenarios' success rates track each other
within a run (encoding choice doesn't change the ceiling), but the
absolute rate varies run to run with recent load on the dev box — this
project also measured 100%/100%/100% on Quarkus on a freshly-booted
container before any other k6 run had touched it, and as low as 2/6108
(port exhaustion: ~55k connections from an immediately-preceding run had
left the OS ephemeral port range full of `TIME_WAIT` sockets) when two
heavy runs were fired back to back with no cooldown. Give the stack's
container a few seconds after startup, and this script some idle time
between back-to-back invocations, for a representative number — both
caveats are also called out in `k6/benchmark.js`'s header comment.

### Gated vs. local — the house pattern

Same split as `examples/part4-*`'s `k6-smoke` CI job and build-plan.md's
DRQ-023/DRQ-027: `smoke.js` is fast, deterministic, and gated (a failed
check fails the PR); `benchmark.js` is comparative, host-dependent, and
local-only (run it, read the summary, cite the numbers in prose — don't
wire it into a CI threshold).

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
