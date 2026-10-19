# Part 5 example — Python native `websockets` + FastAPI: JSON vs Protobuf

Forks `examples/part4-connection/python` and drops its four connection
concerns (backpressure, error handling, heartbeats, JWT auth) to isolate
what Part 5 is actually about (Ch19, "Binary Protobuf over WebSockets";
Ch20, "Optimizing throughput"): the SAME `contracts/asyncapi.yaml`
`handlingEvents` channel, served over **two wire encodings** of the exact
same `HandlingEvent` message —

| Encoding | Frame type | Selected by |
| --- | --- | --- |
| JSON text (default) | `ws.send(str)` | `Sec-WebSocket-Protocol: handling-events.v1`, `handling-events.v1+json`, or no subprotocol at all |
| Protobuf binary | `ws.send(bytes)` | `Sec-WebSocket-Protocol: handling-events.v1+protobuf` |

The channel (`/ws/v1/bookings/{bookingId}/handling-events`) pushes the same
three `HandlingEvent`s (RECEIVE, LOAD, CUSTOMS) as Parts 3 and 4, reusing
Part 3's shared fixture byte-for-byte
(`../../part3-handling-events/fixtures/handling-events.json`) — field VALUES
are identical in both encodings (RFC-3339 string timestamps, decimal-string
Money), so a reader can compare the two frames for the same event directly.
The Quarkus sibling (`../quarkus/`) implements the same negotiation against
the same contract, so the two stacks are directly comparable.

## Architecture

Two listeners, one process, one event loop (`app/main.py`):

- **`app/ws_server.py`** — the WebSocket endpoint, built on the native
  `websockets` library. Listens on `WS_HOST:WS_PORT` (default
  `0.0.0.0:8091`). Negotiates the subprotocol via `select_subprotocol`
  (overriding the library's default, which would reject a client that
  offers no subprotocol at all — see that module's docstring) and replays
  the fixture in the negotiated encoding.
- **`app/http_app.py`** — a small FastAPI app (`/healthz`, `/`) for
  HTTP/app lifecycle, run under uvicorn on `HTTP_HOST:HTTP_PORT` (default
  `0.0.0.0:8092`).
- **`app/mapper.py`** — converts a validated `HandlingEvent` (the generated
  Pydantic model) to/from its Protobuf twin (`app/handling_event_pb2.py`),
  operating on `model_dump(mode="json")` values so the Protobuf and JSON
  field values stay byte-for-byte identical (DRQ-025).

## Encoding negotiation (DRQ-026)

A client offers one or more values in `Sec-WebSocket-Protocol` on the
upgrade request. The server picks the first value in its own declared
preference order (`app/ws_server.py`'s `SUPPORTED_SUBPROTOCOLS`: bare `v1`,
then `+json`, then `+protobuf` — the same order the Quarkus sibling declares
in `quarkus.websockets-next.server.supported-subprotocols`, so a client that
offers more than one gets the same encoding from either stack) that the
client also offered, and defaults to JSON for a client that offers no
subprotocol at all:

```
handling-events.v1            -> JSON text frames
handling-events.v1+json       -> JSON text frames (equivalent to the bare value)
handling-events.v1+protobuf   -> Protobuf binary frames (only when nothing earlier in the list was offered)
(no Sec-WebSocket-Protocol)   -> JSON text frames (default)
```

The negotiated value — or its absence — is echoed back by the WebSocket
handshake as the `Sec-WebSocket-Protocol` response header (standard
RFC 6455 §4.2.2 behavior from the `websockets` library; no response header
at all when no subprotocol was selected).

## Build-time code generation

Both `app/models_generated.py` (JSON) and `app/handling_event_pb2.py`
(+`.pyi`, Protobuf) are **generated, gitignored, never committed**:

```bash
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./scripts/generate-models.sh    # JSON: app/models_generated.py
./scripts/generate-proto.sh     # Protobuf: app/handling_event_pb2.py(+.pyi)
```

`scripts/generate-proto.sh` compiles `contracts/handling-event.proto` with
`grpcio-tools`' bundled `protoc` (`python -m grpc_tools.protoc`) — this site
has no gRPC service, only the message-class generator is used (see
`_plans/version-matrix.md`).

## Run it

```bash
uv sync --group dev
./scripts/generate-models.sh
./scripts/generate-proto.sh
uv run pytest                 # schema conformance + proto round-trip + size assertion

uv run python -m app.main     # starts both listeners
```

Then, from the repo root, with `examples/_lib/lib.sh` sourced:

```bash
source examples/_lib/lib.sh
ensure_websocat

BOOKING=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
URL="ws://localhost:8091/ws/v1/bookings/${BOOKING}/handling-events"

wait_for_ws localhost:8091 "/ws/v1/bookings/${BOOKING}/handling-events"

# JSON (default / explicit)
json_frame="$(websocat -1 -n -t --protocol handling-events.v1+json "$URL" </dev/null)"
schema_validate "$json_frame" build/handling-event.schema.json

# Protobuf (binary) — websocat prints raw bytes; pipe to a small decoder
# built on the generated stub to confirm it parses and matches the JSON
# frame's values (see tests/test_contract.py for the same assertion in
# pure Python).
websocat -1 -n -b --protocol handling-events.v1+protobuf "$URL" </dev/null > /tmp/first.bin
```

## Container build

Build from the **repo root** (the context needs to reach `contracts/` and
the shared fixture under `examples/part3-handling-events/`):

```bash
docker build -f examples/part5-performance/python/Containerfile \
  -t ch19-performance-python .
docker run --rm -p 8091:8091 -p 8092:8092 ch19-performance-python
```

## Pinned versions

| Tool / package | Version |
| --- | --- |
| Python | 3.15 (3.15.0 locally) |
| uv | 0.13.1 |
| fastapi | 0.146.0 |
| websockets | 17.2 |
| uvicorn[standard] | 0.54.0 |
| protobuf | 7.36.2 (exact pin) |
| opentelemetry-distro | 0.66b1 (declared; not yet wired into the entrypoint, same scope note as Parts 3/4) |
| grpcio-tools (dev) | 1.84.0 (exact pin; codegen only, no gRPC service on this site) |
| datamodel-code-generator (dev) | 0.86.0 |
| jsonschema (dev) | 4.26.0 |
| pytest (dev) | 9.1.1 |
| UBI base image | `registry.access.redhat.com/ubi10/python-314-minimal:10.2-1791928506` |
