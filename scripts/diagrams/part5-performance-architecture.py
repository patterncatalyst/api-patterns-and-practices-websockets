#!/usr/bin/env python3
"""Part 5 "Performance" example: architecture diagram. One `HandlingEvent`
negotiates a wire encoding via `Sec-WebSocket-Protocol` (DRQ-026): a client
offering `+json` gets a JSON TEXT frame (opcode 0x1); a client offering
`+protobuf` gets a Protobuf BINARY frame (opcode 0x2). Both encodings decode
to the SAME field values: only the bytes on the wire differ, and the
Protobuf bytes are smaller. See examples/part5-performance/README.md."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 940, 560

nodes = [
    {"x": 350, "y": 15, "w": 240, "h": 65,
     "lines": ["client", "WS upgrade + Sec-WebSocket-Protocol"],
     "style": "user"},

    {"x": 270, "y": 110, "w": 400, "h": 70,
     "lines": ["subprotocol negotiation (DRQ-026)", "server picks the first offered value it also supports, echoes it back"],
     "style": "ink"},

    {"x": 40, "y": 220, "w": 400, "h": 120,
     "lines": ["handling-events.v1+json", "Quarkus:8090 / Python:8091",
               "sendText(toJson(event))", "opcode 0x1: JSON TEXT frame"],
     "style": "accent"},

    {"x": 500, "y": 220, "w": 400, "h": 120,
     "lines": ["handling-events.v1+protobuf", "Quarkus:8090 / Python:8091",
               "sendBinary(event.toProto().toByteArray())", "opcode 0x2: Protobuf BINARY frame"],
     "style": "box"},

    {"x": 60, "y": 380, "w": 360, "h": 55,
     "lines": ["RECEIVE event, e.g. 247 bytes", "eventId/bookingId/eventType/occurredAt/..."],
     "style": "sub"},

    {"x": 520, "y": 380, "w": 360, "h": 55,
     "lines": ["same RECEIVE event, e.g. 149 bytes", "same field VALUES, ~40% smaller"],
     "style": "sub"},

    {"x": 300, "y": 475, "w": 340, "h": 60,
     "lines": ["decode both -> identical field values", "verify.sh asserts byte-for-byte equal after decode"],
     "style": "ghost"},
]

edges = [
    {"x1": 440, "y1": 80, "x2": 440, "y2": 110,
     "label": "upgrade", "lx": 10},
    {"x1": 390, "y1": 180, "x2": 240, "y2": 220,
     "label": "+json offered", "amber": True},
    {"x1": 550, "y1": 180, "x2": 700, "y2": 220,
     "label": "+protobuf offered", "amber": True},
    {"x1": 240, "y1": 340, "x2": 240, "y2": 380,
     "dashed": True},
    {"x1": 700, "y1": 340, "x2": 700, "y2": 380,
     "dashed": True},
    {"x1": 240, "y1": 435, "x2": 440, "y2": 475,
     "dashed": True},
    {"x1": 700, "y1": 435, "x2": 640, "y2": 475,
     "dashed": True},
]

notes = [
    {"x": 470, "y": 545, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Same contract, same fixture, two wire encodings: verify.sh proves field equality and the Protobuf size win live on both stacks."},
]

generate_diagram.emit("part5-performance-architecture", W, H, nodes=nodes, edges=edges, notes=notes)
