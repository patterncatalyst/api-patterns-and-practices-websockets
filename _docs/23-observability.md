---
title: "Observability"
order: 23
part: "Testing, Debugging & Observability"
description: "Tracing a message end to end through the Grafana LGTM stack."
duration: "10 min read"
---

## Learning objectives

By the end of this chapter you can:

- Decide where to scope a span's boundary on a long-lived WebSocket connection instead of inheriting request/response's one-span-per-call default.
- Add a manual span (`@WithSpan`, `tracer.start_as_current_span`) to bridge the gap auto-instrumentation leaves on a native WebSocket library.
- State which signals leave the process: both stacks export spans over OTLP to Tempo, while metrics stay a local Prometheus-format scrape and logs stay on container stdout.
- Correlate a log line to a Tempo trace by printing the trace id itself (`otel.trace_id=...`), with no shared pipeline required.
- Split an observability check into HARD (deterministic, local) and SOFT (depends on cold-start ingestion) assertions.

## Why this matters

A correct channel is not an observable one. Once a connection has been open for an hour and something inside it goes quiet, the engineer on call needs a signal that says which connection to suspect, days after the fact, with no debugger attached. That signal is a trace, a metric and a log line that agree on which connection they describe.

`examples/part6-observability/` runs OpenTelemetry live. Earlier parts wired the SDK and left it inert: Quarkus shipped `quarkus.otel.sdk.disabled=true`, the Python entrypoint never ran under `opentelemetry-instrument`, and the `lgtm` compose service sat behind an unused `observability` profile. Here all three guards are gone. `lgtm` (`grafana/otel-lgtm`, Grafana plus Tempo, Mimir, Loki and a Collector in one image) is a hard dependency with no `profiles:` entry, and both app services wait on its healthcheck before accepting a connection.

## Where a span starts and ends

Tracing's default model comes from request/response: a span starts when a request arrives, ends when the response leaves, and everything in between nests inside it. A WebSocket has no such boundary. One connection can stay open for hours and carry an unbounded number of messages. A span for the whole connection never closes until the client leaves, which defeats a trace as a bounded unit of work. A parentless span per message hides that ten messages arrived over the same socket for the same booking.

A workable middle point: the span `ws.handling-events.connection` covers the whole fixture replay, the three-event push the channel sends on open: not one frame, not the connection's lifetime. A channel that pushes indefinitely has to choose between the same scoping scaled up (the handshake and first burst in one span) and separate spans per activity window, linked back to a connection-level trace with span links instead of nesting. Either way, the boundary is a decision you make, where an HTTP handler inherits it.

## Auto-instrumentation covers the upgrade, not the push

`quarkus-opentelemetry` auto-instruments the HTTP server, and a WebSocket upgrade is an HTTP `GET` with an `Upgrade` header that answers `101 Switching Protocols`. That upgrade span exists before `onOpen` runs. What it does not cover is the push after the upgrade. `@WithSpan` on `onOpen` adds a child span under the upgrade span. Because `onOpen` returns a `Multi`, the interceptor defers `span.end()` until the `Multi` completes, so the span covers the whole asynchronous push and not the microseconds spent building the `Multi`.

Python has no upper layer to inherit from. `opentelemetry-instrument` auto-traces the FastAPI routes, but the WebSocket channel is served by the native `websockets` library on a separate port, and no `opentelemetry-instrumentation-websockets` package exists. A trace of the FastAPI side alone would never show the connection. The server takes the SDK tracer directly and wraps the replay in `tracer.start_as_current_span`. The `TracerProvider` and OTLP exporter are already configured by `opentelemetry-instrument` from `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME`, so only the span itself is hand-written.

{% include excalidraw.html file="23-auto-vs-manual" alt="Two columns. Quarkus: an auto-traced HTTP upgrade span is the parent, and @WithSpan on onOpen adds a child span that ends when the returned Multi completes. Python: the native websockets library has no auto-instrumentation, so the whole connection span is written by hand with the SDK tracer. Both stacks export the same span name to the same Collector and log the same trace id line." caption="Figure 23.1: Quarkus adds a manual child span under an auto-traced HTTP upgrade; Python has no auto-traced layer, so the whole connection span is hand-written with the SDK tracer." %}

{% include codetabs.html langs="Quarkus|Python" %}

```java
    @OnOpen
    @WithSpan(CONNECTION_SPAN_NAME)
    public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {
        String traceId = Span.current().getSpanContext().getTraceId();
        Log.infof("otel.trace_id=%s span=%s bookingId=%s instance=%s",
                traceId, CONNECTION_SPAN_NAME, bookingId, serviceName);

        return Multi.createFrom().iterable(feed.events())
                .invoke(event -> deliveredCounter.increment());
    }
```
```python
async def _replay(websocket: ServerConnection, booking_id: str) -> None:
    with tracer.start_as_current_span(CONNECTION_SPAN_NAME) as span:
        span.set_attribute("bookingId", booking_id)
        span.set_attribute("service.instance", INSTANCE_NAME)
        _log_trace_id(span, booking_id)

        try:
            for event in sequence():
                frame = mapper.to_wire_frame(event)
                await websocket.send(frame)
                HANDLING_EVENTS_DELIVERED_TOTAL.inc()
                span.add_event("handling-event.delivered", {"eventType": event.eventType.value})
            # The fixture sequence is finite; a real feed would keep the
            # loop open and `send` as new handling events are recorded.
            # Here we just hold the connection open so the channel's
            # long-lived-per-booking semantics still hold, until the client
            # disconnects, matching examples/part3-handling-events.
            await websocket.wait_closed()
        except ConnectionClosed:
            span.set_attribute("ws.disconnect_reason", "client_disconnected")
            raise
```

