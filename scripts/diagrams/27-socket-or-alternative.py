#!/usr/bin/env python3
"""Fig 27.1: when a socket already in production is the wrong tool: keep
it for duplex sub-second delivery, otherwise match the interaction to one
of the alternatives."""
import sys, os
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 980, 540
bands = [{"x": 20, "y": 120, "w": 940, "h": 340,
          "label": "No: reach for the alternative that matches the interaction", "fill": "#fafafa"}]
def alt(x, y, title, why, style="box"):
    return {"x": x, "y": y, "w": 285, "h": 80, "lines": [title] + why, "style": style}
nodes = [
    {"x": 280, "y": 20, "w": 420, "h": 60,
     "lines": ["Does it still need both sides sending,", "with sub-second delivery held open?"], "style": "accent"},
    {"x": 760, "y": 20, "w": 200, "h": 60, "lines": ["Keep the WebSocket", "duplex, low latency"], "style": "ink"},
    alt(40, 165, "Server-Sent Events", ["only the server sends to a browser", "native reconnect, Last-Event-ID"]),
    alt(345, 165, "Long-polling", ["the path truncates long-lived", "responses; plain request cycles"]),
    alt(650, 165, "Webhook", ["service to service, the receiver", "hosts a reachable endpoint"]),
    alt(40, 265, "gRPC server-streaming", ["neither end is a browser", "typed, HTTP/2 flow control"]),
    alt(345, 265, "Request/response", ["nothing is live: ask again", "when you need the value"]),
    alt(650, 265, "Message broker", ["backend to backend, needs", "replay and ordering"]),
    {"x": 40, "y": 370, "w": 895, "h": 60,
     "lines": ["HTTP/2 server push", "removed from major browsers: a dead end for browser fan-out"], "style": "ghost"},
]
edges = [
    {"x1": 700, "y1": 50, "x2": 760, "y2": 50, "label": "Yes", "amber": True},
    {"x1": 490, "y1": 80, "x2": 490, "y2": 120, "label": "No"},
]
notes = [
    {"x": 490, "y": 490, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Signals to move off: idle tabs, a client channel never used, low update rate, a proxy that breaks Upgrade."},
    {"x": 490, "y": 510, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Fan-out cost that grows with instances rather than subscribers is the last one."},
]
generate_diagram.emit("27-socket-or-alternative", W, H, bands=bands, nodes=nodes, edges=edges, notes=notes)
