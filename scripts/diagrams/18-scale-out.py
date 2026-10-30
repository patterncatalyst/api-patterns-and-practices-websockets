#!/usr/bin/env python3
"""Fig 18.1/18.2: Ch18: the scale-out fan-out problem a sticky load balancer
cannot solve by itself (a client pinned to instance A never sees an event
injected through instance B unless something crosses instances for it), and
the Kafka-vs-Redis contrast behind that crossing (DRQ-005). See
examples/part4-backplane/PROTOCOL.md "Backplane modes" and
examples/part4-backplane/verify.sh's Ch18 stages B/C."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 18.1: sticky sessions alone vs. the backplane closing the gap
# ---------------------------------------------------------------------------
W1, H1 = 980, 560

bands_1 = [
    {"x": 20, "y": 20, "w": 940, "h": 520,
     "label": "Client pinned to instance A by the load balancer's sticky session: the event is injected at instance B",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 40, "y": 60, "w": 230, "h": 70,
     "lines": ["CLIENT", "ws_connect_bg -> instance A", "sticky session"],
     "style": "user"},

    {"x": 40, "y": 170, "w": 230, "h": 70,
     "lines": ["Instance A", "quarkus-a:8080 / python-a:8081"],
     "style": "accent"},

    {"x": 700, "y": 60, "w": 240, "h": 70,
     "lines": ["TEST HARNESS", "POST inject -> instance B"],
     "style": "user"},

    {"x": 700, "y": 170, "w": 240, "h": 70,
     "lines": ["Instance B", "quarkus-b:8083 / python-b:8084"],
     "style": "box"},

    {"x": 320, "y": 280, "w": 340, "h": 70,
     "lines": ["NO BACKPLANE (stateless)", "A's local subscribers only, B's event never crosses"],
     "style": "ghost"},

    {"x": 240, "y": 400, "w": 500, "h": 90,
     "lines": ["BACKPLANE",
               "Kafka topic handling-events, per-instance consumer group (fan-out, not load-balanced)",
               "Redis channel handling-events:{bookingId}, pub/sub"],
     "style": "ink"},
]

edges_1 = [
    {"x1": 155, "y1": 130, "x2": 155, "y2": 170, "label": "connect; stays open"},
    {"x1": 820, "y1": 130, "x2": 820, "y2": 170, "label": "202 Accepted"},
    {"x1": 270, "y1": 205, "x2": 320, "y2": 300, "label": "dropped, same-instance only", "dashed": True},
    {"x1": 700, "y1": 205, "x2": 660, "y2": 300, "label": "publish() has nowhere local to go", "dashed": True},
    {"x1": 270, "y1": 240, "x2": 300, "y2": 400, "label": "subscribe/consume", "amber": True},
    {"x1": 700, "y1": 240, "x2": 650, "y2": 400, "label": "publish"},
]

notes_1 = [
    {"x": 490, "y": 535, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "Sticky sessions keep a client on ONE instance. They say nothing about where an event is produced. Only a shared backplane crosses that gap."},
]

generate_diagram.emit("18-sticky-vs-backplane", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 18.2: Kafka vs Redis backplane contrast (DRQ-005)
# ---------------------------------------------------------------------------
W2, H2 = 980, 460

bands_2 = [
    {"x": 20, "y": 20, "w": 940, "h": 420,
     "label": "Same fan-out outcome, different trade-off, no single winner",
     "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 50, "y": 65, "w": 400, "h": 55,
     "lines": ["KAFKA: durability + replay"],
     "style": "accent"},

    {"x": 530, "y": 65, "w": 400, "h": 55,
     "lines": ["REDIS: simplicity + latency"],
     "style": "user"},

    {"x": 50, "y": 140, "w": 400, "h": 75,
     "lines": ["Topic handling-events, keyed by bookingId", "per-instance consumer group = fan-out to every instance"],
     "style": "box"},

    {"x": 530, "y": 140, "w": 400, "h": 75,
     "lines": ["Channel handling-events:{bookingId}", "pub/sub: every subscriber gets every publish"],
     "style": "box"},

    {"x": 50, "y": 235, "w": 400, "h": 70,
     "lines": ["Durable: retained on disk, replayable", "powers the afterEventId resume too"],
     "style": "ink"},

    {"x": 530, "y": 235, "w": 400, "h": 70,
     "lines": ["Live only: no history, no replay", "afterEventId behaves as stateless"],
     "style": "ink"},

    {"x": 50, "y": 325, "w": 400, "h": 70,
     "lines": ["Cost: topic/partition/offset bookkeeping,", "a consumer per instance per booking"],
     "style": "box"},

    {"x": 530, "y": 325, "w": 400, "h": 70,
     "lines": ["Cost: a dropped subscriber loses in-flight", "messages, nothing to catch it back up"],
     "style": "box"},
]

edges_2 = [
    {"x1": 450, "y1": 92, "x2": 530, "y2": 92, "label": "contrasted, not ranked", "amber": True},
]

notes_2 = [
    {"x": 490, "y": 425, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "verify.sh proves the SAME cross-instance delivery on both brokers, for both stacks: the trade-off is durability/replay vs. operational surface, not correctness."},
]

generate_diagram.emit("18-kafka-vs-redis", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
