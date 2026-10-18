#!/usr/bin/env python3
"""Figures for Chapter 1 — The Real-Time Problem.

Run from repo root:
    python3 -I scripts/diagrams/01-realtime.py
"""
import sys, os
sys.path.insert(0, "scripts")
import generate_diagram as gd

gd.OUT = "assets/diagrams"
os.makedirs(gd.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 1.1 — Poll loop vs. push: the same booking, two delivery models.
# ---------------------------------------------------------------------------
gd.emit(
    "01-poll-vs-push",
    820, 460,
    bands=[
        {"x": 20, "y": 30, "w": 360, "h": 400, "label": "Pull: client polls the booking service", "fill": "#fafafa"},
        {"x": 440, "y": 30, "w": 360, "h": 400, "label": "Push: client holds a socket open", "fill": "#fff3e0"},
    ],
    nodes=[
        {"x": 60, "y": 70, "w": 140, "h": 50, "lines": ["Client", "watching BKG-4471"], "style": "user"},
        {"x": 240, "y": 70, "w": 140, "h": 50, "lines": ["Booking service", "REST, resource BKG-4471"], "style": "box"},
        {"x": 60, "y": 150, "w": 320, "h": 36, "lines": ["GET /bookings/4471 → 200, status unchanged"], "style": "ghost"},
        {"x": 60, "y": 196, "w": 320, "h": 36, "lines": ["GET /bookings/4471 → 200, status unchanged"], "style": "ghost"},
        {"x": 60, "y": 242, "w": 320, "h": 36, "lines": ["GET /bookings/4471 → 200, status unchanged"], "style": "ghost"},
        {"x": 60, "y": 288, "w": 320, "h": 36, "lines": ["GET /bookings/4471 → 200, CUSTOMS_HOLD"], "style": "accent"},
        {"x": 60, "y": 350, "w": 320, "h": 50, "lines": ["One real change", "found 0-30s after it happened"], "style": "ink"},

        {"x": 480, "y": 70, "w": 140, "h": 50, "lines": ["Client", "watching BKG-4471"], "style": "user"},
        {"x": 660, "y": 70, "w": 140, "h": 50, "lines": ["Handling-event feed", "one open socket"], "style": "box"},
        {"x": 480, "y": 150, "w": 320, "h": 36, "lines": ["connection open, no traffic"], "style": "ghost"},
        {"x": 480, "y": 196, "w": 320, "h": 50, "lines": ["pushed: GATE_IN, USNYC", "the instant the event is recorded"], "style": "accent"},
        {"x": 480, "y": 258, "w": 320, "h": 50, "lines": ["pushed: CUSTOMS_HOLD, USNYC", "the instant the event is recorded"], "style": "accent"},
        {"x": 480, "y": 320, "w": 320, "h": 50, "lines": ["Every change seen", "within one network hop, no gap"], "style": "ink"},
    ],
    edges=[
        {"x1": 200, "y1": 95, "x2": 240, "y2": 95},
        {"x1": 640, "y1": 95, "x2": 600, "y2": 95, "label": "upgrade once"},
    ],
)

# ---------------------------------------------------------------------------
# Figure 1.2 — The cost of polling, visualized as wasted requests.
# ---------------------------------------------------------------------------
gd.emit(
    "01-polling-cost",
    820, 340,
    bands=[
        {"x": 20, "y": 20, "w": 780, "h": 300, "label": "1 booking, watched for 10 minutes, one status change at minute 7", "fill": "#fafafa"},
    ],
    nodes=[
        {"x": 60, "y": 70, "w": 90, "h": 44, "lines": ["poll", "2s interval"], "style": "sub"},
        {"x": 170, "y": 70, "w": 90, "h": 44, "lines": ["poll", "unchanged"], "style": "ghost"},
        {"x": 280, "y": 70, "w": 90, "h": 44, "lines": ["poll", "unchanged"], "style": "ghost"},
        {"x": 390, "y": 70, "w": 90, "h": 44, "lines": ["poll", "unchanged"], "style": "ghost"},
        {"x": 500, "y": 70, "w": 90, "h": 44, "lines": ["…296 more", "unchanged"], "style": "ghost"},
        {"x": 630, "y": 70, "w": 150, "h": 44, "lines": ["1 poll", "catches the change"], "style": "accent"},

        {"x": 60, "y": 150, "w": 720, "h": 70, "lines": [
            "300 requests sent to watch one booking for 10 minutes",
            "299 return a body identical to the one before it — 0 new information, full request/response cost",
        ], "style": "ink"},

        {"x": 60, "y": 250, "w": 340, "h": 60, "lines": [
            "1,000 clients, same interval",
            "300,000 requests/10 min for 1,000 events total",
        ], "style": "box"},
        {"x": 420, "y": 250, "w": 360, "h": 60, "lines": [
            "Push equivalent",
            "1,000 open sockets, 1,000 messages sent total",
        ], "style": "accent"},
    ],
    edges=[
        {"x1": 150, "y1": 92, "x2": 170, "y2": 92},
        {"x1": 260, "y1": 92, "x2": 280, "y2": 92},
        {"x1": 370, "y1": 92, "x2": 390, "y2": 92},
        {"x1": 480, "y1": 92, "x2": 500, "y2": 92},
        {"x1": 590, "y1": 92, "x2": 630, "y2": 92, "amber": True},
    ],
)
