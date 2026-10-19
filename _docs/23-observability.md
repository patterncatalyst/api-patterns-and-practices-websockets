---
title: "Observability"
order: 23
part: "Testing, Debugging & Observability"
description: "Tracing a message end to end through the Grafana LGTM stack."
duration: "14 min read"
---

Every `verify.sh` since Part 3 has opened a connection, read a frame, and asserted its shape — proof that a channel is *correct*. None of it addresses what an engineer watching this channel in production sees once a connection has been open for an hour and something inside it goes quiet. Chapters 21 and 22 built the tools for finding out why a specific connection misbehaves once you already suspect it; this chapter is about the signal that tells you *which* connection to suspect in the first place, days after the fact, without a debugger attached. `examples/part6-observability/` is the first example in this book to turn OpenTelemetry on for real: every earlier part wired the SDK and left it inert — Quarkus shipped `quarkus.otel.sdk.disabled=true`, the Python entrypoint never ran under `opentelemetry-instrument`, and the `lgtm` compose service sat behind an unused `observability` profile nobody enabled by default. This chapter's `compose.yaml` drops all three of those guards. `lgtm` (`grafana/otel-lgtm:0.36.0`) is a hard dependency with no `profiles:` guard at all, both app services wait on its healthcheck before accepting a connection, and `verify.sh` proves the wiring live against both stacks, headless, every run — not read off a screenshot, not assumed from the library docs.

## Why a socket breaks the one-span-per-request assumption

Distributed tracing's default mental model comes from request/response: a span starts when a request arrives, ends when the response leaves, and everything that happened in between nests inside it. A REST call or a gRPC unary RPC fits that model with zero friction — the span's natural boundary is the call's own boundary. A WebSocket connection doesn't have one obvious boundary to pick. It opens once and, in a real deployment, can stay open for hours pushing an unbounded number of messages — tracing *the connection* as a single span would mean a span that never closes until a client disconnects, which defeats a trace's purpose as a bounded unit of work an operator can read start-to-finish. Tracing *each message* as its own span, parented to nothing, loses the fact that ten messages arrived over the same socket to the same client watching the same booking.

`examples/part6-observability` picks a middle point, and says so in its own code: `app/ws_server.py`'s module docstring calls out that "the fixture sequence is finite; a real feed would keep the loop open," and the span this example creates, `ws.handling-events.connection`, covers the whole fixture replay — the three-event push this channel's contract always sends on open — not a single frame and not an unbounded connection lifetime. That's a choice scoped to what this example does, not a universal rule: a channel that keeps pushing indefinitely would need to decide between covering the initial handshake-and-first-burst in one span (what this example does, scaled up) or wrapping periodic activity windows in separate spans linked back to a connection-level trace via span links rather than nesting. What doesn't change with that choice is the shape of the problem — a WebSocket needs an explicit decision about what a span's boundary even means, where an HTTP handler inherits that boundary from the one request it's handling.

## The upgrade gets traced automatically; the push over it does not

Quarkus's story starts one layer up from the WebSocket entirely. `quarkus-opentelemetry` auto-instruments the HTTP server — every request this process answers gets a span, and a WebSocket upgrade is, at the HTTP layer, a `GET` request with an `Upgrade` header that returns `101 Switching Protocols` instead of `200 OK`. That auto-traced upgrade span already exists by the time `HandlingEventObservabilityWebSocket#onOpen` runs — nothing in the example's own code asked for it. What auto-instrumentation does *not* cover is what happens after the upgrade completes: the fixture-replay push itself, the three `HandlingEvent`s streamed down the now-open socket. `@WithSpan(CONNECTION_SPAN_NAME)` on `onOpen` closes that gap with one annotation, adding a **child** span under the already-current upgrade span. The `opentelemetry-instrumentation-annotations` interceptor makes the new span current before the method body runs, and — because `onOpen` returns a `Multi<HandlingEvent>` rather than completing synchronously — defers `span.end()` until that `Multi` completes, so the span covers the full asynchronous push rather than the handful of microseconds `onOpen`'s own method body takes to build the `Multi` object and return it.

