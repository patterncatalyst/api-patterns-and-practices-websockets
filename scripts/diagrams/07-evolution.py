#!/usr/bin/env python3
"""Fig 7.1/7.2 — Ch7: classifying a change to the handling-event contract as
safe or breaking, column by topic, and what happens to a v1 client that is
already connected when a breaking change ships behind a dual-publish
window."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 7.1 — the evolution gate: safe vs. breaking, aligned by topic
# ---------------------------------------------------------------------------
W1, H1 = 820, 420

COLS = [20, 225, 430, 635]
COL_W = 165

nodes_1 = [
    {"x": COLS[0], "y": 65, "w": COL_W, "h": 110,
     "lines": ["Field", "add an optional field",
               "(carrierRemarks)"], "style": "accent"},
    {"x": COLS[1], "y": 65, "w": COL_W, "h": 110,
     "lines": ["Enum", "add a new member",
               "(REROUTED)"], "style": "accent"},
    {"x": COLS[2], "y": 65, "w": COL_W, "h": 110,
     "lines": ["Shape", "new channel path version",
               "(/ws/v2/...)"], "style": "accent"},
    {"x": COLS[3], "y": 65, "w": COL_W, "h": 110,
     "lines": ["Requirement", "add a 2nd subprotocol",
               "old one still served"], "style": "accent"},

    {"x": COLS[0], "y": 255, "w": COL_W, "h": 120,
     "lines": ["Field", "remove a field a client",
               "already reads (amount)"], "style": "ink"},
    {"x": COLS[1], "y": 255, "w": COL_W, "h": 120,
     "lines": ["Enum", "repurpose a member's",
               "meaning in place (CUSTOMS)"], "style": "ink"},
    {"x": COLS[2], "y": 255, "w": COL_W, "h": 120,
     "lines": ["Shape", "change a field's type or",
               "unit in place (Money)"], "style": "ink"},
    {"x": COLS[3], "y": 255, "w": COL_W, "h": 120,
     "lines": ["Requirement", "make an optional field",
               "required"], "style": "ink"},
]

edges_1 = [
    {"x1": COLS[i] + COL_W / 2, "y1": 175, "x2": COLS[i] + COL_W / 2, "y2": 255,
     "dashed": True}
    for i in range(4)
]

notes_1 = [
    {"x": 410, "y": 30, "size": 13, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "Classifying a change to the handling-event contract"},
    {"x": 20, "y": 55, "size": 12, "color": "#b8650a", "anchor": "start", "bold": True,
     "text": "SAFE — an old client's deserializer never has to look at the new part"},
    {"x": 20, "y": 245, "size": 12, "color": "#555555", "anchor": "start", "bold": True,
     "text": "BREAKING — an old client misreads bytes it already expected to understand"},
    {"x": 410, "y": 400, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "Each dashed line pairs the same kind of change: safe addition above, breaking mutation of the same thing below."},
]

generate_diagram.emit("07-evolution-gate", W1, H1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 7.2 — connected-client migration across a dual-publish window
# ---------------------------------------------------------------------------
W2, H2 = 820, 360

BAND_X, BAND_W = 20, 780
TCOLS = [40, 330, 620]
TCOL_W = 250

bands_2 = [
    {"x": BAND_X, "y": 40, "w": BAND_W, "h": 90, "label": "Server", "fill": "#fff3e0"},
    {"x": BAND_X, "y": 140, "w": BAND_W, "h": 90, "label": "v1 client — already connected before the change ships", "fill": "#fafafa"},
    {"x": BAND_X, "y": 240, "w": BAND_W, "h": 90, "label": "v2 client — connects after the change ships", "fill": "#eef4fb"},
]

nodes_2 = [
    {"x": TCOLS[0], "y": 65, "w": TCOL_W, "h": 55,
     "lines": ["v1 shape only"], "style": "box"},
    {"x": TCOLS[1], "y": 65, "w": TCOL_W, "h": 55,
     "lines": ["v1 + v2 shape together", "(dual publish)"], "style": "accent"},
    {"x": TCOLS[2], "y": 65, "w": TCOL_W, "h": 55,
     "lines": ["v2 shape only", "v1 support retired"], "style": "box"},

    {"x": TCOLS[0], "y": 165, "w": TCOL_W, "h": 55,
     "lines": ["connected, reading v1"], "style": "user"},
    {"x": TCOLS[1], "y": 165, "w": TCOL_W, "h": 55,
     "lines": ["still connected", "ignores the new field/member"], "style": "ghost"},
    {"x": TCOLS[2], "y": 165, "w": TCOL_W, "h": 55,
     "lines": ["closed with a deprecation", "code — must reconnect on v2"], "style": "ink"},

    {"x": TCOLS[0], "y": 265, "w": TCOL_W, "h": 55,
     "lines": ["not yet connected"], "style": "ghost"},
    {"x": TCOLS[1], "y": 265, "w": TCOL_W, "h": 55,
     "lines": ["connects, reads v2 shape"], "style": "accent"},
    {"x": TCOLS[2], "y": 265, "w": TCOL_W, "h": 55,
     "lines": ["every client now on v2"], "style": "accent"},
]

edges_2 = [
    {"x1": 300, "y1": 15, "x2": 300, "y2": 335, "dashed": True, "amber": True,
     "label": "deploy (t0)", "lx": 0, "ly": -10},
    {"x1": 590, "y1": 15, "x2": 590, "y2": 335, "dashed": True,
     "label": "window closes", "lx": 0, "ly": -10},
]

notes_2 = [
    {"x": 410, "y": 20, "size": 13, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "A connection opened before t0 outlives the deploy that changed the contract"},
]

generate_diagram.emit("07-connected-client-migration", W2, H2, nodes=nodes_2, edges=edges_2, notes=notes_2)
