# Part 6 "Observability" — Quarkus (WebSockets Next)

Forked from [`examples/part3-handling-events/quarkus`](../../part3-handling-events/quarkus):
the same `handlingEvents` channel
(`operations.receiveHandlingEvent`, [`contracts/asyncapi.yaml`](../../../contracts/asyncapi.yaml)) —
one WebSocket connection per booking, replaying the shared fixture on open —
now instrumented with **live** OpenTelemetry traces and Micrometer/Prometheus
metrics (DRQ-028/DRQ-029), instead of part4's connection-hardening concerns.
The Python/`websockets`-library sibling app ([`../python`](../python))
implements the identical observability behavior against the same contract;
`verify.sh` asserts both uniformly.

- **Endpoint:** `ws://localhost:8080/ws/v1/bookings/{bookingId}/handling-events`
- **Model:** `HandlingEvent` / `HandlingEventType` in
  `src/main/java/.../handlingevents/` are byte-for-byte copies of
  part3/part4's — this part is about observability, not new message content.
- **Metrics port:** 8080 (same port as the WebSocket — `/q/metrics`).

## The fixture is not duplicated here

[`../../part3-handling-events/fixtures/handling-events.json`](../../part3-handling-events/fixtures/handling-events.json)
is the single source of truth (the Python sibling reads the identical
file). `pom.xml`'s `copy-handling-events-fixture` execution copies it onto
the classpath (`/fixtures/handling-events.json`) at build time via a path
relative to this module's basedir (`../../part3-handling-events/fixtures` —
two levels up, since part3's and part6's `quarkus/` modules are siblings
under `examples/`) — no manual copy step for a local build. `Containerfile`
reproduces the same relative layout inside the build stage so the identical
`pom.xml` reference resolves there too.

## Shared OpenTelemetry conventions (DRQ-028/DRQ-029)

Identical on the Python sibling — `verify.sh` greps/asserts both uniformly:

- **OTLP export** — `quarkus.otel.sdk.disabled=false` (unlike part3/part4,
  where it's wired but inert); `quarkus.otel.exporter.otlp.endpoint` honors
  `OTEL_EXPORTER_OTLP_ENDPOINT` (compose sets `http://lgtm:4317`, gRPC).
  `quarkus.otel.service.name=part6-observability-quarkus`.
- **Connection span** — `quarkus-opentelemetry` auto-traces the HTTP upgrade
  itself; `HandlingEventObservabilityWebSocket#onOpen` additionally wraps the
  fixture-replay push in a manual child span, `ws.handling-events.connection`,
  via `@WithSpan` (works with the method's `Multi<HandlingEvent>` return
  type — the interceptor defers `span.end()` until the `Multi` completes, so
  the span covers the whole push, not just the method's synchronous entry).
- **Trace-id log line** — exactly one structured line per connection, in the
  shape `verify.sh` greps for on both stacks:

  ```
  otel.trace_id=<32-hex-trace-id> span=ws.handling-events.connection bookingId=<bookingId> instance=part6-observability-quarkus
  ```

  Read via `Span.current().getSpanContext().getTraceId()` — valid
  synchronously at the top of `onOpen`, since the `@WithSpan` interceptor has
  already made the span current before invoking the method body.
- **Metrics (DRQ-029)** — `quarkus-micrometer-registry-prometheus` publishes
  `/q/metrics` (default path, no extra config). `handling_events_delivered_total`
  (a `Counter`, registered in `HandlingEventObservabilityWebSocket#init`)
  increments once per `HandlingEvent` as it is emitted from the fixture
  `Multi` — i.e. once per event actually handed to WebSockets Next to
  serialize and send, not once per connection.

**Not in scope here:** a full trace landing in Tempo. This module proves the
span exists (trace id in its own logs) and the counter increments — the
combined `verify.sh` (with the `lgtm` compose service up) polls Tempo
separately as a SOFT check, per DRQ-028's HARD/SOFT split.

## Running it

```shell
./mvnw quarkus:dev
```

Dev UI: <http://localhost:8080/q/dev/>.

## Running the conformance test

Identical to part3/part4's test (forked verbatim — this part reuses the same
fixture and model, so the same invariants hold) — regenerate the
contract-derived schema first:

```shell
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./mvnw -q test
```

## Packaging

```shell
./mvnw package
java -jar target/quarkus-app/quarkus-run.jar
```

Or build the container image from the **repo root** (the build context
needs to reach `examples/part3-handling-events/fixtures/`):

```shell
docker build -f examples/part6-observability/quarkus/Containerfile \
  -t part6-observability-quarkus .
docker run --rm -p 8080:8080 part6-observability-quarkus
```

## Self-verify

With the OTel SDK enabled but no collector reachable (`OTEL_EXPORTER_OTLP_ENDPOINT`
unset or pointed somewhere harmless), the exporter is inert but the SDK
still creates and logs spans — enough to prove the span/log-line/counter
wiring without the `lgtm` compose service:

```shell
./mvnw -q package -DskipTests
java -jar target/quarkus-app/quarkus-run.jar &
APP_PID=$!

source ../../_lib/lib.sh
ensure_websocat
CHANNEL="/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
wait_for_ws localhost:8080 "$CHANNEL"

# (a) first frame is the fixture's RECEIVE event
ws_first_frame "ws://localhost:8080$CHANNEL"

# (b) trace-id log line — check the app's stdout/log for:
#   otel.trace_id=<hex> span=ws.handling-events.connection bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A instance=part6-observability-quarkus

# (c) delivery counter > 0
curl -s localhost:8080/q/metrics | grep handling_events_delivered_total

kill $APP_PID
```

Full trace -> Tempo ingestion is proven later by the combined `verify.sh`
with the `lgtm` compose service up (DRQ-028's SOFT Tempo poll).

## Related guides

- [WebSockets Next](https://quarkus.io/guides/websockets-next-reference) —
  Implementation of the WebSocket API with enhanced efficiency and usability.
- [OpenTelemetry](https://quarkus.io/guides/opentelemetry) — Use
  OpenTelemetry to trace services.
- [Micrometer metrics](https://quarkus.io/guides/micrometer) — Instrument
  the runtime and application with dimensional metrics.
