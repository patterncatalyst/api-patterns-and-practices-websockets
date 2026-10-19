# Part 4 example — Python native `websockets` + FastAPI: connection concerns

Forks `examples/part3-handling-events/python` and layers four "keeping a
long-lived connection healthy" concerns on top of its plain fixture replay,
implementing the same `contracts/asyncapi.yaml` `handlingEvents` channel:

| Chapter | Concern | Where |
| --- | --- | --- |
| Ch12 | Backpressure / flow control | `app/outbound.py` |
| Ch13 | Error handling | `app/ws_server.py` (`_receive_loop`, `_error_envelope`) |
| Ch14 | Liveness / heartbeats | `app/ws_server.py` (`create_server`'s `ping_interval`/`ping_timeout`) |
| Ch17 | Security (JWT auth) | `app/auth.py`, `app/mint_token.py` |

The channel (`/ws/v1/bookings/{bookingId}/handling-events`) pushes the same
three `HandlingEvent`s (RECEIVE, LOAD, CUSTOMS) as Part 3, reusing Part 3's
shared fixture byte-for-byte (`../../part3-handling-events/fixtures/handling-events.json`)
rather than duplicating it — Part 4 is about connection concerns, not new
message content. The Quarkus sibling (`../quarkus/`) implements the same
four concerns against the same contract, so the two stacks are directly
comparable.

## Architecture

Two listeners, one process, one event loop (`app/main.py`) — unchanged from
Part 3:

- **`app/ws_server.py`** — the WebSocket endpoint, built on the native
  `websockets` library. Listens on `WS_HOST:WS_PORT` (default
  `0.0.0.0:8081`).
- **`app/http_app.py`** — a small FastAPI app (`/healthz`, `/`) for
  HTTP/app lifecycle, run under uvicorn on `HTTP_HOST:HTTP_PORT` (default
  `0.0.0.0:8082`).

## JWT auth (Ch17)

HS256, shared-secret tokens, carried as `?token=<jwt>` on the WebSocket
upgrade URL (per `contracts/asyncapi.yaml` `servers.local.bindings.ws`).
Secret: `WS_JWT_SECRET` (dev default: `dev-secret-change-me`; override it
for anything beyond local dev). Validation happens in `app/ws_server.py`'s
`handler`, immediately after the opening handshake completes and BEFORE any
fixture frame is sent — see that module's docstring for why rejection is a
post-accept WebSocket close (code **1008**) rather than an HTTP-level
`process_request` rejection.

Mint a token for local testing with `app/mint_token.py`:

```bash
uv run python -m app.mint_token                  # valid, 300s TTL
uv run python -m app.mint_token --mode expired
uv run python -m app.mint_token --mode bad-sig
```

PyJWT emits an `InsecureKeyLengthWarning` against the dev default
(`dev-secret-change-me` is 20 bytes; RFC 7518 §3.2 recommends >= 32 for
HS256). Expected and harmless for local dev; use a >= 32-byte random secret
via `WS_JWT_SECRET` for anything beyond that.

## Close codes

| Code | Meaning | Where |
| --- | --- | --- |
| `1008` | Auth failure (missing/invalid/expired/bad-sig token); also an unrecognized channel path | `app/ws_server.py` |
| `4400` | Malformed client message (private-use range) | `app/ws_server.py` |
| `4290` | Slow consumer / backpressure overrun (private-use range) | `app/outbound.py` |
| `1011` | Unexpected server-side error | `app/ws_server.py` |
| `1001` | Server going away (sent to every open connection when the server shuts down) | the `websockets` library's default `Server.close()` behavior |

## Error handling (Ch13): close-code-vs-envelope

This channel defines no client-to-server operation (server-push only), so
ANY frame a client sends is a protocol error. For that case the server sends
an in-band JSON error envelope **before** closing:

```json
{"error": {"code": "BAD_REQUEST", "message": "invalid JSON: ..."}}
```

...then closes with `4400`. The envelope carries human-readable detail a
client developer can log; the close code alone tells automated reconnect
logic *that* something ended and *roughly why*, without parsing a payload.
Cases that aren't about one specific bad message — auth failure (`1008`),
backpressure (`4290`), an unexpected server exception (`1011`) — rely on the
close code alone, since there's no single offending frame to annotate.

## Backpressure (Ch12)

`app/outbound.py`'s `OutboundQueue` decouples frame production from the
actual `websocket.send()` call via a bounded `asyncio.Queue`
(`OUTBOUND_QUEUE_MAXSIZE`, default 32). A sustained overrun — the queue
fills up, or a single `send()` hangs past `OUTBOUND_SEND_TIMEOUT_S` (default
5s) because the peer stopped reading — triggers
`OUTBOUND_BACKPRESSURE_POLICY`:

- `close` (default) — close the connection with `4290`. Safer default: an
  unbounded number of slow clients each holding a full queue is a
  resource-exhaustion path, and a dropped `HandlingEvent` is a correctness
  problem for this feed, not a superseded-by-the-next-update one.
- `drop` — log a warning and discard the triggering frame, keeping the
  connection open. Shown for comparison; not the right default for this
  channel's semantics (see `app/outbound.py`'s module docstring).

