#!/usr/bin/env python3
"""Fig 23.1/23.2: Ch23 (DRQ-028/DRQ-029): the two things this chapter's
`examples/part6-observability/` example demonstrates live. 23.2 shows the
signal flow for one connection: a manual span wrapping the fixture-replay
push, exported over OTLP to Tempo, with the delivery counter and the
trace-id log line BOTH staying local to the process rather than also
landing in Mimir/Loki (see app/ws_server.py's OTEL_METRICS_EXPORTER=none /
OTEL_LOGS_EXPORTER=none and HandlingEventObservabilityWebSocket's
Micrometer-direct-to-/q/metrics counter). 23.1 contrasts HOW that manual
span comes to exist on each stack: Quarkus adds a @WithSpan CHILD under an
already-auto-traced HTTP upgrade span, Python has no auto-instrumentation
for native `websockets` at all, so the whole span is hand-written with the
SDK tracer directly."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 23.1: auto vs. manual instrumentation, two different paths to the
# same span name
# ---------------------------------------------------------------------------
W1, H1 = 940, 480

nodes_1 = [
    {"x": 20, "y": 55, "w": 430, "h": 55,
     "lines": ["Quarkus", "quarkus-opentelemetry auto-traces the HTTP upgrade",
               "every request gets a span, zero code"],
     "style": "accent"},
    {"x": 490, "y": 55, "w": 430, "h": 55,
     "lines": ["Python", "native websockets: no opentelemetry-instrumentation-websockets",
               "package exists: no auto layer at all"],
     "style": "box"},

    {"x": 20, "y": 160, "w": 430, "h": 90,
     "lines": ["@WithSpan(\"ws.handling-events.connection\")",
               "on onOpen: adds a CHILD span over the",
               "returned Multi; span.end() deferred until",
               "the Multi completes"],
     "style": "ink"},
    {"x": 490, "y": 160, "w": 430, "h": 90,
     "lines": ["tracer.start_as_current_span(",
               "  \"ws.handling-events.connection\")",
               "the WHOLE span, hand-written with the",
               "SDK tracer directly; no parent to attach to"],
     "style": "ink"},

    {"x": 490, "y": 280, "w": 430, "h": 55,
     "lines": ["opentelemetry-instrument still configures the",
               "global TracerProvider + OTLP exporter: only the span itself is manual"],
     "style": "ghost"},

    {"x": 170, "y": 385, "w": 600, "h": 70,
     "lines": ["Same span name, same otel.trace_id=... log line shape, same OTLP export to Tempo",
               "a convention the two stacks keep by discipline, not by shared code"],
     "style": "kernel"},
]

edges_1 = [
    {"x1": 235, "y1": 110, "x2": 235, "y2": 160, "label": "parent -> child", "amber": True},
    {"x1": 705, "y1": 110, "x2": 705, "y2": 160, "dashed": True, "label": "no parent available"},
    {"x1": 705, "y1": 250, "x2": 705, "y2": 280, "dashed": True},
    {"x1": 235, "y1": 250, "x2": 350, "y2": 385, "amber": True},
    {"x1": 705, "y1": 335, "x2": 590, "y2": 385, "amber": True},
]

notes_1 = [
    {"x": 470, "y": 455 - 8, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "Quarkus narrows an existing gap; Python closes one that auto-instrumentation never reaches."},
]

generate_diagram.emit("23-auto-vs-manual", W1, H1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 23.2: one connection's signal flow: what gets pushed over OTLP
# and what stays local to the process
# ---------------------------------------------------------------------------
W2, H2 = 960, 620

nodes_2 = [
    {"x": 370, "y": 10, "w": 240, "h": 50,
     "lines": ["WS client", "opens handlingEvents channel"],
     "style": "user"},

    {"x": 290, "y": 95, "w": 400, "h": 55,
     "lines": ["HTTP upgrade span",
               "auto-traced where the framework instruments it (Quarkus);",
               "plain accept otherwise (Python)"],
     "style": "ink"},

    {"x": 270, "y": 185, "w": 440, "h": 60,
     "lines": ["manual span: ws.handling-events.connection",
               "wraps the whole fixture-replay push"],
     "style": "accent"},

    {"x": 20, "y": 300, "w": 400, "h": 70,
     "lines": ["per-event: HANDLING_EVENTS_DELIVERED_TOTAL.inc()",
               "Prometheus-format PULL scrape only",
               "never reaches Mimir in this example"],
     "style": "sub"},
    {"x": 540, "y": 300, "w": 400, "h": 70,
     "lines": ["otel.trace_id=... log line written to stdout",
               "read by docker compose logs",
               "never reaches Loki in this example"],
     "style": "sub"},

    {"x": 380, "y": 410, "w": 220, "h": 50,
     "lines": ["OTLP export (gRPC)", "to lgtm Collector"],
     "style": "ink"},

    {"x": 120, "y": 500, "w": 280, "h": 55,
     "lines": ["Tempo (traces,:3200)", "the only signal pushed here"],
     "style": "box"},
    {"x": 420, "y": 500, "w": 200, "h": 55,
     "lines": ["Mimir (:9090)", "not fed by this example"],
     "style": "ghost"},
    {"x": 640, "y": 500, "w": 200, "h": 55,
     "lines": ["Loki (:3100)", "not fed by this example"],
     "style": "ghost"},
]

edges_2 = [
    {"x1": 460, "y1": 60, "x2": 460, "y2": 95},
    {"x1": 460, "y1": 150, "x2": 460, "y2": 185},
    {"x1": 350, "y1": 245, "x2": 220, "y2": 300, "amber": True},
    {"x1": 570, "y1": 245, "x2": 740, "y2": 300, "amber": True},
    {"x1": 490, "y1": 245, "x2": 490, "y2": 410, "amber": True, "label": "OTLP"},
    {"x1": 460, "y1": 460, "x2": 260, "y2": 500, "amber": True},
    {"x1": 500, "y1": 460, "x2": 520, "y2": 500, "dashed": True},
    {"x1": 540, "y1": 460, "x2": 740, "y2": 500, "dashed": True},
    {"x1": 220, "y1": 370, "x2": 260, "y2": 500, "dashed": True, "label": "trace id is the correlating value"},
]

notes_2 = [
    {"x": 480, "y": 605, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Only the trace leaves the process over OTLP; the metric and the log line stay local, read or scraped directly."},
]

generate_diagram.emit("23-signal-flow", W2, H2, nodes=nodes_2, edges=edges_2, notes=notes_2)
