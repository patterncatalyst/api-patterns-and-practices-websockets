#!/usr/bin/env python3
"""Fig 12.1/12.2 — Ch12: the server's SERVER-side outbound backpressure
guard (OutboundBackpressureGuard.java / app/outbound.py's bounded
asyncio.Queue) — the bounded buffer with its CLOSE-vs-DROP branches, and a
producer-faster-than-consumer timeline showing where the two detection
signals (buffer full, send() timeout) fire and the 4290 close that follows
under the CLOSE policy."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 12.1 — bounded outbound buffer: CLOSE vs DROP
# ---------------------------------------------------------------------------
W1, H1 = 960, 460

bands_1 = [
    {"x": 20, "y": 20, "w": 920, "h": 420,
     "label": "OutboundBackpressureGuard.java / OutboundQueue in app/outbound.py — decouples the producer from the slow socket write",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 50, "y": 160, "w": 210, "h": 85,
     "lines": ["Producer", "fixture replay / a new", "HandlingEvent is recorded"],
     "style": "accent"},

    {"x": 370, "y": 160, "w": 230, "h": 85,
     "lines": ["BOUNDED OUTBOUND BUFFER", "maxPendingSends / QUEUE_MAXSIZE", "(default 32)"],
     "style": "ink"},

    {"x": 700, "y": 160, "w": 210, "h": 85,
     "lines": ["connection.sendText() /", "websocket.send()", "— the slow client's socket"],
     "style": "user"},

    {"x": 90, "y": 300, "w": 300, "h": 80,
     "lines": ["CLOSE (default)", "close(4290 SLOW_CONSUMER) —", "stop sending, safe default"],
     "style": "box"},

    {"x": 510, "y": 300, "w": 300, "h": 80,
     "lines": ["DROP", "log + skip this event,", "keep the connection open"],
     "style": "box"},
]

edges_1 = [
    {"x1": 260, "y1": 202, "x2": 370, "y2": 202, "label": "enqueue / pending++"},
    {"x1": 600, "y1": 202, "x2": 700, "y2": 202, "label": "sendText / send()"},
    {"x1": 500, "y1": 245, "x2": 260, "y2": 300, "label": "full, or send() > timeout", "dashed": True},
    {"x1": 560, "y1": 245, "x2": 630, "y2": 300, "label": "full, or send() > timeout", "dashed": True},
    {"x1": 240, "y1": 300, "x2": 500, "y2": 202,
     "label": "connection torn down — no more frames", "amber": True, "dashed": True},
    {"x1": 660, "y1": 300, "x2": 700, "y2": 245,
     "label": "next event still enqueued", "amber": True},
]

notes_1 = [
    {"x": 480, "y": 400, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "Two signals trip the policy: the buffer is full (sustained rate mismatch), or one send() hangs past the timeout (peer stopped reading entirely)."},
]

generate_diagram.emit("12-outbound-buffer-policy", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 12.2 — producer-faster-than-consumer timeline
# ---------------------------------------------------------------------------
W2, H2 = 980, 440

bands_2 = [
    {"x": 20, "y": 20, "w": 940, "h": 400,
     "label": "Time flows left to right — the client's TCP receive window fills, then the server's own buffer fills behind it",
     "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 50, "y": 70, "w": 190, "h": 70,
     "lines": ["t0: connection opens", "buffer empty, client draining"],
     "style": "accent"},

    {"x": 280, "y": 70, "w": 190, "h": 70,
     "lines": ["t1: client slows down", "TCP receive window fills"],
     "style": "box"},

    {"x": 510, "y": 70, "w": 190, "h": 70,
     "lines": ["t2: sendText/send()", "stays pending — socket", "write itself blocks"],
     "style": "box"},

    {"x": 740, "y": 70, "w": 200, "h": 70,
     "lines": ["t3: buffer fills OR", "send() exceeds timeout", "— policy trips"],
     "style": "ink"},

    {"x": 740, "y": 220, "w": 200, "h": 80,
     "lines": ["t4 (CLOSE): 4290", "SLOW_CONSUMER —", "remaining events dropped"],
     "style": "user"},

    {"x": 480, "y": 220, "w": 200, "h": 80,
     "lines": ["t4 (DROP): this event", "discarded, buffer keeps", "accepting new ones"],
     "style": "box"},
]

edges_2 = [
    {"x1": 240, "y1": 105, "x2": 280, "y2": 105, "label": "producer keeps enqueueing"},
    {"x1": 470, "y1": 105, "x2": 510, "y2": 105, "label": "pending += 1"},
    {"x1": 700, "y1": 105, "x2": 740, "y2": 105, "label": "threshold crossed"},
    {"x1": 840, "y1": 140, "x2": 840, "y2": 220, "label": "policy = CLOSE", "amber": True},
    {"x1": 790, "y1": 140, "x2": 580, "y2": 220, "label": "policy = DROP", "dashed": True},
]

notes_2 = [
    {"x": 490, "y": 400, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Without a bound, this same timeline just keeps t1-t3 going forever: the buffer grows without limit and the server's own memory is what eventually fails, not the client."},
]

generate_diagram.emit("12-slow-consumer-timeline", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
