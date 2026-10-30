# Part 6 "Observability": the `handlingEvents` channel with live OpenTelemetry

Forks [`examples/part3-handling-events`](../part3-handling-events): the same
[`operations.receiveHandlingEvent`](../../contracts/asyncapi.yaml) channel
(one WebSocket connection per booking, replaying the shared fixture on open),
now instrumented with live OpenTelemetry traces and
Micrometer/`prometheus-client` metrics, instead of part4's
connection-hardening concerns. Quarkus (`quarkus/`, host port `8080`,
WebSockets Next) and Python (`python/`, host port `8081` + metrics on
`8082`, native `websockets` + FastAPI) each independently implement the same
observability behavior against the same contract. `verify.sh` opens a
connection against **both** stacks and proves the OTel wiring live.

## Why this chapter exists

Every earlier part wires the OTel SDK but leaves it **inert**: Quarkus ships
`quarkus.otel.sdk.disabled=true`, the Python entrypoint never runs under
`opentelemetry-instrument`, and the `lgtm` compose service sits behind an
unused `observability` profile, so nothing ever lands in Tempo. This part
turns all three of those on: `quarkus.otel.sdk.disabled=false`, the Python
`Containerfile`'s `ENTRYPOINT ["opentelemetry-instrument", ...]`, and `lgtm`
as a **hard dependency** in `compose.yaml` (no `profiles:` guard; see that
file's header comment). This is the observability example; there is no
reduced-speed path without it.

### Native `websockets` has no OTel auto-instrumentation

`opentelemetry-instrumentation-fastapi` auto-traces the Python app's HTTP
side (`app/http_app.py`) with zero code. There is **no**
`opentelemetry-instrumentation-websockets` package, and the native
`websockets` library exposes no OTel hook of its own: a trace that only
covered the HTTP side would never show the WebSocket connection at all,
even though that connection is the one thing this whole book is about.
`app/ws_server.py` closes that gap with a **manual span**,
`tracer.start_as_current_span("ws.handling-events.connection")`, using the
OTel SDK tracer directly (the global `TracerProvider`/OTLP exporter are
already configured by `opentelemetry-instrument`; only the span itself is
hand-written).

Quarkus's story is the mirror image: `quarkus-opentelemetry` already
auto-traces the HTTP upgrade itself, so `HandlingEventObservabilityWebSocket#onOpen`
adds a **child** span via `@WithSpan`, not because Quarkus lacks WebSocket
instrumentation of its own, but because the goal is a span that covers
the fixture-replay push specifically, parented under the upgrade span,
consistent with the Python sibling's connection-scoped span.

## Shared conventions, both stacks (`verify.sh` asserts both uniformly)

- **OTLP export**: both stacks honor `OTEL_EXPORTER_OTLP_ENDPOINT`
  (`compose.yaml` sets `http://lgtm:4317`, gRPC).
- **Connection span**: `ws.handling-events.connection`, one per connection,
  covering the whole fixture-replay push.
- **Trace-id log line**: exactly one structured line per connection, in the
  identical shape on both stacks:

  ```
  otel.trace_id=<32-hex-trace-id> span=ws.handling-events.connection bookingId=<bookingId> instance=part6-observability-<stack>
  ```

- **Metric**: `handling_events_delivered_total` (a counter, no labels)
  increments once per `HandlingEvent` handed off to be sent:
  Micrometer→Prometheus on Quarkus (`/q/metrics`), `prometheus-client` on
  Python (`:8082/metrics`).

See each stack's own README (`quarkus/README.md`, `python/README.md`) for
the exact code paths.

## HARD vs. SOFT verification

Following the same HARD/SOFT split as the gRPC sibling's
`examples/21-observability/verify.sh`:

- **HARD** (fails the build): the connection's trace id appears in the
  app's own structured log line, and the app's own metrics endpoint
  shows `handling_events_delivered_total` > 0. Both are synchronous checks
  against the app itself, with no waiting on an external pipeline.
- **SOFT** (warns, never fails): Tempo's query API
  (`:3200/api/traces/<trace-id>`) eventually shows a span named
  `ws.handling-events.connection` for that trace id. Bounded-retry poll
  (10 attempts × 3s); a timeout logs a `WARN` and `verify.sh` still exits 0.
  Ingest lag through the collector → Tempo pipeline is expected, especially
  right after `lgtm`'s cold start: this check exists to report whether the
  full pipeline worked, not to gate on it.

Why the split: proving the span/log-line/counter wiring is deterministic and
should never flake CI; proving a specific trace id is *queryable in Tempo
within N seconds* depends on a cold multi-process collector pipeline and
isn't a fair thing to gate a merge on.

## Run it

```bash
cd examples/part6-observability
./verify.sh
```

This brings `quarkus`, `python`, and the always-on `lgtm` service up with
`docker compose` (`lgtm`'s healthcheck gates both apps' `depends_on`), then
for **each** stack:

1. Waits for the WebSocket upgrade, opens one connection, reads the first
   frame, and schema-validates it against the contract-derived JSON Schema
   (the fixture's `RECEIVE` event, same as part3/part4).
2. **HARD**: polls `docker compose logs <service>` for the trace-id log
   line this connection produced, extracts the trace id, and asserts it's a
   32-hex-digit id.
3. **HARD**: scrapes the app's own metrics endpoint and asserts
   `handling_events_delivered_total` is present and its total is `> 0`.
4. **SOFT**: polls Tempo for that trace id; logs the outcome either way,
   never fails the build.

Prints `PASS` (exit `0`) once both stacks clear their HARD assertions,
regardless of how the SOFT Tempo poll came out.

### Ports

| Service | Host port | Purpose |
|---|---|---|
| `quarkus` | `8080` | WS upgrade + the `handlingEvents` channel + `GET /q/metrics` |
| `python` | `8081` | WS upgrade + the `handlingEvents` channel (native `websockets`) |
| `python` | `8082` | HTTP: `/healthz`, `/`, `/metrics` (FastAPI/uvicorn) |
| `lgtm` | `3000` | Grafana UI (anonymous admin) |
| `lgtm` | `4317` / `4318` | OTLP gRPC / HTTP ingest |
| `lgtm` | `3200` | Tempo query API; `verify.sh` polls `/api/traces/<id>` |
| `lgtm` | `9090` | Prometheus/Mimir query |
| `lgtm` | `3100` | Loki |

### Env knobs

| Env var | Stack | Default | Purpose |
|---|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | both | unset (SDK default `http://localhost:4317`); `compose.yaml` sets `http://lgtm:4317` | where spans/the OTLP exporter send |
| `OTEL_SERVICE_NAME` | Python | `part6-observability-python` (baked into the `Containerfile`) | `service.name` resource attribute + the `instance=` log field |
| `quarkus.otel.service.name` | Quarkus | `part6-observability-quarkus` (`application.properties`) | same, Quarkus side |

## Diagram

[`../../assets/diagrams/part6-observability-architecture.svg`](../../assets/diagrams/part6-observability-architecture.svg) /
`part6-observability-architecture.excalidraw` (generated with
[`scripts/diagrams/part6-observability-architecture.py`](../../scripts/diagrams/part6-observability-architecture.py)
via `scripts/generate_diagram.py`) show a WS client opening the channel
against each stack, Quarkus's auto-traced upgrade span plus its manual child
span vs. Python's single manual span (no auto-instrumentation available for
native `websockets`), both exporting OTLP to `lgtm`'s Collector → Tempo /
Mimir / Loki, and the trace-id-in-logs correlation that ties a line in
either app's own log output back to a specific trace.

## Generated artifacts

Same as part3/part4: `build/handling-event.schema.json` (extracted from
`contracts/asyncapi.yaml`) and each app's generated model
(`python/app/models_generated.py`) are build-time-only, gitignored, and
regenerated on every build, never committed. `verify.sh`'s own container
logs and the `lgtm` stack's internal state are likewise ephemeral:
`docker compose down -v` (run automatically on exit) removes them.
