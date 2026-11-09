#!/usr/bin/env python3
"""Fig 28.1: the final project: one contract and fixture, one channel,
six layered concerns on both stacks, two deploy targets."""
import sys, os
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 1000, 600
bands = [
    {"x": 280, "y": 20, "w": 440, "h": 370, "label": "handlingEvents channel, Quarkus and Python stacks", "fill": "#fafafa"},
    {"x": 20, "y": 410, "w": 620, "h": 170, "label": "Deploy", "fill": "#fafafa"},
]
def layer(y, title, detail):
    return {"x": 300, "y": y, "w": 400, "h": 50, "lines": [title, detail], "style": "box"}
nodes = [
    {"x": 20, "y": 70, "w": 220, "h": 80, "lines": ["Contract", "asyncapi.yaml", "handling-event.proto"], "style": "accent"},
    {"x": 20, "y": 200, "w": 220, "h": 70, "lines": ["Fixture", "RECEIVE, LOAD, CUSTOMS"], "style": "box"},
    layer(60, "Connection", "JWT at upgrade, close codes 1008 and 4400"),
    layer(122, "Send path", "backpressure 4290, heartbeat sweep"),
    layer(184, "Encoding", "Sec-WebSocket-Protocol: JSON or Protobuf"),
    layer(246, "Backplane", "stateless | kafka | redis, ?afterEventId replay"),
    layer(308, "Observability", "connection span, delivered-events counter"),
    {"x": 770, "y": 100, "w": 200, "h": 90, "lines": ["Client", "wss, ?token=", "offers a subprotocol"], "style": "user"},
    {"x": 770, "y": 240, "w": 200, "h": 90, "lines": ["Inject endpoint", "POST /internal/bookings/", "{bookingId}/handling-events"], "style": "sub"},
    {"x": 50, "y": 450, "w": 270, "h": 90, "lines": ["minikube", "ingress-nginx, Strimzi Kafka", "Redis toggle"], "style": "ink"},
    {"x": 340, "y": 450, "w": 270, "h": 90, "lines": ["OpenShift Local", "Routes, AMQ Streams Kafka", "Redis toggle"], "style": "ink"},
    {"x": 700, "y": 450, "w": 270, "h": 90, "lines": ["lgtm", "Grafana stack", "traces and metrics"], "style": "sub"},
]
edges = [
    {"x1": 240, "y1": 110, "x2": 280, "y2": 110, "label": "types"},
    {"x1": 240, "y1": 235, "x2": 280, "y2": 235, "label": "seed"},
    {"x1": 720, "y1": 145, "x2": 770, "y2": 145, "label": "frames", "bidir": True, "amber": True},
    {"x1": 770, "y1": 285, "x2": 720, "y2": 285, "label": "inject"},
    {"x1": 330, "y1": 390, "x2": 330, "y2": 410, "label": "runs on"},
    {"x1": 700, "y1": 333, "x2": 835, "y2": 450, "label": "OTLP", "lx": -25, "ly": 10},
]
generate_diagram.emit("28-final-project-system", W, H, bands=bands, nodes=nodes, edges=edges)
