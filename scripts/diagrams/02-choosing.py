#!/usr/bin/env python3
"""Figures for Chapter 2 — Choosing the Right Tool.

02-transport-decision : the decision tree that routes an interaction to one
                         of the five transports (or to plain request/response).
02-duplex-comparison  : five bands, one per transport, showing who may send
                         and when — the duplex/direction dimension made visual.
"""
import sys, os
sys.path.insert(0, "scripts")
import generate_diagram as gd

gd.OUT = "assets/diagrams"
os.makedirs(gd.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 2.1 — decision tree
# ---------------------------------------------------------------------------
gd.emit(
    "02-transport-decision", 900, 480,
    nodes=[
        {"x":350,"y":16,"w":200,"h":52,"lines":["Need live updates","at all?"],"style":"accent"},
        {"x":20,"y":118,"w":230,"h":56,"lines":["Plain request/response","ask again when you need to"],"style":"ghost"},
        {"x":345,"y":118,"w":230,"h":52,"lines":["Who needs to send —","one side or both?"],"style":"accent"},
        {"x":640,"y":208,"w":210,"h":58,"lines":["WebSocket","full duplex, one connection"],"style":"ink"},
        {"x":225,"y":208,"w":250,"h":52,"lines":["Receiver is a browser","tab you control?"],"style":"accent"},
        {"x":50,"y":300,"w":240,"h":52,"lines":["Network path keeps a","streaming response open?"],"style":"accent"},
        {"x":415,"y":300,"w":260,"h":52,"lines":["Receiver exposes a","reachable endpoint?"],"style":"accent"},
        {"x":10,"y":392,"w":170,"h":58,"lines":["SSE","server to client, native"],"style":"ink"},
        {"x":195,"y":392,"w":210,"h":58,"lines":["Long-polling","held request, repeat"],"style":"ink"},
        {"x":415,"y":392,"w":190,"h":58,"lines":["Webhook","sender calls you"],"style":"ink"},
        {"x":620,"y":392,"w":240,"h":58,"lines":["gRPC server-streaming","typed, flow-controlled"],"style":"ink"},
    ],
    edges=[
        {"x1":420,"y1":68,"x2":135,"y2":118,"label":"No, nothing to push"},
        {"x1":460,"y1":68,"x2":460,"y2":118,"label":"Yes"},
        {"x1":560,"y1":170,"x2":740,"y2":208,"label":"Both push, sub-second","amber":True},
        {"x1":420,"y1":170,"x2":350,"y2":208,"label":"Server only"},
        {"x1":320,"y1":260,"x2":170,"y2":300,"label":"Browser you control"},
        {"x1":400,"y1":260,"x2":545,"y2":300,"label":"Another service"},
        {"x1":130,"y1":352,"x2":95,"y2":392,"label":"Yes, survives proxies","amber":True},
        {"x1":200,"y1":352,"x2":300,"y2":392,"label":"No, gets stripped"},
        {"x1":480,"y1":352,"x2":510,"y2":392,"label":"Yes, call it","amber":True},
        {"x1":600,"y1":352,"x2":740,"y2":392,"label":"No, control both ends","amber":True},
    ],
)

# ---------------------------------------------------------------------------
# Figure 2.2 — duplex / direction comparison
# ---------------------------------------------------------------------------
gd.emit(
    "02-duplex-comparison", 900, 500,
    bands=[
        {"x":20,"y":16,"w":860,"h":84,"label":"WebSocket — full duplex over one connection","fill":"#fff3e0"},
        {"x":20,"y":108,"w":860,"h":84,"label":"SSE — server to client only, one HTTP response","fill":"#fafafa"},
        {"x":20,"y":200,"w":860,"h":84,"label":"Long-polling — repeated request/response cycles","fill":"#fafafa"},
        {"x":20,"y":292,"w":860,"h":84,"label":"Webhook — event source calls your endpoint","fill":"#fafafa"},
        {"x":20,"y":384,"w":860,"h":84,"label":"gRPC server-streaming — one HTTP/2 stream, server writes","fill":"#fafafa"},
    ],
    nodes=[
        {"x":50,"y":50,"w":160,"h":40,"lines":["Browser tab"],"style":"user"},
        {"x":690,"y":50,"w":160,"h":40,"lines":["Server"],"style":"box"},

        {"x":50,"y":142,"w":160,"h":40,"lines":["Browser tab"],"style":"user"},
        {"x":690,"y":142,"w":160,"h":40,"lines":["Server"],"style":"box"},

        {"x":50,"y":234,"w":160,"h":40,"lines":["Browser tab"],"style":"user"},
        {"x":690,"y":234,"w":160,"h":40,"lines":["Server"],"style":"box"},

        {"x":50,"y":326,"w":160,"h":40,"lines":["Event source"],"style":"box"},
        {"x":690,"y":326,"w":160,"h":40,"lines":["Your endpoint"],"style":"user"},

        {"x":50,"y":418,"w":160,"h":40,"lines":["Client service"],"style":"user"},
        {"x":690,"y":418,"w":160,"h":40,"lines":["Server service"],"style":"box"},
    ],
    edges=[
        {"x1":210,"y1":62,"x2":690,"y2":62,"label":"frames, either side, anytime","amber":True,"bidir":True},

        {"x1":690,"y1":154,"x2":210,"y2":154,"label":"event: ... data: ... (repeat)"},

        {"x1":210,"y1":246,"x2":690,"y2":246,"label":"GET, held open"},
        {"x1":690,"y1":262,"x2":210,"y2":262,"label":"200, then re-request","dashed":True},

        {"x1":50,"y1":338,"x2":690,"y2":338,"label":"POST when event fires","amber":True},

        {"x1":210,"y1":430,"x2":690,"y2":430,"label":"open stream"},
        {"x1":690,"y1":446,"x2":210,"y2":446,"label":"push, push, push ..."},
    ],
)