Python's story has no upper layer to inherit a span from. `opentelemetry-instrumentation-fastapi`, loaded by the `opentelemetry-instrument` wrapper that `examples/part6-observability/python/Containerfile`'s `ENTRYPOINT` runs under, auto-traces `app/http_app.py`'s FastAPI routes with zero code — but the WebSocket channel is served by the native `websockets` library on a separate port and a separate code path entirely, and there is no `opentelemetry-instrumentation-websockets` package in the OpenTelemetry ecosystem to patch it. A trace that only covered the FastAPI side would never show the WebSocket connection at all, even though that connection is the one thing this whole book is about. `app/ws_server.py` closes that gap by reaching for the OTel SDK tracer directly — `trace.get_tracer("part6-observability-python.ws_server")` — and wrapping the entire fixture replay in `tracer.start_as_current_span(CONNECTION_SPAN_NAME)` by hand. Nothing upstream configured this span for the module; it's the same primitive any manual instrumentation anywhere in the OpenTelemetry ecosystem reaches for. What *is* already configured is the `TracerProvider` and the OTLP exporter behind it — `opentelemetry-instrument` reads `OTEL_EXPORTER_OTLP_ENDPOINT`/`OTEL_SERVICE_NAME` and wires the global tracer before `app/main.py` ever imports `ws_server`, so `trace.get_tracer(__name__)` picks that configuration up with no setup code in this module. Only the span itself — where it starts, what it's named, when it ends — is hand-written.

{% include excalidraw.html file="23-auto-vs-manual" alt="Two columns under a shared heading reading same span name ws.handling-events.connection, same trace-id log line, two different paths to get there. Left column, Quarkus: an accent box reads quarkus-opentelemetry auto-instruments the HTTP upgrade, every request gets a span, zero code. An arrow labeled parent leads down to an ink box reading at WithSpan on onOpen adds a CHILD span over the returned Multi, one annotation, span.end deferred until the Multi completes. Right column, Python: a plain box reads native websockets library, no opentelemetry instrumentation websockets package exists, no parent span available. An arrow labeled no auto layer leads down to an accent box reading tracer.start_as_current_span ws.handling-events.connection, the WHOLE span hand-written with the SDK tracer directly, no parent. A dashed ghost box beneath the Python column notes opentelemetry-instrument still configures the global TracerProvider and OTLP exporter with no setup code here, only the span itself is manual. A shared kernel box spans the bottom reading both stacks export the identical span name to the same lgtm Collector and log the identical otel.trace_id correlation line." caption="Figure 23.1 — Quarkus adds a manual child span under an auto-traced HTTP upgrade; Python has no auto-traced layer at all, so the whole connection span is hand-written with the SDK tracer directly." %}

Here is the manual span creation on each stack, side by side — the one piece of tracing code either example writes:

{% include codetabs.html langs="Quarkus|Python" %}

```java
// examples/part6-observability/quarkus/.../observability/HandlingEventObservabilityWebSocket.java
@OnOpen
@WithSpan(CONNECTION_SPAN_NAME)   // "ws.handling-events.connection" — CHILD of the
                                  // auto-traced HTTP upgrade span quarkus-opentelemetry
                                  // already started for this request.
public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {
    String traceId = Span.current().getSpanContext().getTraceId();
    Log.infof("otel.trace_id=%s span=%s bookingId=%s instance=%s",
            traceId, CONNECTION_SPAN_NAME, bookingId, serviceName);

    return Multi.createFrom().iterable(feed.events())
            .invoke(event -> deliveredCounter.increment());
}
```
```python
# examples/part6-observability/python/app/ws_server.py
tracer = trace.get_tracer("part6-observability-python.ws_server")

async def _replay(websocket: ServerConnection, booking_id: str) -> None:
    with tracer.start_as_current_span(CONNECTION_SPAN_NAME) as span:
        # CONNECTION_SPAN_NAME = "ws.handling-events.connection" — the WHOLE
        # span, created by hand; native `websockets` has no auto-instrumentation
        # of its own, so there is no parent span to attach to here.
        span.set_attribute("bookingId", booking_id)
        _log_trace_id(span, booking_id)

        for event in sequence():
            frame = mapper.to_wire_frame(event)
            await websocket.send(frame)
            HANDLING_EVENTS_DELIVERED_TOTAL.inc()
            span.add_event("handling-event.delivered", {"eventType": event.eventType.value})
        await websocket.wait_closed()
```

Both implementations land on the identical span name, the identical structured log line shape, and the identical counter — a convention the two stacks keep by discipline, not by shared code, since neither language reads the other's source.

## What leaves the process, and what stays local

