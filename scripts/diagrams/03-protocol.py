#!/usr/bin/env python3
"""Fig 3.1/3.2 — Ch3: the RFC 6455 upgrade handshake as a client/server
sequence, and the anatomy of a single WebSocket frame, annotated with the
real bytes this chapter decodes in "On the wire" (a masked text frame
carrying a handling-event payload)."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 3.1 — the upgrade handshake sequence
# ---------------------------------------------------------------------------
W1, H1 = 860, 500

CLIENT = {"x": 40, "w": 330}
SERVER = {"x": 490, "w": 330}

nodes_1 = [
    {"x": CLIENT["x"], "y": 20, "w": CLIENT["w"], "h": 50,
     "lines": ["Client"], "style": "user"},
    {"x": SERVER["x"], "y": 20, "w": SERVER["w"], "h": 50,
     "lines": ["Server", "GET /handling-events"], "style": "accent"},

    {"x": CLIENT["x"], "y": 110, "w": CLIENT["w"], "h": 130,
     "lines": ["GET /handling-events HTTP/1.1", "Host: fleet.example.com",
               "Upgrade: websocket", "Connection: Upgrade",
               "Sec-WebSocket-Key: dGhlIHNhbXBsZQ==",
               "Sec-WebSocket-Version: 13"],
     "style": "user"},
    {"x": SERVER["x"], "y": 110, "w": SERVER["w"], "h": 130,
     "lines": ["on receipt:", "key + GUID, SHA-1, base64", "= Sec-WebSocket-Accept",
               "(RFC 6455 §1.3 fixed GUID)"],
     "style": "box"},

    {"x": SERVER["x"], "y": 280, "w": SERVER["w"], "h": 110,
     "lines": ["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket",
               "Connection: Upgrade", "Sec-WebSocket-Accept: s3pPLMBiTx..."],
     "style": "accent"},

    {"x": CLIENT["x"], "y": 420, "w": CLIENT["w"], "h": 60,
     "lines": ["same TCP connection,", "now framed as WebSocket"], "style": "ghost"},
    {"x": SERVER["x"], "y": 420, "w": SERVER["w"], "h": 60,
     "lines": ["same TCP connection,", "now framed as WebSocket"], "style": "ghost"},
]

edges_1 = [
    {"x1": CLIENT["x"] + CLIENT["w"], "y1": 160, "x2": SERVER["x"], "y2": 160,
     "label": "one HTTP/1.1 request, Upgrade header"},
    {"x1": SERVER["x"], "y1": 320, "x2": CLIENT["x"] + CLIENT["w"], "y2": 320,
     "label": "101 + matching Accept", "amber": True, "lx": 0, "ly": 14},
    {"x1": CLIENT["x"] + CLIENT["w"], "y1": 450, "x2": SERVER["x"], "y2": 450,
     "label": "frames flow both ways, no new handshake", "dashed": True, "bidir": True},
]

notes_1 = [
    {"x": 430, "y": 485, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "One connection, one handshake: after the 101, client and server frame bytes directly over the same TCP socket."},
]

generate_diagram.emit("03-upgrade-handshake", W1, H1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 3.2 — frame anatomy, with the real captured bytes underneath
# ---------------------------------------------------------------------------
W2, H2 = 860, 400

nodes_2 = [
    {"x": 20, "y": 60, "w": 150, "h": 110,
     "lines": ["Byte 0", "FIN · RSV1-3", "Opcode (4 bits)"], "style": "box"},
    {"x": 190, "y": 60, "w": 150, "h": 110,
     "lines": ["Byte 1", "MASK bit", "Payload len (7 bits)"], "style": "box"},
    {"x": 360, "y": 60, "w": 150, "h": 110,
     "lines": ["Ext. payload len", "0, 2, or 8 bytes", "present if len=126/127"], "style": "ghost"},
    {"x": 530, "y": 60, "w": 140, "h": 110,
     "lines": ["Masking key", "4 bytes", "client frames only"], "style": "accent"},
    {"x": 690, "y": 60, "w": 150, "h": 110,
     "lines": ["Payload data", "0..N bytes", "XOR'd with mask key"], "style": "accent"},

    {"x": 20, "y": 230, "w": 150, "h": 80,
     "lines": ["0x81", "FIN=1, opcode=0x1", "(text frame)"], "style": "ink"},
    {"x": 190, "y": 230, "w": 150, "h": 80,
     "lines": ["0x93", "MASK=1, len=19"], "style": "ink"},
    {"x": 530, "y": 230, "w": 140, "h": 80,
     "lines": ["8a a4 58 27", "mask key"], "style": "ink"},
    {"x": 690, "y": 230, "w": 150, "h": 80,
     "lines": ['unmasks to', '{"event":"ARRIVED"}'], "style": "ink"},
]

edges_2 = [
    {"x1": 95, "y1": 170, "x2": 95, "y2": 230, "dashed": True},
    {"x1": 265, "y1": 170, "x2": 265, "y2": 230, "dashed": True},
    {"x1": 600, "y1": 170, "x2": 600, "y2": 230, "dashed": True},
    {"x1": 765, "y1": 170, "x2": 765, "y2": 230, "dashed": True},
]

notes_2 = [
    {"x": 430, "y": 25, "size": 13, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "RFC 6455 frame format — a client→server frame carrying one handling-event message"},
    {"x": 430, "y": 345, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "Real capture: 81 93 8a a4 58 27 f1 86 3d 51 ef ca 2c 05 b0 86 19 75 d8 ed 0e 62 ce 86 25"},
    {"x": 430, "y": 365, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "No extended length field here: 19 fits in the 7-bit payload-length field, so that box is unused."},
]

generate_diagram.emit("03-frame-anatomy", W2, H2, nodes=nodes_2, edges=edges_2, notes=notes_2)
