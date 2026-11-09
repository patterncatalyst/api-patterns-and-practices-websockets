#!/usr/bin/env python3
"""Fig 25.1: the part4-backplane compose services, ports, profiles and the
healthcheck-gated depends_on (examples/part4-backplane/compose.yaml)."""
import sys, os
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 980, 520
bands = [{"x": 20, "y": 20, "w": 940, "h": 480,
          "label": "Compose default network: services reach each other by service name", "fill": "#fafafa"}]
nodes = [
    {"x": 40, "y": 70, "w": 215, "h": 80, "lines": ["quarkus-a", "8080 -> 8080", "INSTANCE_ID=quarkus-a"], "style": "accent"},
    {"x": 275, "y": 70, "w": 215, "h": 80, "lines": ["quarkus-b", "8083 -> 8080", "INSTANCE_ID=quarkus-b"], "style": "box"},
    {"x": 510, "y": 70, "w": 215, "h": 80, "lines": ["python-a", "8081 -> 8081 ws", "8082 -> 8082 health"], "style": "accent"},
    {"x": 745, "y": 70, "w": 195, "h": 80, "lines": ["python-b", "8084 -> 8081 ws", "8085 -> 8082 health"], "style": "box"},
    {"x": 40, "y": 200, "w": 900, "h": 50,
     "lines": ["depends_on: condition service_healthy, required: false",
               "an absent profile is skipped, not an error"], "style": "ghost"},
    {"x": 80, "y": 300, "w": 260, "h": 90, "lines": ["kafka", "apache/kafka:4.3.1, KRaft", "profile kafka, port 9092"], "style": "ink"},
    {"x": 380, "y": 300, "w": 260, "h": 90, "lines": ["redis", "redis:8.10.2-alpine", "profile redis, port 6379"], "style": "ink"},
    {"x": 680, "y": 300, "w": 260, "h": 100, "lines": ["lgtm", "grafana/otel-lgtm:0.36.0", "profile observability", "ports 3000, 4317, 4318"], "style": "sub"},
]
edges = [
    {"x1": 147, "y1": 150, "x2": 147, "y2": 200},
    {"x1": 382, "y1": 150, "x2": 382, "y2": 200},
    {"x1": 617, "y1": 150, "x2": 617, "y2": 200},
    {"x1": 842, "y1": 150, "x2": 842, "y2": 200},
    {"x1": 210, "y1": 250, "x2": 210, "y2": 300, "label": "--profile kafka", "amber": True},
    {"x1": 510, "y1": 250, "x2": 510, "y2": 300, "label": "--profile redis", "amber": True},
]
notes = [
    {"x": 490, "y": 440, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "No profile: only the four app services start."},
    {"x": 490, "y": 465, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "The profile picks which containers run; BACKPLANE_MODE picks which Backplane an instance wires up."},
]
generate_diagram.emit("25-compose-topology", W, H, bands=bands, nodes=nodes, edges=edges, notes=notes)