`compose.yaml`'s `environment: OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4317` is the only wire this example pushes bytes across unprompted: both stacks export spans over OTLP/gRPC to the `lgtm` service's bundled Collector, which forwards them into Tempo. That's the entire push path. Metrics and logs, despite living in the same OpenTelemetry vocabulary as traces, do not travel the same way in this example, and the distinction is worth stating directly rather than letting a reader assume every signal rides the same pipe. The Python `Containerfile` sets `OTEL_METRICS_EXPORTER=none` and `OTEL_LOGS_EXPORTER=none` explicitly — `opentelemetry-instrument` only ever ships traces out of this process. Quarkus never routes its counter through the OTel SDK's own metrics exporter at all: `HandlingEventObservabilityWebSocket`'s `deliveredCounter` is a plain Micrometer `Counter`, registered against the injected `MeterRegistry` and published at `/q/metrics` by `quarkus-micrometer-registry-prometheus` — a pull-based Prometheus endpoint, not a push.

That means `handling_events_delivered_total` never reaches Mimir in this example — nothing scrapes either app's metrics endpoint into the bundled stack's Prometheus/Mimir component, and `verify.sh`'s own comments are explicit that its metric assertion is "a synchronous Prometheus text-format scrape against the app itself, never against Mimir." A reader pointed at the `lgtm` stack's Grafana UI and expecting to graph this counter in an Explore panel backed by Mimir would come away thinking the metric doesn't exist; it exists, reachable with one `curl` straight to the app, not ingested anywhere else. The trace-id log line follows the same local pattern on the logging side: both stacks write it to the process's own stdout, which `docker compose logs <service>` reads directly — Loki ships inside the `grafana/otel-lgtm` image, but nothing in this example's topology feeds a log into it. There's no Promtail or OTel log exporter shipping either app's output anywhere; the log line's only destination is the container's own log stream.

None of that is a gap in the example so much as a complete picture of what "observability" costs to wire up end to end. Tracing got the full push-to-backend treatment here because it's the signal this chapter is built to demonstrate; metrics and logs are present, real, and useful, but stop at the process boundary rather than landing in Mimir or Loki. A team taking this example further toward a real deployment would add a Prometheus scrape config targeting both `/metrics` endpoints and a log-shipping agent (Promtail, the OTel Collector's own filelog receiver, Fluent Bit) pointed at each container's stdout — neither addition changes a line of the application code above, because both apps already emit the Prometheus-format text and the structured log line; only the *pipeline* carrying them onward is what this example leaves out.

{% include excalidraw.html file="23-signal-flow" alt="A WS client box at the top opens the handlingEvents channel. An arrow labeled HTTP upgrade leads down to a box reading HTTP upgrade span, auto-traced where the framework instruments it Quarkus, plain accept otherwise Python. A further arrow leads down to an accent box reading manual span ws.handling-events.connection, wraps the whole fixture-replay push. From that box, one amber arrow goes left to a sub box reading per-event HANDLING_EVENTS_DELIVERED_TOTAL.inc, Prometheus pull scrape only, never reaches Mimir in this example. A second amber arrow goes right to a sub box reading otel.trace_id=... log line written to container stdout, read by docker compose logs, never reaches Loki in this example. A third arrow goes straight down from the manual span box, labeled OTLP export grpc, to a box reading lgtm Collector, which fans out with a single solid arrow to Tempo traces port 3200 and two dashed ghost arrows to Mimir metrics port 9090 and Loki logs port 3100, both labeled not fed by this example. A dashed line connects the trace-id log box sideways to the Tempo box, captioned the trace id is the correlating VALUE, not a wired pipeline." caption="Figure 23.2 — only the trace gets pushed over OTLP to Tempo in this example; the metric and the log line both stay local to the process, pulled or read directly, and the trace id is what bridges them back to the trace a human or verify.sh can query." %}

## Correlating a log line to a trace by value, not by pipeline

Because the log line never travels through Loki, the mechanism that ties "a specific connection's log output" to "a specific trace in Tempo" is simpler than a wired logging pipeline and, for this example's purposes, more useful: both stacks print the trace id itself, in plain text, as part of the one log line each connection produces. The shape is identical on both stacks, down to the field order:

```
otel.trace_id={% raw %}<32-hex-trace-id>{% endraw %} span=ws.handling-events.connection bookingId={% raw %}<bookingId>{% endraw %} instance=part6-observability-{% raw %}<stack>{% endraw %}
```

