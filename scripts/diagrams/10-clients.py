#!/usr/bin/env python3
"""Fig 10.1/10.2: Ch10: the consuming client's reconnect state machine
(ReconnectingClient.java / client.py's _reconnect_loop: exponential backoff
+ jitter, a fresh connector per attempt) and the bounded-buffer backpressure
flow between the socket and a slow consumer (EventBuffer.java / the
asyncio.Queue in client.py: BLOCK vs DROP_OLDEST)."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 10.1: reconnect backoff state machine
# ---------------------------------------------------------------------------
W1, H1 = 900, 460

bands_1 = [
    {"x": 20, "y": 20, "w": 860, "h": 420,
     "label": "ReconnectingClient.java / client.py _reconnect_loop: one attempt counter, reset only on success",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 330, "y": 55, "w": 240, "h": 75,
     "lines": ["CONNECTED", "attempt = 0", "onOpen() / async with connect()"],
     "style": "accent"},

    {"x": 60, "y": 190, "w": 240, "h": 85,
     "lines": ["DISCONNECTED", "clean close, OnError,", "or failed upgrade"],
     "style": "box"},

    {"x": 60, "y": 330, "w": 240, "h": 90,
     "lines": ["BACKOFF", "delay = min(max, base*2^n)", "+/- jitter_ratio, then sleep"],
     "style": "ink"},

    {"x": 600, "y": 330, "w": 240, "h": 90,
     "lines": ["RETRY ATTEMPT", "fresh WebSocketConnector /", "connect() per attempt"],
     "style": "user"},
]

edges_1 = [
    {"x1": 380, "y1": 130, "x2": 220, "y2": 190,
     "label": "disconnect: any cause counts the same"},
    {"x1": 180, "y1": 275, "x2": 180, "y2": 330, "label": "attempt += 1, schedule"},
    {"x1": 300, "y1": 390, "x2": 600, "y2": 390, "label": "delay elapses"},
    {"x1": 650, "y1": 330, "x2": 450, "y2": 130,
     "label": "success: attempt reset to 0", "amber": True},
    {"x1": 790, "y1": 330, "x2": 300, "y2": 230,
     "label": "fails again: same broad catch", "dashed": True},
]

notes_1 = [
    {"x": 450, "y": 440, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "Jitter spreads reconnecting clients across time so a server restart doesn't get hit by a synchronized thundering herd."},
]

generate_diagram.emit("10-reconnect-backoff", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 10.2: bounded-buffer backpressure: BLOCK vs DROP_OLDEST
# ---------------------------------------------------------------------------
W2, H2 = 940, 420

bands_2 = [
    {"x": 20, "y": 20, "w": 900, "h": 380,
     "label": "EventBuffer.java / asyncio.Queue in client.py: decouples socket read rate from consumer rate",
     "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 50, "y": 160, "w": 210, "h": 85,
     "lines": ["WebSocket read loop", "onMessage() / async for", "message in ws"],
     "style": "accent"},

    {"x": 360, "y": 160, "w": 220, "h": 85,
     "lines": ["BOUNDED QUEUE", "capacity = CLIENT_BUFFER_CAPACITY", "(default 16)"],
     "style": "ink"},

    {"x": 680, "y": 160, "w": 210, "h": 85,
     "lines": ["Consumer task/thread", "process(message)", "consumer.delay-ms sleep"],
     "style": "user"},

    {"x": 90, "y": 300, "w": 290, "h": 70,
     "lines": ["BLOCK (default)", "queue.put() awaits room", "no frame lost, producer throttles"],
     "style": "box"},

    {"x": 480, "y": 300, "w": 290, "h": 70,
     "lines": ["DROP_OLDEST", "evict oldest, log warning,", "enqueue newest: never blocks"],
     "style": "box"},
]

edges_2 = [
    {"x1": 260, "y1": 202, "x2": 360, "y2": 202, "label": "enqueue / offer"},
    {"x1": 580, "y1": 202, "x2": 680, "y2": 202, "label": "dequeue / take"},
    {"x1": 440, "y1": 245, "x2": 235, "y2": 300, "label": "queue full?", "dashed": True},
    {"x1": 470, "y1": 245, "x2": 625, "y2": 300, "label": "queue full?", "dashed": True},
    {"x1": 160, "y1": 300, "x2": 155, "y2": 245,
     "label": "blocks producer coroutine/thread", "amber": True, "dashed": True},
    {"x1": 625, "y1": 300, "x2": 480, "y2": 245,
     "label": "evict + enqueue newest", "amber": True, "dashed": True},
]

notes_2 = [
    {"x": 470, "y": 400, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Neither policy is \"correct\" in the abstract: it is a per-integration trade-off exposed as CLIENT_BUFFER_POLICY / client.buffer.policy, not hardcoded."},
]

generate_diagram.emit("10-backpressure-policy", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
