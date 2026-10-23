#!/usr/bin/env python3
"""Figure for Ch1: the Booking lifecycle as a state pipeline, with the
handling-event feed that streams over the WebSocket beneath it.

Top lane: the four Booking states (PENDING -> CONFIRMED -> IN_TRANSIT ->
DELIVERED) the REST booking service tracks. Bottom lane: the handling events
recorded against the booking as it moves, each one pushed over the socket the
instant it happens instead of being discovered by a poll. Dashed connectors
map the events to the state during which they occur.
"""
import sys, os
sys.path.insert(0, "scripts")
import generate_diagram as gd

gd.OUT = "assets/diagrams"
os.makedirs(gd.OUT, exist_ok=True)

# --- states (top lane) ---
sy, sh, sw = 60, 60, 170
sx = [20, 235, 450, 665]
states = ["PENDING", "CONFIRMED", "IN_TRANSIT", "DELIVERED"]
nodes = [
    {"x": sx[i], "y": sy, "w": sw, "h": sh, "lines": [states[i]], "style": "user"}
    for i in range(4)
]

# transitions between states (amber, forward-only)
edges = []
for i in range(3):
    edges.append({
        "x1": sx[i] + sw, "y1": sy + sh / 2,
        "x2": sx[i + 1], "y2": sy + sh / 2,
        "amber": True,
    })

# --- handling-event feed (bottom lane) ---
band = [{"x": 20, "y": 250, "w": 815, "h": 120,
         "label": "Handling-event feed: each event pushed over the WebSocket, not polled for",
         "fill": "#fff8ef"}]

ey, eh, ew = 290, 52, 150
events = [
    (40,  "GATE_IN",             "container gated in"),
    (235, "LOAD / UNLOAD",       "container moves"),
    (430, "CUSTOMS_HOLD",        "hold opened"),
    (660, "DELIVERY_CONFIRMED",  "signed at the dock"),
]
for ex, title, detail in events:
    nodes.append({"x": ex, "y": ey, "w": ew, "h": eh,
                  "lines": [title, detail], "style": "accent"})

# dashed connectors: the state during which each event is recorded
# GATE_IN at CONFIRMED->IN_TRANSIT; LOAD/UNLOAD + CUSTOMS_HOLD during IN_TRANSIT;
# DELIVERY_CONFIRMED at DELIVERED.
connect = [
    (sx[1] + sw / 2, 40 + ew / 2),      # CONFIRMED -> GATE_IN
    (sx[2] + sw / 2, 235 + ew / 2),     # IN_TRANSIT -> LOAD/UNLOAD
    (sx[2] + sw / 2, 430 + ew / 2),     # IN_TRANSIT -> CUSTOMS_HOLD
    (sx[3] + sw / 2, 660 + ew / 2),     # DELIVERED -> DELIVERY_CONFIRMED
]
for x_top, x_bot in connect:
    edges.append({"x1": x_top, "y1": sy + sh, "x2": x_bot, "y2": ey, "dashed": True})

notes = [{"x": 20, "y": 30, "text": "Booking state the REST service tracks",
          "size": 12, "color": "#2f6db5"}]

gd.emit("01-booking-lifecycle", 880, 400, bands=band, nodes=nodes, edges=edges, notes=notes)
