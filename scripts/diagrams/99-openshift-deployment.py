#!/usr/bin/env python3
"""Fig 99.1: the same chart on OpenShift Local: edge-TLS Route to instance
A, AMQ Streams Kafka, in-cluster builds (examples/part4-backplane/openshift)."""
import sys, os
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 1020, 560
bands = [{"x": 200, "y": 20, "w": 800, "h": 520,
          "label": "project part4-backplane: restricted-v2, no fixed UID", "fill": "#fafafa"}]
nodes = [
    {"x": 20, "y": 190, "w": 150, "h": 80, "lines": ["Client", "websocat over wss", "cluster CA verified"], "style": "user"},
    {"x": 20, "y": 320, "w": 160, "h": 90, "lines": ["AMQ Streams", "OperatorHub", "channel amq-streams-3.2.x", "Manual approval"], "style": "sub"},
    {"x": 20, "y": 430, "w": 160, "h": 90, "lines": ["In-cluster builds", "Quarkus: binary S2I", "Python: Docker strategy"], "style": "ghost"},
    {"x": 220, "y": 175, "w": 150, "h": 110, "lines": ["Route", "edge TLS, redirect", "timeout 3600s", "A instances only"], "style": "accent"},
    {"x": 440, "y": 60, "w": 240, "h": 100, "lines": ["Instance A", "quarkus-a:8080", "python-a:8081 ws, 8082 http"], "style": "accent"},
    {"x": 440, "y": 330, "w": 240, "h": 100, "lines": ["Instance B", "quarkus-b:8080", "python-b:8081 ws, 8082 http"], "style": "box"},
    {"x": 750, "y": 60, "w": 235, "h": 100, "lines": ["Kafka part4-backplane", "AMQ Streams, KRaft, 4.2.0", "part4-backplane-kafka-bootstrap:9092"], "style": "ink"},
    {"x": 750, "y": 330, "w": 235, "h": 100, "lines": ["redis", "redis:8.10.2-alpine", "port 6379, same Helm release"], "style": "sub"},
    {"x": 440, "y": 470, "w": 545, "h": 50, "lines": ["ConfigMap backplane-config",
        "BACKPLANE_MODE from the Helm value backplane: kafka | redis"], "style": "ghost"},
]
edges = [
    {"x1": 170, "y1": 230, "x2": 220, "y2": 230, "label": "wss", "amber": True},
    {"x1": 370, "y1": 200, "x2": 440, "y2": 120},
    {"x1": 680, "y1": 110, "x2": 750, "y2": 110, "label": "pub/sub", "amber": True},
    {"x1": 650, "y1": 330, "x2": 800, "y2": 160, "label": "publish"},
    {"x1": 680, "y1": 380, "x2": 750, "y2": 380, "label": "redis mode", "dashed": True},
    {"x1": 560, "y1": 160, "x2": 560, "y2": 330, "label": "oc exec into A, curl B", "dashed": True},
]
generate_diagram.emit("99-openshift-deployment", W, H, bands=bands, nodes=nodes, edges=edges)
