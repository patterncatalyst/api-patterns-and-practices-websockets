#!/usr/bin/env python3
"""Part 3 "Handling It" example: architecture diagram. A client opens the
`handlingEvents` channel against EACH stack on its own port; both stacks
read the same `contracts/asyncapi.yaml` and replay the same shared fixture
(`examples/part3-handling-events/fixtures/handling-events.json`) in order.
See examples/part3-handling-events/README.md."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 860, 420

nodes = [
    {"x": 330, "y": 15, "w": 200, "h": 65,
     "lines": ["client", "opens one WS per booking"],
     "style": "user"},

    {"x": 280, "y": 115, "w": 300, "h": 70,
     "lines": ["contracts/asyncapi.yaml", "channels.handlingEvents / HandlingEvent"],
     "style": "ink"},

    {"x": 50, "y": 240, "w": 320, "h": 120,
     "lines": ["Quarkus: WebSockets Next", "ws://localhost:8080/ws/v1/bookings/{id}/handling-events",
               "@OnOpen returns Multi<HandlingEvent>", "hand-kept to the contract schema"],
     "style": "accent"},

    {"x": 490, "y": 240, "w": 320, "h": 120,
     "lines": ["Python: native websockets + FastAPI", "ws://localhost:8081/ws/v1/bookings/{id}/handling-events",
               "(+:8082 /healthz)", "Pydantic model generated from the contract"],
     "style": "box"},

    {"x": 605, "y": 15, "w": 230, "h": 65,
     "lines": ["fixtures/handling-events.json", "RECEIVE, LOAD, CUSTOMS"],
     "style": "ghost"},
]

edges = [
    {"x1": 400, "y1": 80, "x2": 300, "y2": 115,
     "label": "WS upgrade", "lx": -40},
    {"x1": 460, "y1": 80, "x2": 560, "y2": 115,
     "label": "WS upgrade", "lx": 40},
    {"x1": 630, "y1": 48, "x2": 530, "y2": 48,
     "label": "both replay", "dashed": True},
    {"x1": 380, "y1": 185, "x2": 210, "y2": 240,
     "label": "generates/validates against", "amber": True},
    {"x1": 480, "y1": 185, "x2": 650, "y2": 240,
     "label": "generates/validates against", "amber": True},
    {"x1": 370, "y1": 300, "x2": 490, "y2": 300,
     "label": "same channel, same message shape, same fixture order", "dashed": True, "bidir": True},
]

notes = [
    {"x": 430, "y": 400, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Neither stack reads the other's source: both push the identical RECEIVE/LOAD/CUSTOMS sequence, verified by verify.sh."},
]

generate_diagram.emit("part3-architecture", W, H, nodes=nodes, edges=edges, notes=notes)
