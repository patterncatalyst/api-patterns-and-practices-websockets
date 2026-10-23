#!/usr/bin/env python3
"""Fig 6.1/6.2: Ch6: the HandlingEvent message's envelope-like fields vs
its payload fields inside one flat JSON object, and the discriminated-union
choice (one reused message + an eventType discriminator) against the
rejected alternative (one AsyncAPI message per event kind)."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 6.1: envelope vs. payload inside one flat message
# ---------------------------------------------------------------------------
W1, H1 = 820, 400

bands_1 = [
    {"x": 20, "y": 60, "w": 780, "h": 300,
     "label": "one JSON object on the wire: components.schemas.HandlingEvent",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 50, "y": 110, "w": 340, "h": 220, "style": "accent",
     "lines": ["Envelope-like fields",
               "eventId: evt_ + ULID, identity",
               "eventType: discriminator (enum)",
               "occurredAt: when it happened",
               "registeredAt: when it was recorded"]},
    {"x": 420, "y": 110, "w": 340, "h": 220, "style": "box",
     "lines": ["Payload fields",
               "bookingId / cargoId: the subject",
               "location: UN/LOCODE string",
               "voyageNumber: optional, voyage context",
               "amount: optional Money (decimal string)"]},
]

edges_1 = [
    {"x1": 390, "y1": 220, "x2": 420, "y2": 220, "dashed": True, "bidir": True,
     "label": "same object, two roles"},
]

notes_1 = [
    {"x": 410, "y": 30, "size": 13, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "No separate wrapper object: the contract keeps one flat message, not { envelope, payload }"},
    {"x": 410, "y": 385, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "\"Envelope\" and \"payload\" here are roles fields play, not a nesting the JSON actually has"},
]

generate_diagram.emit("06-message-envelope", W1, H1, nodes=nodes_1, edges=edges_1, bands=bands_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 6.2: one reused message vs. one message per event kind
# ---------------------------------------------------------------------------
W2, H2 = 820, 360

nodes_2 = [
    {"x": 30, "y": 40, "w": 340, "h": 60, "style": "accent",
     "lines": ["This contract's choice", "one message, eventType discriminates"]},
    {"x": 30, "y": 140, "w": 150, "h": 50, "style": "box", "lines": ["RECEIVE"]},
    {"x": 220, "y": 140, "w": 150, "h": 50, "style": "box", "lines": ["LOAD / UNLOAD"]},
    {"x": 30, "y": 220, "w": 150, "h": 50, "style": "box", "lines": ["CUSTOMS / CLAIM"]},
    {"x": 220, "y": 220, "w": 150, "h": 50, "style": "box", "lines": ["HOLD / DELIVERED"]},

    {"x": 450, "y": 40, "w": 340, "h": 60, "style": "ghost",
     "lines": ["Rejected alternative", "one AsyncAPI message per event kind"]},
    {"x": 450, "y": 140, "w": 150, "h": 50, "style": "ghost", "lines": ["ReceivedEvent"]},
    {"x": 640, "y": 140, "w": 150, "h": 50, "style": "ghost", "lines": ["LoadedEvent"]},
    {"x": 450, "y": 220, "w": 150, "h": 50, "style": "ghost", "lines": ["CustomsEvent"]},
    {"x": 640, "y": 220, "w": 150, "h": 50, "style": "ghost", "lines": ["...4 more schemas"]},
]

edges_2 = [
    {"x1": 105, "y1": 100, "x2": 105, "y2": 140, "label": "eventType ="},
    {"x1": 295, "y1": 100, "x2": 295, "y2": 140},
    {"x1": 105, "y1": 100, "x2": 105, "y2": 220, "dashed": True},
    {"x1": 295, "y1": 100, "x2": 295, "y2": 220, "dashed": True},

    {"x1": 525, "y1": 100, "x2": 525, "y2": 140, "dashed": True},
    {"x1": 715, "y1": 100, "x2": 715, "y2": 140, "dashed": True},
    {"x1": 525, "y1": 100, "x2": 525, "y2": 220, "dashed": True},
    {"x1": 715, "y1": 100, "x2": 715, "y2": 220, "dashed": True},
]

notes_2 = [
    {"x": 410, "y": 300, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "Same seven event kinds either way: the difference is where the branching lives"},
    {"x": 410, "y": 320, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "One schema: adding RECONSIGNED is one new enum value. Seven schemas: it's a new channel message, in both stacks."},
]

generate_diagram.emit("06-one-vs-many-messages", W2, H2, nodes=nodes_2, edges=edges_2, notes=notes_2)
