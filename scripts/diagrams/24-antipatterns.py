#!/usr/bin/env python3
"""Fig 24.1/24.2 — Ch24: the anti-pattern -> remedy map across all eight
mistakes this chapter names (each cited against the chapter/file where this
site caught it live), and the dev-vs-prod timeline showing why the Ch14
idle-timeout trap passes a short manual test and only fails once a
connection lives long enough for a silent peer's own ping-driven clock
reset to matter."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 24.1 — anti-pattern -> remedy map, four rows + two extra pairs
# ---------------------------------------------------------------------------
W1, H1 = 1180, 760

bands_1 = [
    {"x": 20, "y": 20, "w": 1140, "h": 110, "label": "LIFECYCLE", "fill": "#fafafa"},
    {"x": 20, "y": 150, "w": 1140, "h": 190, "label": "BOUNDS", "fill": "#fafafa"},
    {"x": 20, "y": 360, "w": 1140, "h": 110, "label": "SECURITY", "fill": "#fafafa"},
    {"x": 20, "y": 490, "w": 1140, "h": 190, "label": "SCHEMA & DESIGN", "fill": "#fafafa"},
]

def pair(y, left_lines, right_lines, h=80):
    return [
        {"x": 50, "y": y, "w": 520, "h": h, "lines": left_lines, "style": "box"},
        {"x": 620, "y": y, "w": 520, "h": h, "lines": right_lines, "style": "ink"},
    ]

nodes_1 = []
edges_1 = []

# Lifecycle row
nodes_1 += pair(55,
    ["idle-timeout resets on the server's", "OWN outbound ping (Ch14)"],
    ["pong-tracked LAST_PONG_AT + a scheduled", "sweep, close 4408"])

# Bounds row (two pairs stacked)
nodes_1 += pair(185,
    ["asyncio.Queue maxsize<=0 means", "UNBOUNDED, not zero (Ch12)"],
    ["a positive bound + a send timeout,", "close 4290"])
nodes_1 += pair(275,
    ["a backplane with N instances does N", "times the discard work per event (Ch18)"],
    ["key/partition the broadcast domain —", "don't treat it as unbounded"])

# Security row
nodes_1 += pair(395,
    ["four token failures answered", "differently is a signature oracle (Ch17)"],
    ["collapse every failure to one close code,", "1008 — reason logged server-side only"])

# Schema & design row (two pairs stacked)
nodes_1 += pair(525,
    ["a reused Protobuf field number is a", "silent misread, not a parse error (Ch19)"],
    ["field numbers are additive-only — buf", "breaking + check-proto-parity.py gate it"])
nodes_1 += pair(615,
    ["rejecting a client that offers no", "subprotocol (Ch19, DRQ-026)"],
    ["an explicit permissive fallback path,", "JSON by default"])

for y in (95, 225, 315, 435, 565, 655):
    edges_1.append({"x1": 570, "y1": y, "x2": 620, "y2": y, "amber": True})

notes_1 = [
    {"x": 590, "y": 735, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Every left box is a real failure this site's own verify.sh or build caught; every right box is the fix already shipped in the example it names."},
]

generate_diagram.emit("24-pattern-remedy-map", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 24.2 — dev-vs-prod timeline for the idle-timeout trap
# ---------------------------------------------------------------------------
W2, H2 = 1180, 460

bands_2 = [
    {"x": 20, "y": 20, "w": 1140, "h": 180,
     "label": "IN DEV — a short-lived manual test", "fill": "#fafafa"},
    {"x": 20, "y": 230, "w": 1140, "h": 210,
     "label": "IN PROD — a connection held open for hours", "fill": "#fafafa"},
]

nodes_2 = [
    # dev lane
    {"x": 50, "y": 70, "w": 230, "h": 65,
     "lines": ["connection opens,", "a developer sends a few", "messages by hand"],
     "style": "box"},
    {"x": 320, "y": 70, "w": 230, "h": 65,
     "lines": ["tab closed within a minute", "or two — well inside any", "idle-timeout window"],
     "style": "box"},
    {"x": 600, "y": 70, "w": 540, "h": 65,
     "lines": ["looks completely fine — nobody ever waits long enough",
               "for the idle clock to matter, because it never has to"],
     "style": "ghost"},

    # prod lane
    {"x": 50, "y": 280, "w": 230, "h": 65,
     "lines": ["same auto-ping / idle-timeout", "config, same channel,", "connection held for hours"],
     "style": "box"},
    {"x": 320, "y": 280, "w": 230, "h": 65,
     "lines": ["peer goes silent", "(laptop sleeps, mobile", "network drops)"],
     "style": "box"},
    {"x": 600, "y": 280, "w": 280, "h": 65,
     "lines": ["server's own outbound ping keeps", "resetting the idle clock, every interval,", "indefinitely"],
     "style": "accent"},
    {"x": 920, "y": 280, "w": 220, "h": 65,
     "lines": ["talking to nobody for hours,", "still thinks the connection", "is healthy"],
     "style": "accent"},
    {"x": 600, "y": 370, "w": 540, "h": 55,
     "lines": ["only once HeartbeatLivenessSweep is added: 4408 close within one",
               "configured liveness window — proven live in verify.sh's Step 6"],
     "style": "user"},
]

edges_2 = [
    {"x1": 280, "y1": 102, "x2": 320, "y2": 102},
    {"x1": 550, "y1": 102, "x2": 600, "y2": 102},

    {"x1": 280, "y1": 312, "x2": 320, "y2": 312},
    {"x1": 550, "y1": 312, "x2": 600, "y2": 312, "label": "clock reset, again and again", "amber": True},
    {"x1": 880, "y1": 312, "x2": 920, "y2": 312},
    {"x1": 870, "y1": 345, "x2": 870, "y2": 370, "label": "only the pong-tracked sweep breaks this", "amber": True},
]

notes_2 = [
    {"x": 590, "y": 440, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "The exact same configuration passes every short manual check and fails, with no alert, at the one timescale that matters: how long a real connection stays open."},
]

generate_diagram.emit("24-dev-vs-prod-timeline", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
