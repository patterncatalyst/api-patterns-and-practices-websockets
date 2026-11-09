#!/usr/bin/env python3
"""Fig 26.1: the minikube deployment: ingress to instance A, instance B
internal, Strimzi Kafka or Redis backplane (examples/part4-backplane/k8s)."""
import sys, os
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
os.makedirs(generate_diagram.OUT, exist_ok=True)

W, H = 1000, 560
bands = [{"x": 190, "y": 20, "w": 790, "h": 520, "label": "namespace part4-backplane", "fill": "#fafafa"}]
nodes = [
    {"x": 20, "y": 200, "w": 140, "h": 80, "lines": ["Client", "websocat", "nip.io host name"], "style": "user"},
    {"x": 20, "y": 380, "w": 150, "h": 80, "lines": ["Images", "minikube image load", "imagePullPolicy: Never"], "style": "ghost"},
    {"x": 210, "y": 190, "w": 150, "h": 100, "lines": ["Ingress", "ingress-nginx", "timeouts 3600s", "cookie affinity"], "style": "accent"},
    {"x": 430, "y": 60, "w": 240, "h": 100, "lines": ["Instance A", "quarkus-a:8080", "python-a:8081 ws, 8082 http"], "style": "accent"},
    {"x": 430, "y": 330, "w": 240, "h": 100, "lines": ["Instance B", "quarkus-b:8080", "python-b:8081 ws, 8082 http"], "style": "box"},
    {"x": 740, "y": 60, "w": 220, "h": 100, "lines": ["Kafka my-cluster", "Strimzi, single-node KRaft", "my-cluster-kafka-bootstrap:9092"], "style": "ink"},
    {"x": 740, "y": 330, "w": 220, "h": 100, "lines": ["redis", "Service on port 6379", "toggle: redis-mode component"], "style": "sub"},
    {"x": 430, "y": 470, "w": 530, "h": 50, "lines": ["ConfigMap backplane-config",
        "BACKPLANE_MODE kafka | redis, KAFKA_BOOTSTRAP_SERVERS, REDIS_URL"], "style": "ghost"},
]
edges = [
    {"x1": 160, "y1": 240, "x2": 210, "y2": 240, "label": "wss", "amber": True},
    {"x1": 360, "y1": 210, "x2": 430, "y2": 120, "label": "rules for A only", "lx": -20, "ly": 10},
    {"x1": 670, "y1": 110, "x2": 740, "y2": 110, "label": "pub/sub", "amber": True},
    {"x1": 640, "y1": 330, "x2": 790, "y2": 160, "label": "publish"},
    {"x1": 670, "y1": 380, "x2": 740, "y2": 380, "label": "redis mode", "dashed": True},
    {"x1": 550, "y1": 160, "x2": 550, "y2": 330, "label": "kubectl exec into A, curl B", "dashed": True},
]
notes = [
    {"x": 285, "y": 330, "size": 12, "color": "#555555", "anchor": "middle", "text": "B has a Service but no"},
    {"x": 285, "y": 348, "size": 12, "color": "#555555", "anchor": "middle", "text": "Ingress rule: internal only"},
]
generate_diagram.emit("26-minikube-deployment", W, H, bands=bands, nodes=nodes, edges=edges, notes=notes)
