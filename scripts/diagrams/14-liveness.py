#!/usr/bin/env python3
"""Fig 14.1/14.2: Ch14: why relying on Vert.x idle-timeout alone never
detects a dead peer (the server's own outbound ping is write activity that
resets the idle clock), versus HeartbeatLivenessSweep's pong-tracked sweep
that actually closes a silent connection (CloseCodes.LIVENESS_TIMEOUT,
4408): and the real timeline from last pong to the TCP socket actually
going away, including Vert.x's ~10s closing-handshake grace and the 1006
HandlingEventConnectionWebSocket#onClose observes when that grace expires."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 14.1: idle-timeout trap (BROKEN) vs pong-tracked sweep (WORKS)
# ---------------------------------------------------------------------------
W1, H1 = 960, 520

bands_1 = [
    {"x": 20, "y": 20, "w": 920, "h": 220,
     "label": "BROKEN: auto-ping-interval + quarkus.http.idle-timeout alone",
     "fill": "#fafafa"},
    {"x": 20, "y": 270, "w": 920, "h": 230,
     "label": "WORKS: HandlingEventConnectionWebSocket + HeartbeatLivenessSweep",
     "fill": "#fafafa"},
]

nodes_1 = [
    # broken lane
    {"x": 50, "y": 70, "w": 190, "h": 75,
     "lines": ["SILENT PEER", "upgrade completes,", "then never answers a ping"],
     "style": "box"},
    {"x": 320, "y": 70, "w": 210, "h": 75,
     "lines": ["SERVER auto-ping", "sends PING every", "auto-ping-interval (20s)"],
     "style": "accent"},
    {"x": 610, "y": 70, "w": 300, "h": 75,
     "lines": ["idle-timeout clock", "resets on this WRITE", "read OR write both count"],
     "style": "ink"},
    {"x": 610, "y": 170, "w": 300, "h": 55,
     "lines": ["40s idle-timeout never expires", "connection looks healthy forever"],
     "style": "ink"},

    # works lane
    {"x": 50, "y": 320, "w": 190, "h": 75,
     "lines": ["SILENT PEER", "same peer,", "never pongs"],
     "style": "box"},
    {"x": 320, "y": 320, "w": 230, "h": 75,
     "lines": ["LAST_PONG_AT", "stamped on open, never", "updated again: stays stale"],
     "style": "user"},
    {"x": 620, "y": 320, "w": 290, "h": 75,
     "lines": ["HeartbeatLivenessSweep", "ticks every sweep-interval (5s),", "compares now - LAST_PONG_AT"],
     "style": "user"},
    {"x": 620, "y": 420, "w": 290, "h": 60,
     "lines": [">livenessTimeout (45s)", "close(4408) requested"],
     "style": "accent"},
]

edges_1 = [
    {"x1": 240, "y1": 107, "x2": 320, "y2": 107, "label": "stays silent"},
    {"x1": 530, "y1": 107, "x2": 610, "y2": 107, "label": "write activity"},
    {"x1": 760, "y1": 145, "x2": 760, "y2": 170, "label": "clock reset, again and again", "amber": True},

    {"x1": 240, "y1": 357, "x2": 320, "y2": 357, "label": "never pongs"},
    {"x1": 550, "y1": 357, "x2": 620, "y2": 357, "label": "sweep reads userData()"},
    {"x1": 765, "y1": 395, "x2": 765, "y2": 420, "label": "silentFor > timeout", "amber": True},
]

notes_1 = [
    {"x": 480, "y": 500, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "idle-timeout resets on the server's OWN outbound ping: a silent peer never trips it. Only an explicit pong-tracked sweep does."},
]

generate_diagram.emit("14-idle-timeout-trap", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 14.2: ping/pong + sweep timeline, last pong to TCP actually closing
# ---------------------------------------------------------------------------
W2, H2 = 1180, 360

bands_2 = [
    {"x": 20, "y": 20, "w": 1140, "h": 300,
     "label": "Default config: auto-ping-interval=20s, liveness-timeout=45s, sweep-interval=5s, Vert.x closing grace=~10s",
     "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 50, "y": 70, "w": 170, "h": 70,
     "lines": ["T+0s", "last pong received", "LAST_PONG_AT stamped"],
     "style": "accent"},
    {"x": 260, "y": 70, "w": 170, "h": 70,
     "lines": ["T+20s / T+40s", "server PINGs sent,", "peer never answers"],
     "style": "box"},
    {"x": 470, "y": 70, "w": 180, "h": 70,
     "lines": ["T+45s", "sweep tick: silentFor", "> livenessTimeout"],
     "style": "user"},
    {"x": 690, "y": 70, "w": 190, "h": 70,
     "lines": ["T+45s", "close(4408) requested,", "CLOSE_REQUESTED marked"],
     "style": "user"},
    {"x": 920, "y": 70, "w": 220, "h": 70,
     "lines": ["T+45s..~55s", "Vert.x closing-handshake", "grace: peer never ACKs"],
     "style": "ink"},
    {"x": 920, "y": 190, "w": 220, "h": 70,
     "lines": ["T+~55s", "TCP forced closed;", "onClose sees code 1006"],
     "style": "ink"},
]

edges_2 = [
    {"x1": 220, "y1": 105, "x2": 260, "y2": 105},
    {"x1": 430, "y1": 105, "x2": 470, "y2": 105, "label": "2 missed pongs"},
    {"x1": 650, "y1": 105, "x2": 690, "y2": 105, "label": "4408 selected"},
    {"x1": 880, "y1": 105, "x2": 920, "y2": 105, "label": "close frame sent"},
    {"x1": 1030, "y1": 140, "x2": 1030, "y2": 190, "label": "~10s with no reply", "amber": True},
]

notes_2 = [
    {"x": 590, "y": 310, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "verify.sh's Step 6 shrinks all three knobs for a fast test (~16s observed live, not ~55s): the sequence of events is identical, only the durations shrink."},
]

generate_diagram.emit("14-pong-sweep-timeline", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