Getting that hex string right took one formatting detail on the Python side that's easy to get subtly wrong. `SpanContext.trace_id` is a plain 128-bit Python `int`, not a pre-formatted string — `app/ws_server.py`'s `_log_trace_id` renders it with `format(span.get_span_context().trace_id, "032x")`, and the `032` matters: a bare `hex()` or an unpadded format call drops leading zero nibbles, so a trace id that happens to start with a zero byte would come out shorter than 32 characters — not only cosmetically wrong, but wrong in a way that breaks any downstream tool (Tempo's query API, a log-scraping script) expecting exactly 32 hex digits. Java never hits this problem because `Span.current().getSpanContext().getTraceId()` already returns the padded 32-character hex string directly — a difference in what each language's OTel API hands back, not a difference in the trace id's actual 128-bit value.

Either stack's line is enough on its own to answer the question this chapter opened with: given a connection a user reported trouble with, which trace in Tempo corresponds to it? Grep the app's own log output (or, as this example's `verify.sh` does, `docker compose logs <service>`) for the `bookingId` in question, read the `otel.trace_id=` value off the matching line, and that hex string is a direct key into Tempo's trace-lookup API — no shared request id, no correlation service, no second system that has to stay in sync with the first. The log line is cheap specifically because it duplicates a value the span already carries rather than inventing a new identifier.

## What to measure: connections are not events

`handling_events_delivered_total` counts individual `HandlingEvent` frames handed off to be sent — incremented once per frame inside the span, on both stacks, with no labels. It is **not** a count of connections, and conflating the two is an easy mistake for a dashboard to make: three connections that each receive the full three-event fixture produce a counter reading of nine, not three. For this example's deterministic fixture replay, that distinction barely matters because every connection pushes exactly three events; for a real feed where connections stay open indefinitely and events arrive at an unpredictable rate, the two numbers diverge completely — a spike in `handling_events_delivered_total` could mean more connections opened, or the same handful of connections suddenly receiving a burst of events, and only a labeled metric (by `bookingId`, by instance) or a cross-reference against the trace volume could tell those apart. This example keeps the metric unlabeled on purpose, matching Chapter 20's instinct that a metric answering "in aggregate, how much happened" should stay cheap to keep and graph over long windows, not carry per-connection cardinality that belongs in a trace instead. A production deployment of this channel would likely want a second metric — open connection count, a gauge incremented in `onOpen` and decremented on close — specifically because "how many sockets are open right now" and "how many events have gone out in total" answer two different operational questions neither number can answer for the other.

What the counter does prove, synchronously and without touching Tempo at all, is that the delivery path ran to completion: `verify.sh`'s `assert_metric_present` scrapes each app's own metrics endpoint (`/q/metrics` on Quarkus, `:8082/metrics` on Python) and sums every sample line matching the counter's name, asserting the total is greater than zero. That assertion catches a class of bug a trace alone would not surface as cleanly — a connection that opens, upgrades, and even gets a trace recorded for it, but never sends a frame because the send loop raised before reaching `websocket.send`, would still show a span in Tempo while the delivery counter stayed at zero.

## Verifying the wiring without faking a flaky gate

Proving a trace id shows up in a log line is deterministic the instant the connection closes — the line is already in the container's own stdout. Proving that same trace is *queryable in Tempo* within some bounded time is a different kind of claim: it depends on the app's OTLP batch-export interval, the Collector picking the span up, and Tempo finishing ingestion — three separate processes a cold `docker compose up --build` has freshly started together. `verify.sh` splits its assertions along exactly that line, and the split has a name — DRQ-028's HARD/SOFT convention, the same one the gRPC sibling site uses for its own observability chapter.

**HARD** — fails the build the instant it's wrong — covers two checks, both synchronous and local to the app under test: `wait_for_trace_id_log` polls `docker compose logs <service>` (bounded, fifteen attempts at one-second intervals) for the exact log line pattern above, extracts the 32-hex-digit trace id with a `sed` capture, and fails outright if the pattern never appears or the captured string isn't valid hex of the right length. `assert_metric_present` then scrapes the app's own metrics endpoint directly and fails if the counter is missing or sums to zero. Both checks ask a question the app itself can answer without depending on anything downstream — a flaky collector, a slow Tempo ingest, a container that needed an extra second to flush its log buffer, none of that can make either check fail for reasons unrelated to whether the span and the counter did their job.

**SOFT** — warns, never fails — is `check_tempo_trace`: a bounded poll (ten attempts, three seconds apart, thirty seconds total) of Tempo's query API, `http://localhost:3200/api/traces/<trace-id>`, checking the response body contains a span literally named `ws.handling-events.connection`. A timeout here logs a `WARN` and `verify.sh` still exits `0` — the function's own comment states the reasoning directly: proving a specific trace id is queryable in Tempo within N seconds depends on a cold, multi-process ingestion pipeline, and "isn't a fair thing to gate a merge on." That's not giving up on verifying the full pipeline works; it's refusing to let a pipeline's normal cold-start ingest lag — which has nothing to do with whether this example's instrumentation code is correct — turn into an intermittent CI failure a team would eventually learn to ignore or silence outright. The SOFT check still runs, still reports its outcome, and still gets read by anyone debugging a real ingestion problem; it only loses the authority to block a merge over something outside this example's own control.

## On the wire

A connection's own log output, grepped directly from the running container — identical shape on both stacks:

```
$ docker compose logs quarkus | grep 'span=ws.handling-events.connection'
part6-observability-quarkus  | otel.trace_id={% raw %}4bf92f3577b34da6a3ce929d0e0e4736{% endraw %} span=ws.handling-events.connection bookingId={% raw %}bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A{% endraw %} instance=part6-observability-quarkus

$ docker compose logs python | grep 'span=ws.handling-events.connection'
part6-observability-python   | otel.trace_id={% raw %}9c2a1e0f6b3d4c5a8e7f1a2b3c4d5e6f{% endraw %} span=ws.handling-events.connection bookingId={% raw %}bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A{% endraw %} instance=part6-observability-python
```

The counter, scraped straight off each app's own endpoint — the exact HARD assertion `verify.sh` makes, no Mimir in the path:

```
$ curl -s http://localhost:8080/q/metrics | grep handling_events_delivered_total
handling_events_delivered_total 3.0

$ curl -s http://localhost:8082/metrics | grep handling_events_delivered_total
handling_events_delivered_total 3.0
```

And the trace id from the first block, handed straight to Tempo's query API — the SOFT check, the one a reader runs by hand after `verify.sh` has already reported its outcome:

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

The same trace id, read three independent ways — a log line, a metric scrape, and Tempo's own stored span — is a stronger claim than any one of them alone, and it's the exact sequence `examples/part6-observability/verify.sh` runs against both stacks, every time, before it prints `PASS`.

## Where this goes next

This chapter turned the lights on: a manual span bridging the gap auto-instrumentation leaves on a native WebSocket library, a trace exported to a real backend, a metric and a log line that both stay local by design, and a verification split that gates on what's deterministic while still reporting on what isn't. Chapter 24 turns around and asks the opposite question — not what correct observability looks like, but which of the shortcuts this book has avoided on purpose (logging a payload instead of tracing it, a span that never ends because a connection never closes, a metric with unbounded per-connection cardinality) are the anti-patterns a team reaches for under deadline pressure, and why each one costs more than it saves the first time an on-call engineer needs the signal it was supposed to provide.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Give a long-lived connection an explicit span boundary instead of inheriting request/response's one-span-per-call default — this example scopes <code>ws.handling-events.connection</code> to the whole fixture-replay push, a choice made for what this channel does, not a universal rule for every socket. Let auto-instrumentation cover whatever it already reaches (Quarkus's HTTP-upgrade span, FastAPI's HTTP routes) and reserve manual spans for the gap it leaves — here, the entire WebSocket push on Python, where no <code>opentelemetry-instrumentation-websockets</code> package exists, and a child span on Quarkus, where the gap is narrower because the upgrade itself is already traced. Know which signals leave the process at all: this example pushes traces over OTLP to Tempo, but both stacks' metrics stay a local Prometheus-format pull scrape and both stacks' trace-id log line stays on local stdout — neither reaches Mimir or Loki here, and a team extending this example toward production needs to add that plumbing explicitly rather than assume the bundled LGTM image wires it up on its own. Correlate a log line to a trace by printing the trace id itself in the log line — a value match needs no shared infrastructure to stay in sync. And verify observability the way <code>verify.sh</code> does: gate a build on what's deterministic and local (the trace id in the app's own log, the counter on the app's own metrics endpoint) and let a cold multi-process ingestion pipeline's lag show up as a non-fatal warning, not a flaky failure.</p></div>
