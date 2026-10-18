#!/usr/bin/env python3
"""Fig 4.1/4.2 — Ch4: the shipping/cargo domain nouns this socket pushes and
their relations, and the handling-event feed flow from the REST booking
service's write path through to a watching client's socket."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 4.1 — the domain model: nouns + relations
# ---------------------------------------------------------------------------
W1, H1 = 820, 440

nodes_1 = [
    {"x": 30, "y": 30, "w": 180, "h": 70,
     "lines": ["Booking", "bkg_ + ULID"], "style": "box"},
    {"x": 30, "y": 170, "w": 180, "h": 70,
     "lines": ["Cargo", "crg_ + ULID"], "style": "box"},

    {"x": 310, "y": 30, "w": 180, "h": 70,
     "lines": ["Route"], "style": "box"},
    {"x": 310, "y": 170, "w": 180, "h": 60,
     "lines": ["Leg", "carrier, origin, destination"], "style": "sub"},

    {"x": 600, "y": 95, "w": 190, "h": 70,
     "lines": ["Location", "UN/LOCODE string"], "style": "box"},

    {"x": 170, "y": 310, "w": 280, "h": 100,
     "lines": ["HandlingEvent", "eventType, occurredAt,", "registeredAt"], "style": "accent"},
    {"x": 600, "y": 310, "w": 190, "h": 70,
     "lines": ["Money", "decimal string"], "style": "ink"},
]

edges_1 = [
    {"x1": 120, "y1": 100, "x2": 120, "y2": 170, "label": "has one or more"},
    {"x1": 210, "y1": 65, "x2": 310, "y2": 65, "label": "follows"},
    {"x1": 400, "y1": 100, "x2": 400, "y2": 170, "label": "composed of"},
    {"x1": 490, "y1": 190, "x2": 600, "y2": 150, "label": "origin / destination"},

    {"x1": 120, "y1": 240, "x2": 230, "y2": 310, "label": "recorded against", "amber": True},
    {"x1": 210, "y1": 65, "x2": 290, "y2": 310, "label": "belongs to (bookingId)", "amber": True, "dashed": True},
    {"x1": 450, "y1": 350, "x2": 600, "y2": 300, "label": "occurred at", "amber": True},
    {"x1": 450, "y1": 390, "x2": 600, "y2": 360, "label": "amount (optional)", "amber": True},
]

notes_1 = [
    {"x": 410, "y": 20, "size": 12, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "Shared glossary (REST + gRPC + WebSockets): Booking, Cargo, Route/Leg, Location, Money"},
    {"x": 410, "y": 425, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "HandlingEvent is the only noun this feed pushes; Booking, Cargo, Route, and Location travel inside it as ids and values, never as nested objects."},
]

generate_diagram.emit("04-domain-model", W1, H1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 4.2 — the handling-event feed flow
# ---------------------------------------------------------------------------
W2, H2 = 820, 340

nodes_2 = [
    {"x": 20, "y": 40, "w": 190, "h": 90,
     "lines": ["REST booking service", "source of truth for", "Booking + Cargo state"], "style": "user"},
    {"x": 300, "y": 40, "w": 190, "h": 90,
     "lines": ["Handling event recorded", "a HandlingEvent row is", "written and persisted"], "style": "box"},
    {"x": 580, "y": 40, "w": 220, "h": 90,
     "lines": ["/ws/v1/bookings/{bookingId}", "/handling-events", "pushes on receive"], "style": "accent"},
    {"x": 300, "y": 210, "w": 190, "h": 90,
     "lines": ["Watching client", "one socket per", "watched booking"], "style": "user"},
]

edges_2 = [
    {"x1": 210, "y1": 85, "x2": 300, "y2": 85, "label": "persists event"},
    {"x1": 490, "y1": 85, "x2": 580, "y2": 85, "label": "triggers push", "amber": True},
    {"x1": 690, "y1": 130, "x2": 490, "y2": 255, "label": "HandlingEvent message", "amber": True},
    {"x1": 300, "y1": 255, "x2": 115, "y2": 130, "label": "GET /bookings/{id} still answers full state",
     "dashed": True, "lx": -20, "ly": 10},
]

notes_2 = [
    {"x": 410, "y": 310, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "The socket adds a push path; it never replaces the booking service as the record of truth or its GET endpoint."},
]

generate_diagram.emit("04-handling-event-feed", W2, H2, nodes=nodes_2, edges=edges_2, notes=notes_2)
