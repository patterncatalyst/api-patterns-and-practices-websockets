#!/usr/bin/env python3
"""Fig 16.1/16.2: Ch16: the Kafka-backed answer to Ch15's stateless gap.
16.1 mirrors Ch15's reconnect timeline layout row-for-row but contrasts the
two outcomes directly: stateless loses the gap-era event (PROTOCOL.md
"Resume parameter": afterEventId ignored), kafka replays it exactly once
after reconnect. 16.2 is the topic/offset/resume model underneath that:
the seed-direct path that never touches Kafka, the inject-to-topic path
keyed by bookingId, subscribe's found/not-found replay-after logic
(KafkaBackplane.replayFor / kafka_backplane.py's subscribe), and retention
as the hard bound on how far back a replay can reach."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 16.1: the gap: lost (Ch15) vs. filled by replay (Ch16)
# ---------------------------------------------------------------------------
W1, H1 = 1000, 480

bands_1 = [
    {"x": 20, "y": 20, "w": 960, "h": 200,
     "label": "Ch15 stateless (default profile) -- PROTOCOL.md \"Resume parameter\": afterEventId is ignored",
     "fill": "#fafafa"},
    {"x": 20, "y": 240, "w": 960, "h": 200,
     "label": "Ch16 kafka (--profile kafka) -- the same topic the client never sees answers the gap",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 40, "y": 80, "w": 160, "h": 90, "style": "accent",
     "lines": ["CONNECTED", "3 seed events", "(feed.py, direct)"]},
    {"x": 230, "y": 80, "w": 160, "h": 90, "style": "box",
     "lines": ["DISCONNECT", "client drops"]},
    {"x": 420, "y": 80, "w": 190, "h": 90, "style": "ghost",
     "lines": ["gap event injected", "POST .../handling-events", "no broker -- nothing stores it"]},
    {"x": 640, "y": 80, "w": 160, "h": 90, "style": "box",
     "lines": ["RECONNECT", "?afterEventId=", "<last seed eventId>"]},
    {"x": 830, "y": 80, "w": 140, "h": 90, "style": "ghost",
     "lines": ["LOST", "never arrives"]},

    {"x": 40, "y": 300, "w": 160, "h": 90, "style": "accent",
     "lines": ["CONNECTED", "3 seed events", "(feed.py, same as Ch15)"]},
    {"x": 230, "y": 300, "w": 160, "h": 90, "style": "box",
     "lines": ["DISCONNECT", "client drops"]},
    {"x": 420, "y": 300, "w": 190, "h": 90, "style": "ink",
     "lines": ["gap event PUBLISHED", "handling-events topic,", "keyed by bookingId"]},
    {"x": 640, "y": 300, "w": 160, "h": 90, "style": "box",
     "lines": ["RECONNECT", "?afterEventId=", "<last seed eventId>"]},
    {"x": 830, "y": 300, "w": 140, "h": 90, "style": "accent",
     "lines": ["FILLED", "replayed once --", "dedup by eventId"]},
]

edges_1 = [
    {"x1": 200, "y1": 125, "x2": 230, "y2": 125, "label": "disconnect"},
    {"x1": 390, "y1": 125, "x2": 420, "y2": 125, "label": "while disconnected"},
    {"x1": 610, "y1": 125, "x2": 640, "y2": 125, "label": "client retries"},
    {"x1": 800, "y1": 125, "x2": 830, "y2": 125,
     "label": "afterEventId ignored -- live tail only", "dashed": True},

    {"x1": 200, "y1": 345, "x2": 230, "y2": 345, "label": "disconnect"},
    {"x1": 390, "y1": 345, "x2": 420, "y2": 345, "label": "durable -- survives the gap"},
    {"x1": 610, "y1": 345, "x2": 640, "y2": 345, "label": "client retries"},
    {"x1": 800, "y1": 345, "x2": 830, "y2": 345,
     "label": "not found (seed id) -> replay everything in topic", "amber": True},
]

notes_1 = [
    {"x": 500, "y": 465, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Same request on both rows -- ?afterEventId=<last seen eventId>. The only difference is whether anything durable sits behind the socket to answer it."},
]

generate_diagram.emit("16-gap-filled-by-replay", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 16.2 -- the topic/offset/resume model
# ---------------------------------------------------------------------------
W2, H2 = 1000, 460

bands_2 = [
    {"x": 20, "y": 20, "w": 960, "h": 420,
     "label": "KafkaBackplane.java / kafka_backplane.py -- seed-direct vs. injected-to-topic, kept strictly separate",
     "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 300, "y": 55, "w": 260, "h": 80, "style": "ghost",
     "lines": ["older than retention", "gone -- cannot be replayed"]},

    {"x": 40, "y": 170, "w": 220, "h": 95, "style": "user",
     "lines": ["Seed feed (direct)", "3 fixture events, every connection,", "every mode -- never through Kafka"]},

    {"x": 40, "y": 320, "w": 220, "h": 95, "style": "user",
     "lines": ["Inject endpoint", "POST /internal/.../handling-events", "injected events only"]},

    {"x": 330, "y": 230, "w": 260, "h": 120, "style": "ink",
     "lines": ["Kafka topic: handling-events", "keyed by bookingId, 1 partition",
               "retention is the hard bound on replay"]},

    {"x": 650, "y": 170, "w": 230, "h": 110, "style": "accent",
     "lines": ["subscribe / replayFor", "found -> replay suffix after it",
               "not found -> replay everything"]},

    {"x": 650, "y": 330, "w": 230, "h": 95, "style": "user",
     "lines": ["Client", "dedups by eventId -> exactly once"]},
]

edges_2 = [
    {"x1": 260, "y1": 217, "x2": 650, "y2": 377,
     "label": "always delivered directly, never via Kafka"},
    {"x1": 260, "y1": 367, "x2": 330, "y2": 320, "label": "publish(bookingId, event) -- keyed"},
    {"x1": 590, "y1": 290, "x2": 650, "y2": 240, "label": "replay-after / live tail"},
    {"x1": 460, "y1": 230, "x2": 420, "y2": 135, "label": "retention window", "dashed": True},
    {"x1": 765, "y1": 280, "x2": 765, "y2": 330,
     "label": "gap-era events, then live -- replay-vs-live can double-deliver; client dedups", "amber": True},
]

notes_2 = [
    {"x": 500, "y": 445, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "The seed never reaches the topic, so afterEventId naming a seed id always misses the search and falls back to replaying everything currently in the topic (PROTOCOL.md \"Resume parameter\")."},
]

generate_diagram.emit("16-topic-offset-resume", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
