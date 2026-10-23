#!/usr/bin/env python3
"""Fig 8.1/8.2: Ch8: the @WebSocket endpoint's connection lifecycle
callbacks on HandlingEventWebSocket, and the Multi server-push flow that
replays HandlingEventFeed's fixture as JSON text frames."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 8.1: the @WebSocket endpoint and its connection lifecycle
# ---------------------------------------------------------------------------
W1, H1 = 860, 420

bands_1 = [
    {"x": 20, "y": 50, "w": 820, "h": 340,
     "label": "HandlingEventWebSocket: @WebSocket(path = \"/ws/v1/bookings/{bookingId}/handling-events\")",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 50, "y": 100, "w": 230, "h": 90, "style": "accent",
     "lines": ["@OnOpen", "onOpen(@PathParam bookingId)",
               "this chapter's example", "returns Multi<HandlingEvent>"]},
    {"x": 315, "y": 100, "w": 230, "h": 90, "style": "ghost",
     "lines": ["@OnTextMessage", "not declared here",
               "channel is receive-only", "(contracts/asyncapi.yaml)"]},
    {"x": 580, "y": 100, "w": 230, "h": 90, "style": "box",
     "lines": ["@OnClose", "not declared here",
               "nothing to release", "no per-connection state kept"]},

    {"x": 50, "y": 240, "w": 230, "h": 110, "style": "sub",
     "lines": ["WebSocketConnection", "imperative sendText(...)",
               "available for ad hoc pushes;", "not used by this handler"]},
    {"x": 315, "y": 240, "w": 230, "h": 110, "style": "accent",
     "lines": ["HandlingEventFeed", "@ApplicationScoped, @PostConstruct",
               "loads fixtures/handling-events.json", "once, at startup"]},
    {"x": 580, "y": 240, "w": 230, "h": 110, "style": "user",
     "lines": ["Jackson ObjectMapper", "pulled in transitively by",
               "quarkus-websockets-next", "serializes HandlingEvent -> JSON"]},
]

edges_1 = [
    {"x1": 165, "y1": 190, "x2": 165, "y2": 240, "label": "could call"},
    {"x1": 430, "y1": 190, "x2": 430, "y2": 240, "dashed": True},
    {"x1": 165, "y1": 240, "x2": 430, "y2": 190, "dashed": True, "label": "feed.events()"},
    {"x1": 430, "y1": 240, "x2": 165, "y2": 190, "amber": True, "label": "Multi<HandlingEvent>"},
]

notes_1 = [
    {"x": 430, "y": 30, "size": 13, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "One lifecycle callback runs for this endpoint, @OnOpen, because the contract declares no inbound operation"},
    {"x": 430, "y": 405, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "@PathParam bookingId binds the {bookingId} template segment; the handler never touches WebSocketConnection directly"},
]

generate_diagram.emit("08-ws-endpoint-lifecycle", W1, H1, nodes=nodes_1, edges=edges_1, bands=bands_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 8.2: the Multi server-push flow for one connection
# ---------------------------------------------------------------------------
W2, H2 = 860, 380

nodes_2 = [
    {"x": 30, "y": 50, "w": 190, "h": 70, "style": "user",
     "lines": ["Client", "opens WebSocket", "to /ws/v1/bookings/{id}/..."]},
    {"x": 280, "y": 50, "w": 230, "h": 70, "style": "accent",
     "lines": ["@OnOpen onOpen()", "returns",
               "Multi.createFrom().iterable(feed.events())"]},
    {"x": 580, "y": 50, "w": 250, "h": 70, "style": "box",
     "lines": ["WebSockets Next runtime", "subscribes to the Multi,",
               "drives emission onto the connection"]},

    {"x": 280, "y": 180, "w": 150, "h": 50, "style": "ghost", "lines": ["RECEIVE", "USNYC"]},
    {"x": 450, "y": 180, "w": 150, "h": 50, "style": "ghost", "lines": ["LOAD", "USNYC"]},
    {"x": 620, "y": 180, "w": 150, "h": 50, "style": "ghost", "lines": ["CUSTOMS", "NLRTM"]},

    {"x": 30, "y": 280, "w": 230, "h": 70, "style": "user",
     "lines": ["Client", "receives 3 text frames,", "in fixture order"]},
    {"x": 580, "y": 280, "w": 250, "h": 70, "style": "sub",
     "lines": ["Multi completes", "after the 3rd item",
               "connection stays open"]},
]

edges_2 = [
    {"x1": 220, "y1": 85, "x2": 280, "y2": 85, "label": "upgrade"},
    {"x1": 510, "y1": 85, "x2": 580, "y2": 85, "label": "subscribe"},
    {"x1": 355, "y1": 120, "x2": 355, "y2": 180, "amber": True, "label": "item 1"},
    {"x1": 525, "y1": 120, "x2": 525, "y2": 180, "amber": True, "label": "item 2"},
    {"x1": 695, "y1": 120, "x2": 695, "y2": 180, "amber": True, "label": "item 3"},
    {"x1": 355, "y1": 230, "x2": 145, "y2": 280, "label": "text frame"},
    {"x1": 525, "y1": 230, "x2": 180, "y2": 280, "dashed": True},
    {"x1": 695, "y1": 230, "x2": 695, "y2": 280, "label": "onComplete"},
]

notes_2 = [
    {"x": 430, "y": 25, "size": 13, "color": "#1d1d1d", "anchor": "middle", "bold": True,
     "text": "Each Multi item becomes one JSON text frame, sent in emission order, over the one connection @OnOpen returned it for"},
    {"x": 430, "y": 365, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "Nothing closes the socket when the Multi completes: only the TCP/WebSocket close (not shown) ends the connection"},
]

generate_diagram.emit("08-multi-push-flow", W2, H2, nodes=nodes_2, edges=edges_2, notes=notes_2)
