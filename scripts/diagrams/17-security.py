#!/usr/bin/env python3
"""Fig 17.1/17.2 — Ch17: the JWT auth-at-upgrade flow (token on the query
string, validated right after the handshake completes, not inside
`process_request`/before it — see app/ws_server.py's and
HandlingEventConnectionWebSocket#onOpen's docstrings) and the teaching
HS256-shared-secret shape this example uses vs. the Keycloak/OIDC RS256+JWKS
shape named as the production path (DRQ-021)."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 17.1 — auth-at-upgrade flow: token -> validate -> accept/1008
# ---------------------------------------------------------------------------
W1, H1 = 980, 520

bands_1 = [
    {"x": 20, "y": 20, "w": 940, "h": 480,
     "label": "ws_server.py handler() / HandlingEventConnectionWebSocket#onOpen — both stacks validate AFTER accept, not before",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 40, "y": 70, "w": 230, "h": 80,
     "lines": ["CLIENT", "GET /ws/.../handling-events", "?token=<jwt>"],
     "style": "user"},

    {"x": 360, "y": 70, "w": 250, "h": 80,
     "lines": ["OPENING HANDSHAKE", "HTTP Upgrade request", "token rides the query string"],
     "style": "box"},

    {"x": 700, "y": 60, "w": 250, "h": 95,
     "lines": ["process_request hook (Python)", "runs BEFORE handshake completes —", "can only return an HTTP response,", "no WS close code exists yet"],
     "style": "ghost"},

    {"x": 360, "y": 210, "w": 250, "h": 60,
     "lines": ["101 Switching Protocols", "handshake complete, socket open"],
     "style": "box"},

    {"x": 360, "y": 320, "w": 250, "h": 90,
     "lines": ["VALIDATE (in the handler)", "validate_token() / JwtHs256.verify()", "HS256 signature + exp, before", "a single fixture frame is sent"],
     "style": "accent"},

    {"x": 60, "y": 440, "w": 250, "h": 60,
     "lines": ["ACCEPT", "stream the fixture replay"],
     "style": "user"},

    {"x": 660, "y": 440, "w": 290, "h": 60,
     "lines": ["REJECT — close(1008)", "no data sent, no reason echoed"],
     "style": "ink"},
]

edges_1 = [
    {"x1": 270, "y1": 110, "x2": 360, "y2": 110, "label": "1. upgrade request"},
    {"x1": 610, "y1": 100, "x2": 700, "y2": 100, "label": "would run here", "dashed": True},
    {"x1": 485, "y1": 150, "x2": 485, "y2": 210, "label": "2. handshake completes"},
    {"x1": 485, "y1": 270, "x2": 485, "y2": 320, "label": "3. handler runs first"},
    {"x1": 400, "y1": 410, "x2": 185, "y2": 440, "label": "valid signature + unexpired", "amber": True},
    {"x1": 560, "y1": 410, "x2": 805, "y2": 440, "label": "missing/garbage/expired/bad-sig", "dashed": True},
]

notes_1 = [
    {"x": 490, "y": 500, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "process_request can only answer with an HTTP response (no app close code yet) -- so this example validates right after accept and closes 1008 instead."},
]

generate_diagram.emit("17-auth-upgrade-flow", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 17.2 — teaching HS256 shared secret vs. production Keycloak/JWKS
# ---------------------------------------------------------------------------
W2, H2 = 980, 440

bands_2 = [
    {"x": 20, "y": 20, "w": 940, "h": 400,
     "label": "Same bearer-JWT shape at the upgrade -- different trust model behind it (DRQ-021)",
     "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 50, "y": 65, "w": 400, "h": 55,
     "lines": ["THIS EXAMPLE -- teaching"],
     "style": "accent"},

    {"x": 530, "y": 65, "w": 400, "h": 55,
     "lines": ["PRODUCTION PATH -- Keycloak / OIDC"],
     "style": "user"},

    {"x": 50, "y": 140, "w": 400, "h": 70,
     "lines": ["mint_token.py / TokenMinter", "one process mints AND signs HS256"],
     "style": "box"},

    {"x": 530, "y": 140, "w": 400, "h": 70,
     "lines": ["Keycloak issues + signs RS256", "token at a real OIDC token endpoint"],
     "style": "box"},

    {"x": 50, "y": 230, "w": 400, "h": 70,
     "lines": ["WS_JWT_SECRET -- one symmetric key", "shared by every minter AND verifier"],
     "style": "ink"},

    {"x": 530, "y": 230, "w": 400, "h": 70,
     "lines": ["JWKS endpoint publishes public keys", "resource server fetches + caches, rotates"],
     "style": "ink"},

    {"x": 50, "y": 320, "w": 400, "h": 70,
     "lines": ["Verify: recompute HMAC, constant-", "time compare against the shared secret"],
     "style": "box"},

    {"x": 530, "y": 320, "w": 400, "h": 70,
     "lines": ["Verify: RSA signature against the", "rotating public key -- no shared secret"],
     "style": "box"},
]

edges_2 = [
    {"x1": 450, "y1": 92, "x2": 530, "y2": 92, "label": "DRQ-021: same shape, different trust model", "amber": True},
]

notes_2 = [
    {"x": 490, "y": 410, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "A shared secret works for one teaching process minting and verifying its own tokens -- it does not survive a second verifier needing the same secret."},
]

generate_diagram.emit("17-hs256-vs-keycloak", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
