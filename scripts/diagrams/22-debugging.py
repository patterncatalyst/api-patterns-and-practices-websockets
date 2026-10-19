#!/usr/bin/env python3
"""Fig 22.1/22.2 — Ch22: where each debugging tool actually taps a live
WebSocket connection (handshake / data frames / close, plus the TCP layer
underneath all three), and a symptom-to-tool decision map for picking the
right one first instead of reaching for tcpdump on a problem curl --include
would have shown in one request."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 22.1 — connection lifecycle with each tool's tap point
# ---------------------------------------------------------------------------
W1, H1 = 1120, 620

bands_1 = [
    {"x": 20, "y": 20, "w": 1080, "h": 150,
     "label": "HANDSHAKE — one HTTP request, one 101 response", "fill": "#fafafa"},
    {"x": 20, "y": 190, "w": 1080, "h": 150,
     "label": "DATA FRAMES — every byte after the 101 belongs to a frame", "fill": "#fafafa"},
    {"x": 20, "y": 360, "w": 1080, "h": 150,
     "label": "CLOSE — a close frame, or an abrupt reset with none", "fill": "#fafafa"},
]

nodes_1 = [
    # handshake lane
    {"x": 50, "y": 55, "w": 300, "h": 80,
     "lines": ["CLIENT", "GET + Upgrade, Connection,", "Sec-WebSocket-Key, Version:13"],
     "style": "box"},
    {"x": 410, "y": 55, "w": 290, "h": 80,
     "lines": ["SERVER", "101 Switching Protocols +", "Sec-WebSocket-Accept"],
     "style": "accent"},
    {"x": 760, "y": 55, "w": 320, "h": 80,
     "lines": ["TAP: curl --include /", "browser DevTools Network tab", "— see the 101 + every header"],
     "style": "user"},

    # frames lane
    {"x": 50, "y": 225, "w": 290, "h": 80,
     "lines": ["TEXT frame", "opcode 0x1 — JSON", "e.g. HandlingEvent"],
     "style": "box"},
    {"x": 400, "y": 225, "w": 300, "h": 80,
     "lines": ["BINARY frame", "opcode 0x2 — Protobuf", "same message, fewer bytes"],
     "style": "box"},
    {"x": 760, "y": 225, "w": 320, "h": 80,
     "lines": ["TAP: DevTools Frames tab", "(per connection) / websocat", "-t (text) or -b (binary)"],
     "style": "user"},

    # close lane
    {"x": 50, "y": 400, "w": 290, "h": 80,
     "lines": ["CLOSE frame", "code + optional reason", "(or: peer vanishes, no frame)"],
     "style": "box"},
    {"x": 400, "y": 400, "w": 300, "h": 80,
     "lines": ["TCP teardown", "two-way close handshake,", "or abrupt reset -> 1006"],
     "style": "ink"},
    {"x": 760, "y": 400, "w": 320, "h": 100,
     "lines": ["TAP: python ws_close_probe", "(websockets lib) reads", "ws.close_code directly —", "websocat CANNOT see this"],
     "style": "accent"},
]

edges_1 = [
    {"x1": 350, "y1": 95, "x2": 410, "y2": 95, "label": "upgrade request"},
    {"x1": 700, "y1": 95, "x2": 760, "y2": 95, "label": "observed here"},

    {"x1": 340, "y1": 265, "x2": 760, "y2": 265, "label": "inspect"},
    {"x1": 400, "y1": 300, "x2": 760, "y2": 300, "label": "inspect"},

    {"x1": 340, "y1": 440, "x2": 400, "y2": 440, "label": "close handshake"},
    {"x1": 700, "y1": 440, "x2": 760, "y2": 440, "label": "the blind spot", "amber": True},
]

notes_1 = [
    {"x": 560, "y": 585, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "tcpdump/Wireshark taps underneath all three phases at the TCP layer — full visibility on ws://, only encrypted length/timing on wss://."},
]

generate_diagram.emit("22-lifecycle-taps", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 22.2 — symptom-to-tool decision map
# ---------------------------------------------------------------------------
W2, H2 = 1300, 440

bands_2 = [
    {"x": 20, "y": 20, "w": 1260, "h": 400, "label": "", "fill": "#ffffff"},
]

root_2 = {"x": 460, "y": 30, "w": 380, "h": 55,
          "lines": ["Symptom on a live connection?"], "style": "ink"}

cols = [
    {
        "x": 30,
        "symptom": ["Never upgrades", "(no 101 at all)"],
        "tool": ["curl --include", "the Upgrade request"],
        "diag": ["Proxy stripped", "Connection: Upgrade,", "or wrong path/headers"],
    },
    {
        "x": 290,
        "symptom": ["101 arrives,", "then silence / hang"],
        "tool": ["DevTools Frames tab", "or websocat -t"],
        "diag": ["Auth gate rejected", "post-upgrade (Ch17), or", "subprotocol mismatch"],
    },
    {
        "x": 550,
        "symptom": ["Frame arrives,", "wrong shape / won't parse"],
        "tool": ["DevTools binary/text icon,", "websocat -b | xxd"],
        "diag": ["Opcode mismatch —", "binary negotiated, client", "expects text (Ch19)"],
    },
    {
        "x": 810,
        "symptom": ["Connection drops,", "no obvious reason"],
        "tool": ["python ws_close_probe", "+ server trace-id logs"],
        "diag": ["close_code says WHY —", "4400/4290/4408/1008;", "1006 = no code arrived"],
    },
    {
        "x": 1070,
        "symptom": ["Works, then dies", "after sustained load"],
        "tool": ["tcpdump/Wireshark on TCP", "+ server logs over time"],
        "diag": ["Backpressure (4290) or", "liveness sweep (4408/1011)", "firing under pressure"],
    },
]

COL_W = 210

nodes_2 = [root_2]
edges_2 = []
for c in cols:
    x = c["x"]
    sy, ty, dy = 115, 205, 295
    s = {"x": x, "y": sy, "w": COL_W, "h": 65, "lines": c["symptom"], "style": "box"}
    t = {"x": x, "y": ty, "w": COL_W, "h": 65, "lines": c["tool"], "style": "user"}
    d = {"x": x, "y": dy, "w": COL_W, "h": 80, "lines": c["diag"], "style": "ink"}
    nodes_2 += [s, t, d]
    cx = x + COL_W / 2
    edges_2.append({"x1": cx, "y1": 85, "x2": cx, "y2": sy})
    edges_2.append({"x1": cx, "y1": sy + 65, "x2": cx, "y2": ty})
    edges_2.append({"x1": cx, "y1": ty + 65, "x2": cx, "y2": dy})

notes_2 = [
    {"x": 650, "y": 420, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Reach for the cheapest tool that taps the right layer first — curl before websocat, websocat before tcpdump."},
]

generate_diagram.emit("22-symptom-to-tool", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
