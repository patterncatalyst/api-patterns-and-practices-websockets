#!/usr/bin/env python3
"""Fig 20.1/20.2: Ch20: the real k6/benchmark.js numbers (examples/
part5-performance/README.md, 2026-10-19 capture): bytes/frame for JSON
vs. Protobuf vs. JSON+permessage-deflate, with the k6/ws measurement
blind spot marked on the deflate bar; and the four throughput levers
(encoding, batching, compression, limits) mapped against where each one
actually applies on this channel."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 20.1: measured bytes/frame, three encodings, one caveat
# ---------------------------------------------------------------------------
W1, H1 = 900, 480

nodes_1 = [
    {"x": 260, "y": 10, "w": 380, "h": 50,
     "lines": ["k6/benchmark.js: 3 scenarios, same channel, same fixture"],
     "style": "user"},

    {"x": 40, "y": 90, "w": 250, "h": 90,
     "lines": ["json", "avg 259.7B / p90 267.0B", "measured on the wire"],
     "style": "box"},
    {"x": 325, "y": 90, "w": 250, "h": 90,
     "lines": ["protobuf", "avg 154.0B / p90 157.0B", "40.7% smaller than json"],
     "style": "accent"},
    {"x": 610, "y": 90, "w": 250, "h": 90,
     "lines": ["json+deflate", "avg 259.7B / p90 267.0B", "identical to plain json"],
     "style": "box"},

    {"x": 610, "y": 200, "w": 250, "h": 80,
     "lines": ["k6/ws inflates compressed frames",
               "before the script sees the bytes",
               "this row can't show the win"],
     "style": "ghost"},

    {"x": 40, "y": 310, "w": 390, "h": 70,
     "lines": ["Python:8091 (websockets)",
               "permessage-deflate negotiated: 7908/7908 (100%)"],
     "style": "sub"},
    {"x": 470, "y": 310, "w": 390, "h": 70,
     "lines": ["Quarkus:8090 (WebSockets Next / Undertow)",
               "permessage-deflate negotiated: 0/11806-18292 (0%)"],
     "style": "sub"},

    {"x": 180, "y": 405, "w": 540, "h": 55,
     "lines": ["same stack difference, reproduced across every run",
               "not proof deflate doesn't help, proof k6/ws can't see it"],
     "style": "ghost"},
]

edges_1 = [
    {"x1": 450, "y1": 60, "x2": 165, "y2": 90},
    {"x1": 450, "y1": 60, "x2": 450, "y2": 90},
    {"x1": 450, "y1": 60, "x2": 735, "y2": 90, "amber": True, "label": "compression: \"deflate\""},
    {"x1": 735, "y1": 180, "x2": 735, "y2": 200, "dashed": True},
    {"x1": 235, "y1": 380, "x2": 400, "y2": 405, "dashed": True},
    {"x1": 665, "y1": 380, "x2": 500, "y2": 405, "dashed": True},
]

notes_1 = [
    {"x": 450, "y": 470, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "Bytes/frame numbers are the fixture's size, not a function of load: the only row that changes with load is connects/sec."},
]

generate_diagram.emit("20-bytes-per-frame", W1, H1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 20.2: the four throughput levers and where each applies
# ---------------------------------------------------------------------------
W2, H2 = 900, 460

bands_2 = [
    {"x": 20, "y": 40, "w": 860, "h": 390, "label": "One HandlingEvent, pushed over one connection", "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 45, "y": 75, "w": 380, "h": 80,
     "lines": ["1. Encoding (Ch19)", "JSON vs. Protobuf: fixed per-frame cost",
               "40.7% smaller, deterministic"],
     "style": "accent"},
    {"x": 475, "y": 75, "w": 380, "h": 80,
     "lines": ["2. Batching / coalescing", "amortize per-frame overhead",
               "fewer, larger frames, adds latency"],
     "style": "box"},

    {"x": 45, "y": 185, "w": 380, "h": 90,
     "lines": ["3. permessage-deflate (RFC 7692)",
               "per-connection DEFLATE state, CPU per frame",
               "Python on by default; Quarkus opt-in, 0% here"],
     "style": "box"},
    {"x": 475, "y": 185, "w": 380, "h": 90,
     "lines": ["4. Size limits",
               "max-message-size / max-frame-size (Quarkus)",
               "max_size / max_queue (Python)"],
     "style": "box"},

    {"x": 160, "y": 310, "w": 580, "h": 70,
     "lines": ["5. Backpressure (Ch12) bounds all of the above",
               "under a slow consumer: a full queue or a stalled sendText",
               "caps effective throughput regardless of encoding or compression"],
     "style": "ink"},

    {"x": 260, "y": 400, "w": 380, "h": 40,
     "lines": ["k6 measures connection-churn here, not a sustained push rate"],
     "style": "ghost"},
]

edges_2 = [
    {"x1": 425, "y1": 115, "x2": 475, "y2": 115, "amber": True},
    {"x1": 235, "y1": 155, "x2": 235, "y2": 185, "dashed": True},
    {"x1": 665, "y1": 155, "x2": 665, "y2": 185, "dashed": True},
    {"x1": 235, "y1": 275, "x2": 400, "y2": 310, "dashed": True},
    {"x1": 665, "y1": 275, "x2": 500, "y2": 310, "dashed": True},
    {"x1": 450, "y1": 380, "x2": 450, "y2": 400, "dashed": True},
]

notes_2 = [
    {"x": 450, "y": 25, "size": 12, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "Four levers above the line, one ceiling below it"},
]

generate_diagram.emit("20-levers", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