Both stacks use the same span name, the same log line shape and the same counter. The two implementations keep that convention by discipline, not shared code.

## What leaves the process

| Signal | Path | Where it ends |
|---|---|---|
| Traces | OTLP/gRPC to `http://lgtm:4317` (`OTEL_EXPORTER_OTLP_ENDPOINT`), from both stacks | Tempo, via the bundled Collector |
| Metrics | Local scrape: `/q/metrics` on Quarkus (Micrometer `Counter`), `:8082/metrics` on Python | The app's own endpoint, never Mimir |
| Logs | Container stdout, read with `docker compose logs <service>` | The container's log stream, never Loki |

Not every signal rides one pipe. The Python `Containerfile` sets `OTEL_METRICS_EXPORTER=none` and `OTEL_LOGS_EXPORTER=none`, so `opentelemetry-instrument` ships only traces. Quarkus registers its counter against the injected `MeterRegistry` and publishes it through `quarkus-micrometer-registry-prometheus`, a pull endpoint. Nothing scrapes either endpoint into Mimir, and nothing ships either app's stdout to Loki, so `handling_events_delivered_total` is reachable with one `curl` and invisible in Grafana's Explore panel.

Taking this toward production adds a Prometheus scrape config for both metrics endpoints and a log shipper (Promtail, the Collector's `filelog` receiver, Fluent Bit) pointed at each container's stdout. Neither changes a line of application code, because both apps already emit Prometheus text and the structured log line.

{% include excalidraw.html file="23-signal-flow" alt="A WebSocket client opens the handlingEvents channel. The HTTP upgrade leads to a manual span, ws.handling-events.connection, which wraps the fixture replay. From it the delivered counter and the trace id log line stay local to the process, while the span goes over OTLP gRPC to the lgtm Collector and on to Tempo. Dashed arrows to Mimir and Loki are marked not fed." caption="Figure 23.2: only the trace is pushed over OTLP to Tempo; the metric and the log line stay local, and the trace id in the log line links them back to the trace." %}

## Correlating a log line to a trace by value

The log line never travels through Loki, so correlation is by value. Both stacks print the trace id in plain text, in one line per connection, in the same field order:

```
otel.trace_id={% raw %}<32-hex-trace-id>{% endraw %} span=ws.handling-events.connection bookingId={% raw %}<bookingId>{% endraw %} instance=part6-observability-{% raw %}<stack>{% endraw %}
```

Given a connection a user reported, grep the app's log for the `bookingId`, read `otel.trace_id=` off the line, and use that hex string as the key into Tempo's trace-lookup API. No shared request id, correlation service or second system has to stay in sync, because the line duplicates a value the span already carries.

One Python detail matters. `SpanContext.trace_id` is a 128-bit `int`, not a string, so the server renders it with `format(trace_id, "032x")`. A bare `hex()` or an unpadded format drops leading zero nibbles, and a trace id that starts with a zero byte comes out shorter than 32 characters, which breaks Tempo's query API and any log scraper expecting exactly 32 digits. Java's `getTraceId()` already returns the padded string.

## What to measure

`handling_events_delivered_total` counts `HandlingEvent` frames, once per frame inside the span, on both stacks, with no labels. It is not a count of connections: three connections that each receive the three-event fixture read nine, not three. With a fixed fixture the difference is invisible. With a live feed the two numbers diverge: a spike could mean more connections opened or the same few connections receiving a burst, and only a labeled metric or the trace volume tells them apart.

The metric stays unlabeled. An aggregate "how much happened" counter should stay cheap to keep over long windows, and per-connection cardinality belongs in a trace. A production channel also wants a gauge of open connections, incremented in `onOpen` and decremented on close, because "how many sockets are open now" and "how many events went out in total" are different operational questions.

The counter also proves the delivery path ran: a connection that upgrades and records a span but never sends, because the send loop raised before `websocket.send`, shows a span in Tempo and a counter stuck at zero.

## HARD and SOFT assertions

Proving a trace id appears in a log line is deterministic the moment the connection closes. Proving the same trace is queryable in Tempo within a bounded window depends on the OTLP batch-export interval, the Collector and Tempo's ingestion, three processes a cold `docker compose up --build` has just started together. Gating a merge on that makes CI flaky, and a team learns to ignore or silence a flaky gate.

The rule: **fail the build on what the app can answer locally, and only warn on what depends on a cold multi-process pipeline.**

Both stacks run the same two tiers:

| Tier | Check | Outcome |
|---|---|---|
| HARD | The trace id appears in the app's own `docker compose logs <service>` output: up to 15 polls, one second apart, then a `sed` capture that must yield 32 hex digits | Fails the build |
| HARD | The app's own metrics endpoint shows `handling_events_delivered_total` summing above zero | Fails the build |
| SOFT | `http://localhost:3200/api/traces/<trace-id>` returns a span named `ws.handling-events.connection`: up to 10 polls, three seconds apart | Logs a `WARN` on timeout and still exits `0` |

Neither HARD check can fail because of a slow collector, a slow Tempo ingest or a log buffer that needed another second to flush. The SOFT check still runs and reports, and it is the one to read when debugging a real ingestion problem. It only loses the authority to block a merge.

## On the wire

A connection's log line, grepped from each running container:

```
$ docker compose logs quarkus | grep 'span=ws.handling-events.connection'
part6-observability-quarkus  | otel.trace_id={% raw %}4bf92f3577b34da6a3ce929d0e0e4736{% endraw %} span=ws.handling-events.connection bookingId={% raw %}bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A{% endraw %} instance=part6-observability-quarkus

$ docker compose logs python | grep 'span=ws.handling-events.connection'
part6-observability-python   | otel.trace_id={% raw %}9c2a1e0f6b3d4c5a8e7f1a2b3c4d5e6f{% endraw %} span=ws.handling-events.connection bookingId={% raw %}bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A{% endraw %} instance=part6-observability-python
```

The counter, scraped from each app's own endpoint:

```
$ curl -s http://localhost:8080/q/metrics | grep handling_events_delivered_total
handling_events_delivered_total 3.0

$ curl -s http://localhost:8082/metrics | grep handling_events_delivered_total
handling_events_delivered_total 3.0
```

The trace id from the first block, handed to Tempo's query API:

```
$ curl -s "http://localhost:3200/api/traces/4bf92f3577b34da6a3ce929d0e0e4736" | python3 -m json.tool
```
```json
{
  "batches": [
    {
      "resource": { "attributes": [{"key": "service.name", "value": {"stringValue": "part6-observability-quarkus"}}] },
      "scopeSpans": [
        { "spans": [ { "name": "ws.handling-events.connection", "traceId": "4bf92f3577b34da6a3ce929d0e0e4736" } ] }
      ]
    }
  ]
}
```

> **Decision**
>
> Give a long-lived connection an explicit span boundary instead of inheriting one span per call. Let auto-instrumentation cover what it reaches (the HTTP upgrade, FastAPI routes) and write manual spans only for the gap: the whole push on Python, a child span on Quarkus. Know which signals leave the process before you trust a dashboard. Correlate logs to traces by printing the trace id. Gate a build on what the app can answer locally, and let cold-start ingestion lag warn.

> **🤖 Explore with your agent**
>
> "In examples/part6-observability, list which of traces, metrics and logs reach the lgtm service for the Quarkus app (port 8080) and the Python app (ports 8081 and 8082), citing compose.yaml and the Containerfile OTEL_*_EXPORTER settings. Then add an open-connections gauge to both apps, incremented when a handlingEvents connection opens and decremented on close, and leave handling_events_delivered_total unlabeled."
>
> Check: `curl -s http://localhost:8080/q/metrics | grep -i open` and `curl -s http://localhost:8082/metrics | grep -i open` show the gauge, and `./verify.sh` still prints PASS.

## Build, run, observe

```bash
cd examples/part6-observability && ./verify.sh
```

The script starts both stacks next to the LGTM stack, opens a connection to each, and checks that the app's own log line carries the connection's trace id and its own metrics endpoint shows the counter above zero. It then polls Tempo for the span as a non-fatal check and prints `PASS: ` once both stacks hold the HARD assertions. Ports: Quarkus on `8080`, Python on `8081` with metrics on `8082`, Grafana on `3000`, Tempo on `3200`. `examples/part6-observability/README.md` has the full output.

To read one connection by hand, run the grep and `curl` commands above in that order: log line, counter, then Tempo.

## For deeper coverage

- Charity Majors, Liz Fong-Jones & George Miranda, *Observability Engineering* (O'Reilly, 2022): the three-pillars model, applied unevenly here by pushing only traces to Tempo.
- Betsy Beyer, Chris Jones, Jennifer Petoff, Niall Richard Murphy, Charity Majors, Liz Fong-Jones & George Miranda (eds.), *Site Reliability Engineering*, 2nd ed. (O'Reilly, 2026): the operational case for separating deterministic checks from ones that depend on a pipeline.
- *Cloud Native Design Patterns*, "Observability" chapter: span boundaries, correlation identifiers, and the pull-versus-push distinction.
- [OpenTelemetry documentation](https://opentelemetry.io/docs/): the SDK, auto-instrumentation, and manual span APIs (`@WithSpan`, `start_as_current_span`).
- [W3C Trace Context](https://www.w3.org/TR/trace-context/): the trace id format rendered as 32 hex digits in the log line.