## Heartbeats (Ch14)

Delegated entirely to the `websockets` library: `create_server` passes
`ping_interval`/`ping_timeout` straight to `serve()`. The library sends a
ping every `ping_interval` seconds and closes the connection if no pong
arrives within `ping_timeout` seconds — no custom liveness code in this
module. Both are env-overridable (`WS_PING_INTERVAL_S` / `WS_PING_TIMEOUT_S`,
default 20s each) so a test can shrink the window to something it can wait
out.

## Build-time model generation

`app/models_generated.py` is **generated, gitignored, never committed** —
identical pipeline to Part 3:

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
uv run pytest                 # schema conformance + auth + error-envelope tests

uv run python -m app.main     # starts both listeners
```

Then, from the repo root, with `examples/_lib/lib.sh` sourced:

```bash
source examples/_lib/lib.sh
ensure_websocat

BOOKING=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
URL="ws://localhost:8081/ws/v1/bookings/${BOOKING}/handling-events"

wait_for_ws localhost:8081 "/ws/v1/bookings/${BOOKING}/handling-events"

# Valid token: receives the RECEIVE frame.
TOKEN="$(uv run python -m app.mint_token)"
frame="$(ws_first_frame_auth "$URL" "$TOKEN")"
schema_validate "$frame" build/handling-event.schema.json

# Missing/bad token: rejected, no frame, close 1008.
assert_ws_rejected "$URL"
BAD_TOKEN="$(uv run python -m app.mint_token --mode bad-sig)"
assert_ws_rejected "${URL}?token=${BAD_TOKEN}"
```

## Container build

Build from the **repo root** (the context needs to reach `contracts/` and
the shared fixture under `examples/part3-handling-events/`):

```bash
docker build -f examples/part4-connection/python/Containerfile \
  -t ch12-connection-concerns-python .
docker run --rm -p 8081:8081 -p 8082:8082 ch12-connection-concerns-python
```

## Pinned versions

| Tool / package | Version |
| --- | --- |
| Python | 3.15 (3.15.0 locally) |
| uv | 0.13.1 |
| fastapi | 0.146.0 |
| websockets | 17.2 |
| uvicorn[standard] | 0.54.0 |
| pyjwt | 2.15.1 (exact pin) |
| opentelemetry-distro | 0.66b1 (declared; not yet wired into the entrypoint, same scope note as Part 3) |
| datamodel-code-generator (dev) | 0.86.0 |
| jsonschema (dev) | 4.26.0 |
| pytest (dev) | 9.1.1 |
| UBI base image | `registry.access.redhat.com/ubi10/python-314-minimal:10.2-1791928506` |
