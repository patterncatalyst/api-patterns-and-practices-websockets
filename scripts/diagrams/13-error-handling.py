#!/usr/bin/env python3
"""Fig 13.1/13.2: Ch13: the close-code-vs-envelope decision (CloseCodes.java /
ws_server.py's docstring) and the bad-frame error flow proven live by
verify.sh's Ch13 step, contrasted with the 1006 abnormal closure a client
synthesizes locally when a peer disappears without a close handshake at all
(ConnectionLifecycleShutdown.java's Javadoc names this directly)."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 13.1: envelope vs close-code-alone decision tree
# ---------------------------------------------------------------------------
W1, H1 = 980, 520

bands_1 = [
    {"x": 20, "y": 20, "w": 940, "h": 480,
     "label": "CloseCodes.java / ws_server.py docstring: one decision, applied per failure",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 350, "y": 55, "w": 280, "h": 70,
     "lines": ["Something went wrong", "on this connection"],
     "style": "accent"},

    {"x": 330, "y": 165, "w": 320, "h": 90,
     "lines": ["Is there ONE specific offending", "frame to annotate, and is the", "socket still open to send on?"],
     "style": "ink"},

    {"x": 60, "y": 310, "w": 320, "h": 110,
     "lines": ["YES: e.g. a malformed client frame", "1. send ErrorEnvelope (still open)", "2. THEN close(BAD_REQUEST / 4400)"],
     "style": "user"},

    {"x": 600, "y": 300, "w": 340, "h": 150,
     "lines": ["NO: no single frame to blame,", "or the socket is already gone", "close code ALONE is the signal:",
                "AUTH_FAILURE 1008 · SLOW_CONSUMER 4290",
                "LIVENESS_TIMEOUT 4408 · UNEXPECTED 1011"],
     "style": "box"},

    {"x": 60, "y": 460, "w": 320, "h": 40,
     "lines": ["client's normal message handler sees WHY"],
     "style": "ghost"},
]

edges_1 = [
    {"x1": 490, "y1": 125, "x2": 490, "y2": 165},
    {"x1": 400, "y1": 255, "x2": 260, "y2": 310, "label": "yes"},
    {"x1": 580, "y1": 255, "x2": 740, "y2": 300, "label": "no"},
    {"x1": 220, "y1": 420, "x2": 220, "y2": 460, "amber": True},
]

notes_1 = [
    {"x": 490, "y": 500, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "A close code alone arrives as the socket is going away: too late to carry detail. The envelope is sent FIRST, while the connection is still open."},
]

generate_diagram.emit("13-error-decision-tree", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 13.2: bad-frame error flow vs. 1006 abnormal closure
# ---------------------------------------------------------------------------
W2, H2 = 1000, 460

bands_2 = [
    {"x": 20, "y": 20, "w": 460, "h": 420,
     "label": "Protocol error: verify.sh Ch13 step, both stacks", "fill": "#fafafa"},
    {"x": 510, "y": 20, "w": 470, "h": 420,
     "label": "Peer disappears: no close handshake at all", "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 50, "y": 60, "w": 400, "h": 55,
     "lines": ["Client sends a client-to-server frame", "(channel defines none: any frame is invalid)"],
     "style": "accent"},

    {"x": 50, "y": 150, "w": 400, "h": 60,
     "lines": ["Server: onTextMessage / _receive_loop", "classifies WHY (not JSON, not object, ...)"],
     "style": "ink"},

    {"x": 50, "y": 245, "w": 400, "h": 55,
     "lines": ["sendText(ErrorEnvelope.badRequest(...))", "{\"error\":{\"code\":\"BAD_REQUEST\", ...}}"],
     "style": "user"},

    {"x": 50, "y": 335, "w": 400, "h": 85,
     "lines": ["connection.close(BAD_REQUEST, ...)", "client onmessage fires FIRST (envelope),",
               "then onclose fires with code=4400"],
     "style": "box"},

    {"x": 540, "y": 60, "w": 400, "h": 55,
     "lines": ["Process killed / network partition /", "cable pulled: no FIN, no close frame"],
     "style": "accent"},

    {"x": 540, "y": 150, "w": 400, "h": 60,
     "lines": ["No ErrorEnvelope possible: the server", "never got a chance to send one"],
     "style": "ink"},

    {"x": 540, "y": 245, "w": 400, "h": 60,
     "lines": ["Peer's TCP stack eventually gives up", "(timeout) or never notices at all"],
     "style": "box"},

    {"x": 540, "y": 335, "w": 400, "h": 85,
     "lines": ["Client runtime SYNTHESIZES onclose", "code=1006 \"abnormal closure\" locally", "never sent on the wire by either peer"],
     "style": "ghost"},
]

edges_2 = [
    {"x1": 250, "y1": 115, "x2": 250, "y2": 150},
    {"x1": 250, "y1": 210, "x2": 250, "y2": 245},
    {"x1": 250, "y1": 300, "x2": 250, "y2": 335},
    {"x1": 740, "y1": 115, "x2": 740, "y2": 150},
    {"x1": 740, "y1": 210, "x2": 740, "y2": 245},
    {"x1": 740, "y1": 305, "x2": 740, "y2": 335, "dashed": True, "amber": True},
]

notes_2 = [
    {"x": 500, "y": 445, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "1006 is a reserved RFC 6455 value an implementation must never put in an actual close frame: it exists only for a local API to report \"the connection ended with no handshake.\""},
]

generate_diagram.emit("13-error-flow-vs-1006", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
