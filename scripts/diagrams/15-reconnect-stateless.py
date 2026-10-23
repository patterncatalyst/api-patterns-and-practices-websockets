#!/usr/bin/env python3
"""Fig 15.1/15.2: Ch15: the stateless-mode gap (verify.sh's Stage A proof
connect, 3 seeds, disconnect, inject a gap event, reconnect with
?afterEventId=<last seed id>, the gap event is NOT delivered), and the
decision criteria for when that gap is acceptable versus when it needs the
Kafka-backed replay Ch16 adds. Figure 15.1's layout is the one
Ch16's counterpart figure reuses: same five stages, same positions: so the
two chapters' diagrams read as a before/after pair: this one ends in a grey
LOST box, Ch16's ends in a delivered one."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 15.1: the gap timeline (stateless mode loses the gap-era event)
# ---------------------------------------------------------------------------
W1, H1 = 1180, 420

bands_1 = [
    {"x": 20, "y": 20, "w": 1140, "h": 380,
     "label": "Stateless mode (default profile, no broker): PROTOCOL.md \"Resume parameter\"",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 50, "y": 70, "w": 190, "h": 80,
     "lines": ["CONNECT", "3-event fixture seed", "delivered (RECEIVE/LOAD/CUSTOMS)"],
     "style": "accent"},
    {"x": 300, "y": 70, "w": 180, "h": 80,
     "lines": ["DISCONNECT", "client goes away;", "StatelessBackplane keeps nothing"],
     "style": "box"},
    {"x": 300, "y": 190, "w": 180, "h": 90,
     "lines": ["GAP", "POST /internal/.../handling-events", "injected while disconnected"],
     "style": "ghost"},
    {"x": 300, "y": 310, "w": 180, "h": 70,
     "lines": ["LOST", "no subscriber queue to land in", "delivered to nobody, kept nowhere"],
     "style": "ink"},
    {"x": 560, "y": 70, "w": 230, "h": 80,
     "lines": ["RECONNECT", "?afterEventId=<last seed id>", "query param accepted..."],
     "style": "user"},
    {"x": 870, "y": 70, "w": 250, "h": 80,
     "lines": ["...and IGNORED", "replayFor()/subscribe() return", "no history for this id: ever"],
     "style": "ink"},
    {"x": 870, "y": 190, "w": 250, "h": 90,
     "lines": ["LIVE TAIL ONLY", "new events from reconnect", "onward are delivered normally"],
     "style": "accent"},
]

edges_1 = [
    {"x1": 240, "y1": 110, "x2": 300, "y2": 110, "label": "socket drops"},
    {"x1": 390, "y1": 150, "x2": 390, "y2": 190, "label": "client not watching"},
    {"x1": 390, "y1": 280, "x2": 390, "y2": 310, "label": "never queued, never stored", "amber": True},
    {"x1": 480, "y1": 110, "x2": 560, "y2": 110, "label": "new WS upgrade"},
    {"x1": 790, "y1": 110, "x2": 870, "y2": 110},
    {"x1": 995, "y1": 150, "x2": 995, "y2": 190, "label": "the only thing resumed is the socket", "amber": True},
]

notes_1 = [
    {"x": 590, "y": 390, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "Resuming the SOCKET is not resuming the STREAM. The gap event is gone the moment it's injected: reconnect can't ask for what no server ever kept."},
]

generate_diagram.emit("15-gap-timeline", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 15.2: when stateless reconnect is fine vs. when it isn't
# ---------------------------------------------------------------------------
W2, H2 = 1080, 460

bands_2 = [
    {"x": 20, "y": 20, "w": 1040, "h": 190,
     "label": "Stateless reconnect is FINE when...",
     "fill": "#fafafa"},
    {"x": 20, "y": 230, "w": 1040, "h": 210,
     "label": "Stateless reconnect is NOT ENOUGH when...",
     "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 50, "y": 65, "w": 290, "h": 75,
     "lines": ["A full resync is cheap", "GET the current state on reconnect;", "the feed is a notification, not the record of truth"],
     "style": "accent"},
    {"x": 370, "y": 65, "w": 280, "h": 75,
     "lines": ["Only the latest value matters", "a position indicator, a live price", "an old value is stale, not missing"],
     "style": "accent"},
    {"x": 680, "y": 65, "w": 340, "h": 75,
     "lines": ["Gaps are self-correcting", "the next push supersedes", "whatever the gap cost"],
     "style": "accent"},

    {"x": 50, "y": 275, "w": 290, "h": 85,
     "lines": ["Every event is a discrete fact", "billing, customs, an audit trail", "a missed HandlingEvent is a missed charge"],
     "style": "ink"},
    {"x": 370, "y": 275, "w": 280, "h": 85,
     "lines": ["No cheap full resync exists", "the feed IS the record;", "no REST endpoint to re-GET the gap from"],
     "style": "ink"},
    {"x": 680, "y": 275, "w": 340, "h": 85,
     "lines": ["At-least-once delivery is required", "a consumer needs every eventId", "accounted for, not only the newest one"],
     "style": "ink"},
]

edges_2 = []

notes_2 = [
    {"x": 540, "y": 190, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "=> default/stateless mode (this chapter) is the right tool"},
    {"x": 540, "y": 425, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "=> needs a durable, replayable log a client can resume from an offset: Chapter 16's Kafka-backed backplane"},
]

generate_diagram.emit("15-when-stateless-ok", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
