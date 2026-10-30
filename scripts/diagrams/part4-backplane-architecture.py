#!/usr/bin/env python3
"""Part 4 "Production Concerns" backplane example: architecture diagram.
Two instances per stack share ONE backplane (Kafka topic or Redis channel);
an event injected through instance B's internal endpoint fans out to a
client connected to instance A (Ch18, DRQ-005). The inset at the bottom
shows the companion reconnect proof: stateless mode loses a gap-era event,
kafka mode replays it after reconnect. See
examples/part4-backplane/PROTOCOL.md."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 980, 600

nodes = [
    {"x": 40, "y": 15, "w": 280, "h": 70,
     "lines": ["client", "ws_connect_bg -> instance A"],
     "style": "user"},

    {"x": 660, "y": 15, "w": 280, "h": 70,
     "lines": ["verify.sh (test harness)", "POST inject -> instance B"],
     "style": "user"},

    {"x": 60, "y": 140, "w": 380, "h": 90,
     "lines": ["Instance A", "quarkus-a:8080 / python-a:8081",
               "own Kafka consumer group OR Redis subscribe"],
     "style": "accent"},

    {"x": 540, "y": 140, "w": 380, "h": 90,
     "lines": ["Instance B", "quarkus-b:8083 / python-b:8084",
               "publishes the injected event"],
     "style": "box"},

    {"x": 240, "y": 280, "w": 500, "h": 90,
     "lines": ["Backplane",
               "Kafka topic handling-events: durable, replay",
               "Redis channel handling-events:{bookingId} (live only, no replay)"],
     "style": "ink"},

    {"x": 140, "y": 420, "w": 700, "h": 110,
     "lines": ["Reconnect: GET .../handling-events?afterEventId=<last seen eventId>",
               "stateless: gap-era event LOST, no broker, no history",
               "kafka: gap-era event REPLAYED after reconnect, dedup by eventId, delivered once"],
     "style": "ghost"},
]

edges = [
    {"x1": 150, "y1": 85, "x2": 250, "y2": 140,
     "label": "connect; seed replay; live delivery (instance=A)", "bidir": True},
    {"x1": 800, "y1": 85, "x2": 730, "y2": 140,
     "label": "POST inject (bookingId, eventId)"},
    {"x1": 700, "y1": 230, "x2": 650, "y2": 280,
     "label": "publish"},
    {"x1": 330, "y1": 280, "x2": 260, "y2": 230,
     "label": "fan-out: kafka consumer group / redis pub-sub", "amber": True},
    {"x1": 190, "y1": 85, "x2": 190, "y2": 420,
     "label": "?afterEventId=<last seen>", "dashed": True},
]

notes = [
    {"x": 490, "y": 575, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Both stacks (Quarkus WebSockets Next, Python websockets+FastAPI) implement this identically: PROTOCOL.md is the single source of truth."},
]

generate_diagram.emit("part4-backplane-architecture", W, H, nodes=nodes, edges=edges, notes=notes)
