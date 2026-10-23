#!/usr/bin/env python3
"""Fig 19.1/19.2: Ch19: the same HandlingEvent carried as a JSON text frame
vs. a Protobuf binary frame (the RECEIVE event's measured sizes from
examples/part5-performance/README.md, 247B/149B), and why the proto side
wins: stable integer field numbers on the wire vs. repeated JSON key
literals: the same additive-only field-number discipline Ch7 applies to
the AsyncAPI contract, now applied to contracts/handling-event.proto."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 19.1: one message, two wire encodings, two frame opcodes
# ---------------------------------------------------------------------------
W1, H1 = 900, 460

nodes_1 = [
    {"x": 330, "y": 10, "w": 240, "h": 60,
     "lines": ["HandlingEvent (RECEIVE)", "one value, one contract"],
     "style": "user"},

    {"x": 250, "y": 100, "w": 400, "h": 60,
     "lines": ["Sec-WebSocket-Protocol negotiation (DRQ-026)",
               "+json or +protobuf, echoed back on the 101"],
     "style": "ink"},

    {"x": 40, "y": 200, "w": 370, "h": 100,
     "lines": ["handling-events.v1+json", "sendText(event) / ws.send(str)",
               "opcode 0x1: TEXT frame"],
     "style": "box"},
    {"x": 490, "y": 200, "w": 370, "h": 100,
     "lines": ["handling-events.v1+protobuf", "sendBinary(bytes) / ws.send(bytes)",
               "opcode 0x2: BINARY frame"],
     "style": "accent"},

    {"x": 40, "y": 330, "w": 370, "h": 55,
     "lines": ['{"eventId":"evt_...","eventType":"RECEIVE",...}', "247 bytes on the wire"],
     "style": "sub"},
    {"x": 490, "y": 330, "w": 370, "h": 55,
     "lines": ["08 76 65 74 5f 2e 2e 2e 20 01 2a ...", "149 bytes on the wire: 39.7% smaller"],
     "style": "sub"},

    {"x": 260, "y": 410, "w": 380, "h": 40,
     "lines": ["verify.sh decodes both -> identical field values"],
     "style": "ghost"},
]

edges_1 = [
    {"x1": 450, "y1": 70, "x2": 450, "y2": 100},
    {"x1": 370, "y1": 160, "x2": 225, "y2": 200, "amber": True, "label": "+json offered"},
    {"x1": 530, "y1": 160, "x2": 675, "y2": 200, "amber": True, "label": "+protobuf offered"},
    {"x1": 225, "y1": 300, "x2": 225, "y2": 330, "dashed": True},
    {"x1": 675, "y1": 300, "x2": 675, "y2": 330, "dashed": True},
    {"x1": 225, "y1": 385, "x2": 400, "y2": 410, "dashed": True},
    {"x1": 675, "y1": 385, "x2": 500, "y2": 410, "dashed": True},
]

notes_1 = [
    {"x": 450, "y": 460 - 8, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "Same channel, same fixture event: only the frame opcode and the byte layout change."},
]

generate_diagram.emit("19-two-encodings-one-message", W1, H1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 19.2: field numbers vs. key names: why the bytes differ, and what
# stays stable across an additive change to either side
# ---------------------------------------------------------------------------
W2, H2 = 900, 420

bands_2 = [
    {"x": 20, "y": 40, "w": 410, "h": 330, "label": "JSON (asyncapi.yaml component schema)", "fill": "#fafafa"},
    {"x": 470, "y": 40, "w": 410, "h": 330, "label": "Protobuf (handling-event.proto)", "fill": "#fff3e0"},
]

ROWS_JSON = [
    ('"eventId"', 70),
    ('"bookingId"', 110),
    ('"cargoId"', 150),
    ('"eventType"', 190),
    ('"location"', 230),
    ('"occurredAt"', 270),
    ('"registeredAt"', 310),
]
ROWS_PROTO = [
    ("1  event_id", 70),
    ("2  booking_id", 110),
    ("3  cargo_id", 150),
    ("4  event_type", 190),
    ("5  location", 230),
    ("6  occurred_at", 270),
    ("7  registered_at", 310),
]

nodes_2 = []
for text, y in ROWS_JSON:
    nodes_2.append({"x": 45, "y": y, "w": 360, "h": 30,
                     "lines": [f"{text}: <value>: key literal sent every frame"],
                     "style": "sub"})
for text, y in ROWS_PROTO:
    nodes_2.append({"x": 495, "y": y, "w": 360, "h": 30,
                     "lines": [f"tag {text} = <value>: one-byte tag, no name on the wire"],
                     "style": "sub"})

notes_2 = [
    {"x": 225, "y": 25, "size": 12, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "renaming a key is free; field NUMBERS never move or get reused"},
    {"x": 675, "y": 25, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "field numbers are the wire identity: additive-only, same as Ch7's JSON discipline"},
    {"x": 450, "y": 405, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "check-proto-parity.py fails the build the moment either side adds, removes, or reorders a field the other side doesn't also carry."},
]

generate_diagram.emit("19-field-numbers-vs-key-names", W2, H2, bands=bands_2, nodes=nodes_2, edges=[], notes=notes_2)
