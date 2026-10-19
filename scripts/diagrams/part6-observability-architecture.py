#!/usr/bin/env python3
"""Part 6 "Observability" example — architecture diagram. A WS client opens
the `handlingEvents` channel against EACH stack; Quarkus auto-traces the
HTTP upgrade and adds a manual CHILD span for the fixture-replay push,
Python has no auto-instrumentation for native `websockets` so its connection
span is entirely manual. Both export OTLP to the `lgtm` compose service
(Collector -> Tempo/Mimir/Loki) and log the SAME trace-id-correlation line
shape, which is how a reader (and verify.sh) ties a log line back to a
specific trace. See examples/part6-observability/README.md."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 980, 620

nodes = [
    {"x": 370, "y": 15, "w": 240, "h": 55,
     "lines": ["WS client", "opens handlingEvents channel"],
     "style": "user"},

    {"x": 40, "y": 110, "w": 420, "h": 165,
     "lines": ["Quarkus — WebSockets Next (:8080)",
               "quarkus-opentelemetry auto-traces the HTTP upgrade",
               "@WithSpan onOpen -> CHILD span ws.handling-events.connection",
               "Log.infof otel.trace_id=... instance=part6-observability-quarkus",
               "Micrometer Counter handling_events_delivered_total -> /q/metrics"],
     "style": "accent"},

    {"x": 500, "y": 110, "w": 440, "h": 165,
     "lines": ["Python — native websockets + FastAPI (:8081 / :8082)",
               "NO opentelemetry-instrumentation-websockets exists",
               "tracer.start_as_current_span(ws.handling-events.connection) — MANUAL",
               "logger.info otel.trace_id=... instance=part6-observability-python",
               "prometheus_client Counter handling_events_delivered_total -> :8082/metrics"],
     "style": "box"},

    {"x": 300, "y": 320, "w": 360, "h": 55,
     "lines": ["OTLP export (gRPC)", "OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4317"],
     "style": "ink"},

    {"x": 170, "y": 420, "w": 620, "h": 110,
     "lines": ["lgtm (grafana/otel-lgtm:0.36.0) — HARD dependency, no profiles: guard",
               "OTel Collector -> Tempo (traces, :3200 query) / Mimir (metrics, :9090) / Loki (logs, :3100)",
               "Grafana UI :3000 (anonymous admin)"],
     "style": "kernel"},

    {"x": 40, "y": 565, "w": 420, "h": 40,
     "lines": ["HARD: trace id in the app's OWN log line", "+ app's OWN metric scrape > 0"],
     "style": "sub"},

    {"x": 500, "y": 565, "w": 440, "h": 40,
     "lines": ["SOFT: Tempo /api/traces/<id> eventually", "shows span ws.handling-events.connection"],
     "style": "ghost"},
]

edges = [
    {"x1": 440, "y1": 70, "x2": 250, "y2": 110,
     "label": "upgrade", "lx": -30},
    {"x1": 540, "y1": 70, "x2": 720, "y2": 110,
     "label": "upgrade", "lx": 30},
    {"x1": 250, "y1": 275, "x2": 440, "y2": 320,
     "amber": True},
    {"x1": 720, "y1": 275, "x2": 540, "y2": 320,
     "amber": True},
    {"x1": 480, "y1": 375, "x2": 480, "y2": 420,
     "label": "OTLP", "amber": True},
    {"x1": 300, "y1": 530, "x2": 260, "y2": 565,
     "dashed": True},
    {"x1": 660, "y1": 530, "x2": 700, "y2": 565,
     "dashed": True},
]

notes = [
    {"x": 490, "y": 605, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Same trace-id-in-logs shape on both stacks correlates a log line to the trace Tempo eventually ingests."},
]

generate_diagram.emit("part6-observability-architecture", W, H, nodes=nodes, edges=edges, notes=notes)
