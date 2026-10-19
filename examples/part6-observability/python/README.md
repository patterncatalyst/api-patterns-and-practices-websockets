# Part 6 example — Python native `websockets` + FastAPI: live OpenTelemetry

Forks `examples/part3-handling-events/python`'s plain fixture-replay layout
(native `websockets` server + FastAPI, same ports, same `uv` project shape)
and wires in live OpenTelemetry traces + metrics, exported to the shared
LGTM stack (Grafana/Loki/Tempo/Mimir), for Ch23 — this book's one
observability anchor, in both stacks (see `../quarkus/`).

## The finding this chapter demonstrates

The process runs under `opentelemetry-instrument` (see `Containerfile`),
which zero-code auto-instruments the FastAPI app (`app/http_app.py`) via
`opentelemetry-instrumentation-fastapi`. **There is no equivalent
instrumentation package for the native `websockets` library** — no
`opentelemetry-instrumentation-websockets` exists, and `websockets` exposes
no OTel hook of its own. A trace that only covered the HTTP side would never
show the WebSocket connection at all, even though that connection is the
actual feed this whole book is about.

`app/ws_server.py` closes that gap with a **manual span**:
`tracer.start_as_current_span("ws.handling-events.connection")`, using the
OTel SDK tracer directly, inside the connection handler. The global
`TracerProvider` + OTLP exporter are still configured by
`opentelemetry-instrument` before `app/main.py` ever runs — only the span
itself is hand-written; nothing else about configuring the SDK changes.

## Architecture

Two listeners, one process, one event loop (`app/main.py`) — unchanged from
Part 3/4:

- **`app/ws_server.py`** — the WebSocket endpoint, built on the native
  `websockets` library. Listens on `WS_HOST:WS_PORT` (default
  `0.0.0.0:8081`). Opens the manual `ws.handling-events.connection` span per
  connection, logs the trace-id correlation line, and increments
  `handling_events_delivered_total` once per delivered `HandlingEvent`.
- **`app/http_app.py`** — a small FastAPI app (`/healthz`, `/`, `/metrics`)
  for HTTP/app lifecycle, run under uvicorn on `HTTP_HOST:HTTP_PORT`
  (default `0.0.0.0:8082`). Auto-instrumented by
  `opentelemetry-instrumentation-fastapi` — no tracing code in that module.
- **`app/feed.py`** — loads + validates the shared fixture (reused
  byte-for-byte from `../../part3-handling-events/fixtures/handling-events.json`;
  Part 6 is about observability, not new message content).
- **`app/mapper.py`** — maps a validated `HandlingEvent` to its outbound
  wire frame (JSON). Split out from `feed.py` (unlike Part 3/4, which fold
  this into `sequence_as_json`) because `app/ws_server.py` needs a per-event
  hook, at the point a frame actually leaves the server, to increment the
  delivered-events counter — see that module's docstring.
- **`app/metrics.py`** — the `handling_events_delivered_total` Prometheus
  counter (DRQ-029), scraped by `app/http_app.py`'s `/metrics`.

No auth, backpressure policy, or heartbeat tuning here — those are Part 4's
concerns (`examples/part4-connection`). This example forks Part 3's plain
layout deliberately, so the only new thing on the wire path is the
observability this chapter is about.

## The trace-id log line (shared convention, both stacks)

Every connection logs exactly one line correlating the manual span with its
trace id, in this exact shape (identical on the Quarkus sibling):

```
otel.trace_id=<32-hex-trace-id> span=ws.handling-events.connection bookingId=<bookingId> instance=part6-observability-python
```

`instance` comes from `OTEL_SERVICE_NAME` (same value the `Containerfile`
bakes in, falling back to the same default if unset — e.g. under
`uv run python -m app.main` with no OTel env set at all).

## The metric: `handling_events_delivered_total`

A `prometheus-client` `Counter`, no labels, incremented once per
`HandlingEvent` frame actually sent to a client — the Python-stack
counterpart of the Quarkus sibling's Micrometer counter of the same name.
Scraped at `GET /metrics` on the HTTP port (`8082`).

## Run it

```bash
uv sync --group dev
./scripts/generate-models.sh
uv run pytest                 # schema conformance + trace-id log line + counter tests

uv run opentelemetry-instrument python -m app.main     # starts both listeners, OTel wired
# or, without the OTel wrapper (SDK still runs; FastAPI auto-instrumentation
# just doesn't attach — see app/main.py's docstring):
uv run python -m app.main
```

By default `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, so the OTLP exporter has
nothing to talk to — it logs failed export attempts in the background and
never blocks startup or a request. Point it at the shared LGTM stack to see
real traces in Tempo and real metrics scraped into Mimir:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # or http://lgtm:4317 under compose
export OTEL_SERVICE_NAME=part6-observability-python
uv run opentelemetry-instrument python -m app.main
```

Then, from the repo root, with `examples/_lib/lib.sh` sourced:

```bash
source examples/_lib/lib.sh
ensure_websocat

BOOKING=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
URL="ws://localhost:8081/ws/v1/bookings/${BOOKING}/handling-events"

wait_for_ws localhost:8081 "/ws/v1/bookings/${BOOKING}/handling-events"

frame="$(ws_first_frame "$URL")"
schema_validate "$frame" build/handling-event.schema.json

curl -s localhost:8082/metrics | grep handling_events_delivered_total
```

## Container build

Build from the **repo root** (the context needs to reach `contracts/` and
the shared fixture under `examples/part3-handling-events/`):

```bash
docker build -f examples/part6-observability/python/Containerfile \
  -t ch23-observability-python .
docker run --rm -p 8081:8081 -p 8082:8082 \
  -e OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4317 \
  ch23-observability-python
```

## Build-time model generation

`app/models_generated.py` is **generated, gitignored, never committed** —
identical pipeline to Part 3/4:

```bash
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./scripts/generate-models.sh
```

## Pinned versions

| Tool / package | Version |
| --- | --- |
| Python | 3.15 (3.15.0 locally) |
| uv | 0.13.1 |
| fastapi | 0.148.0 |
| websockets | 17.2 |
| uvicorn[standard] | 0.54.0 |
| opentelemetry-distro | 0.66b1 |
| opentelemetry-exporter-otlp-proto-grpc | 1.45.1 |
| opentelemetry-instrumentation-fastapi | 0.66b1 |
| prometheus-client | 0.26.0 |
| datamodel-code-generator (dev) | 0.86.0 |
| jsonschema (dev) | 4.26.0 |
| pytest (dev) | 9.1.1 |
| UBI base image | `registry.access.redhat.com/ubi10/python-314-minimal:10.2-1791928506` |
