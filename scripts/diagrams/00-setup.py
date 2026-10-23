#!/usr/bin/env python3
"""Figures for _docs/00-setup-and-the-lab.md.

Run from the repo root:
    python3 -I scripts/diagrams/00-setup.py
"""
import sys
sys.path.insert(0, "scripts")
import generate_diagram as gd
import os

gd.OUT = "assets/diagrams"
os.makedirs(gd.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 0.1: the Compose lab topology this chapter's examples iteration
# will ship: one contract, two servers, LGTM gated behind a profile.
# ---------------------------------------------------------------------------
gd.emit(
    "00-lab-topology",
    840,
    460,
    bands=[
        {"x": 20, "y": 20, "w": 800, "h": 300, "label": "docker compose (Ch0 lab, forthcoming in examples/)", "fill": "#fafafa"},
        {"x": 20, "y": 340, "w": 800, "h": 100, "label": "docker compose --profile observability (opt-in)", "fill": "#fff3e0"},
    ],
    nodes=[
        {"x": 50, "y": 70, "w": 190, "h": 70, "lines": ["wscat / browser", "dev console"], "style": "user"},
        {"x": 330, "y": 60, "w": 220, "h": 80, "lines": ["quarkus:8080", "WebSockets Next", "/events (upgrade)"], "style": "box"},
        {"x": 330, "y": 170, "w": 220, "h": 80, "lines": ["python:8081", "FastAPI + websockets", "/events (upgrade)"], "style": "box"},
        {"x": 620, "y": 115, "w": 170, "h": 70, "lines": ["contracts/", "asyncapi.yaml", "one channel, one schema"], "style": "accent"},
        {"x": 330, "y": 370, "w": 220, "h": 55, "lines": ["grafana/otel-lgtm:3000", "Loki · Tempo · Mimir"], "style": "ghost"},
    ],
    edges=[
        {"x1": 240, "y1": 95, "x2": 330, "y2": 95, "label": "wss:// upgrade"},
        {"x1": 240, "y1": 120, "x2": 330, "y2": 205, "label": "wss:// upgrade"},
        {"x1": 550, "y1": 90, "x2": 620, "y2": 130, "label": "generated from", "dashed": True},
        {"x1": 550, "y1": 200, "x2": 620, "y2": 160, "label": "generated from", "dashed": True},
        {"x1": 440, "y1": 140, "x2": 440, "y2": 170, "amber": True, "dashed": True, "label": "OTLP, opt-in"},
        {"x1": 440, "y1": 250, "x2": 440, "y2": 370, "amber": True, "dashed": True},
    ],
    notes=[
        {"x": 30, "y": 440, "text": "Two independent implementations, one AsyncAPI contract, reflection-free: the client just opens a socket.", "size": 12, "color": "#555555"},
    ],
)

# ---------------------------------------------------------------------------
# Figure 0.2: the three runtime tiers this site climbs through, in order.
# ---------------------------------------------------------------------------
gd.emit(
    "00-tier-progression",
    840,
    260,
    nodes=[
        {"x": 40, "y": 90, "w": 230, "h": 90, "lines": ["Docker Compose", "this chapter", "fastest inner loop"], "style": "ink"},
        {"x": 320, "y": 90, "w": 230, "h": 90, "lines": ["minikube", "docker driver + containerd", "Ch26"], "style": "box"},
        {"x": 600, "y": 90, "w": 220, "h": 90, "lines": ["OpenShift Local (CRC)", "separate appendix", "Appendix A"], "style": "box"},
    ],
    edges=[
        {"x1": 270, "y1": 135, "x2": 320, "y2": 135, "label": "same contract, same services"},
        {"x1": 550, "y1": 135, "x2": 600, "y2": 135, "label": "same contract, separate track"},
    ],
    notes=[
        {"x": 40, "y": 220, "text": "Every tier runs the identical Quarkus and Python images; only the orchestrator and the ingress path change.", "size": 12, "color": "#555555"},
    ],
)
