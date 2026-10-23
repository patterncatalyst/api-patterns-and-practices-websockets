#!/usr/bin/env python3
"""Fig 5.1/5.2: Ch5: the AsyncAPI 3 object model as it appears in
contracts/asyncapi.yaml (servers -> channels -> operations -> messages ->
components), and the one-contract-to-two-stacks shape this chapter commits
both the Quarkus and Python examples to."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 5.1: the AsyncAPI 3 object model, walked against our own contract
# ---------------------------------------------------------------------------
W1, H1 = 820, 440

nodes_1 = [
    {"x": 280, "y": 15, "w": 260, "h": 65,
     "lines": ["servers.local", "host: localhost:8080  protocol: ws"],
     "style": "user"},

    {"x": 260, "y": 110, "w": 300, "h": 75,
     "lines": ["channels.handlingEvents",
               "address: /ws/v1/bookings/{bookingId}/handling-events"],
     "style": "accent"},

    {"x": 260, "y": 215, "w": 300, "h": 70,
     "lines": ["operations.receiveHandlingEvent", "action: receive"],
     "style": "accent"},

    {"x": 110, "y": 325, "w": 230, "h": 70,
     "lines": ["components.messages.HandlingEvent", "payload: $ref schemas.HandlingEvent"],
     "style": "box"},

    {"x": 370, "y": 325, "w": 230, "h": 70,
     "lines": ["components.schemas.HandlingEvent", "eventId, bookingId, cargoId,", "eventType, location, occurredAt..."],
     "style": "box"},

    {"x": 630, "y": 325, "w": 170, "h": 70,
     "lines": ["referenced schemas", "HandlingEventType", "Location · Money"],
     "style": "ghost"},
]

edges_1 = [
    {"x1": 410, "y1": 80, "x2": 410, "y2": 110,
     "label": "channel binds to a server"},
    {"x1": 410, "y1": 185, "x2": 410, "y2": 215,
     "label": "operation binds to a channel"},
    {"x1": 350, "y1": 285, "x2": 225, "y2": 325,
     "label": "operation.messages $ref"},
    {"x1": 340, "y1": 360, "x2": 370, "y2": 360,
     "label": "message.payload $ref", "amber": True},
    {"x1": 600, "y1": 360, "x2": 630, "y2": 360,
     "label": "property $ref", "dashed": True},
]

notes_1 = [
    {"x": 410, "y": 420, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "Four top-level sections, never nested: servers, channels, operations, components. AsyncAPI 3's object model."},
]

generate_diagram.emit("05-asyncapi-object-model", W1, H1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 5.2: one contract, two stacks
# ---------------------------------------------------------------------------
W2, H2 = 820, 340

nodes_2 = [
    {"x": 280, "y": 20, "w": 260, "h": 80,
     "lines": ["contracts/asyncapi.yaml", "single source of truth"],
     "style": "ink"},

    {"x": 60, "y": 160, "w": 300, "h": 110,
     "lines": ["Quarkus", "WebSockets Next", "@OnOpen / @OnTextMessage handlers", "hand-kept to HandlingEvent schema"],
     "style": "user"},

    {"x": 460, "y": 160, "w": 300, "h": 110,
     "lines": ["Python", "FastAPI/Starlette + websockets", "connection handler per booking",
               "hand-kept to HandlingEvent schema"],
     "style": "accent"},
]

edges_2 = [
    {"x1": 350, "y1": 100, "x2": 210, "y2": 160,
     "label": "validates against (r02); generates from (r03)"},
    {"x1": 470, "y1": 100, "x2": 610, "y2": 160,
     "label": "validates against (r02); generates from (r03)"},
    {"x1": 360, "y1": 215, "x2": 460, "y2": 215,
     "label": "same channel, same message shape", "dashed": True, "bidir": True},
]

notes_2 = [
    {"x": 410, "y": 315, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Neither stack reads the other's source: both answer to the one contract, checked by asyncapi validate."},
]

generate_diagram.emit("05-contract-to-two-stacks", W2, H2, nodes=nodes_2, edges=edges_2, notes=notes_2)
