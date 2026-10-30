#!/usr/bin/env python3
"""Part 4 "Connection Concerns" example: architecture diagram. A client
opens the `handlingEvents` channel against EACH stack with a JWT on the
upgrade URL; both stacks gate the connection on that token BEFORE replaying
the shared fixture, then apply the SAME four connection concerns (auth,
error taxonomy, outbound backpressure, heartbeats) with the SAME close
codes. See examples/part4-connection/README.md."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 940, 560

nodes = [
    {"x": 350, "y": 15, "w": 240, "h": 65,
     "lines": ["client", "WS upgrade + ?token=<jwt>"],
     "style": "user"},

    {"x": 300, "y": 110, "w": 340, "h": 70,
     "lines": ["auth gate", "verify HS256 signature + exp, shared secret"],
     "style": "ink"},

    {"x": 40, "y": 220, "w": 400, "h": 150,
     "lines": ["Quarkus: WebSockets Next", "ws://localhost:8080/ws/v1/bookings/{id}/handling-events",
               "OutboundBackpressureGuard -> fixture replay",
               "onTextMessage/onBinaryMessage -> 4400", "auto-ping-interval 20s + idle-timeout 40s"],
     "style": "accent"},

    {"x": 500, "y": 220, "w": 400, "h": 150,
     "lines": ["Python: native websockets + FastAPI", "ws://localhost:8081/ws/v1/bookings/{id}/handling-events (+:8082)",
               "OutboundQueue -> fixture replay",
               "_receive_loop -> 4400", "ping_interval 20s + ping_timeout 20s"],
     "style": "box"},

    {"x": 60, "y": 410, "w": 360, "h": 60,
     "lines": ["reject: 1008 (auth)", "no data streamed, before replay starts"],
     "style": "ghost"},

    {"x": 520, "y": 410, "w": 360, "h": 60,
     "lines": ["reject: 4400 (error) / 4290 (backpressure)", "envelope + close (4400); close-only (4290)"],
     "style": "ghost"},

    {"x": 300, "y": 495, "w": 340, "h": 50,
     "lines": ["heartbeat: ping/pong keeps the connection alive;", "a silent peer is closed on idle-timeout"],
     "style": "sub"},
]

edges = [
    {"x1": 440, "y1": 80, "x2": 440, "y2": 110,
     "label": "upgrade", "lx": 10},
    {"x1": 390, "y1": 180, "x2": 240, "y2": 220,
     "label": "token valid", "amber": True},
    {"x1": 550, "y1": 180, "x2": 700, "y2": 220,
     "label": "token valid", "amber": True},
    {"x1": 240, "y1": 370, "x2": 240, "y2": 410,
     "label": "token invalid", "dashed": True},
    {"x1": 700, "y1": 370, "x2": 700, "y2": 410,
     "label": "bad frame / overrun", "dashed": True},
    {"x1": 240, "y1": 370, "x2": 700, "y2": 410,
     "dashed": True},
    {"x1": 700, "y1": 370, "x2": 240, "y2": 410,
     "dashed": True},
    {"x1": 440, "y1": 370, "x2": 440, "y2": 495,
     "label": "both stacks", "dashed": True, "bidir": True},
]

notes = [
    {"x": 470, "y": 545, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Same shared JWT secret, same close codes on both stacks: verify.sh asserts a client can't tell them apart."},
]

generate_diagram.emit("part4-connection-architecture", W, H, nodes=nodes, edges=edges, notes=notes)
