#!/usr/bin/env python3
"""Fig 21.1/21.2: Ch21: the WebSocket test pyramid (unit/conformance ->
live integration -> functional HTTP/close-code -> load), grounded in the
real corpus (examples/*/verify.sh, examples/_lib/lib.sh, python
tests/test_contract.py, the Quarkus HandlingEventContractTest /
HandlingEventProtoRoundTripTest, examples/part6-testing/newman, and the k6
smoke.js/benchmark.js split): and what each layer can and can't observe
about a protocol a plain `curl` can't reach."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"

# ---------------------------------------------------------------------------
# Figure 21.1: the pyramid: four layers, narrow at the top
# ---------------------------------------------------------------------------
W1, H1 = 900, 560

bands_1 = [
    {"x": 20, "y": 10, "w": 860, "h": 540, "label": "", "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 300, "y": 30, "w": 300, "h": 70,
     "lines": ["Load: k6", "smoke.js GATED / benchmark.js local-only",
               "DRQ-023, DRQ-027"],
     "style": "box"},

    {"x": 230, "y": 125, "w": 440, "h": 70,
     "lines": ["Functional: Newman + python close-code probe",
               "12 assertions / 0 failed (DRQ-030); ws_close_probe for 4400/4290/1008",
               "the HTTP seam + the close codes websocat can't read"],
     "style": "box"},

    {"x": 140, "y": 220, "w": 620, "h": 90,
     "lines": ["Live integration: verify.sh + lib.sh, both stacks, real containers",
               "ws_first_frame / ws_frames_n / ws_connect_bg / assert_ws_rejected /",
               "wait_for_log_count: docker compose up, assert, compose down"],
     "style": "accent"},

    {"x": 60, "y": 330, "w": 780, "h": 90,
     "lines": ["Unit / conformance: pytest test_contract.py + Quarkus HandlingEventContractTest",
               "schema_validate against build/handling-event.schema.json, proto round-trip",
               "(HandlingEventProtoRoundTripTest): no socket, no container, runs in milliseconds"],
     "style": "box"},

    {"x": 140, "y": 445, "w": 620, "h": 55,
     "lines": ["the contract-drift gate: regenerate the schema, re-run every layer",
               "that reads it, on every change to contracts/asyncapi.yaml"],
     "style": "ink"},

    {"x": 60, "y": 515, "w": 340, "h": 30,
     "lines": ["fewer tests, slower, closer to production ↑"],
     "style": "ghost"},
    {"x": 500, "y": 515, "w": 340, "h": 30,
     "lines": ["more tests, faster, further from production ↓"],
     "style": "ghost"},
]

edges_1 = [
    {"x1": 450, "y1": 100, "x2": 450, "y2": 125, "dashed": True},
    {"x1": 450, "y1": 195, "x2": 450, "y2": 220, "dashed": True},
    {"x1": 450, "y1": 310, "x2": 450, "y2": 330, "dashed": True},
    {"x1": 450, "y1": 420, "x2": 450, "y2": 445, "amber": True},
]

notes_1 = [
    {"x": 450, "y": 490, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "Ch21/22/24 are prose citing this existing corpus (DRQ-028); only Ch23 adds new runnable code."},
]

generate_diagram.emit("21-test-pyramid", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 21.2: what each layer can and can't observe
# ---------------------------------------------------------------------------
W2, H2 = 940, 520

nodes_2 = [
    {"x": 20, "y": 10, "w": 430, "h": 110,
     "lines": ["Unit / conformance (no socket)",
               "SEES: schema shape, enum parity (8 members),",
               "proto<->JSON value parity, wire-size assertion",
               "BLIND TO: anything over a live connection at all"],
     "style": "box"},
    {"x": 470, "y": 10, "w": 450, "h": 110,
     "lines": ["Live integration (websocat via lib.sh)",
               "SEES: frame contents, field semantics, reconnect/",
               "resume, fan-out across instances, idle-hold",
               "BLIND TO: close CODES: exit code alone can't tell",
               "\"rejected\" from \"accepted and still open\""],
     "style": "accent"},

    {"x": 20, "y": 150, "w": 430, "h": 110,
     "lines": ["Functional close-code probe (python + websockets lib)",
               "SEES: exact close_code (4400/4290/1008),",
               "the BAD_REQUEST envelope, frame count before close",
               "WHY: websockets library exposes ws.close_code;",
               "websocat has no equivalent flag"],
     "style": "box"},
    {"x": 470, "y": 150, "w": 450, "h": 110,
     "lines": ["Functional HTTP (Newman)",
               "SEES: the HTTP seam around the socket: /healthz,",
               "the inject endpoint's 202/400/422: 12 assertions, 0 failed",
               "BLIND TO: the WebSocket channel itself",
               "contracts/asyncapi.yaml is WS-only"],
     "style": "box"},

    {"x": 20, "y": 290, "w": 450, "h": 110,
     "lines": ["Load: k6 smoke.js (gated)",
               "SEES: connect success, 3-frame shape, p(95) session time",
               "DETERMINISTIC: rate==1.0 threshold fails the PR",
               "on any failed check, every run, same host or not"],
     "style": "box"},
    {"x": 490, "y": 290, "w": 430, "h": 110,
     "lines": ["Load: k6 benchmark.js (local-only)",
               "SEES: bytes/frame, connects/sec, negotiation outcome",
               "TIMING-SENSITIVE: connects/sec moves with the host's",
               "ephemeral-port state: never cited as a bare number"],
     "style": "box"},

    {"x": 120, "y": 430, "w": 700, "h": 70,
     "lines": ["Deterministic across every run: schema validation, round-trips, close codes,",
               "frame field values, negotiation yes/no. Timing-sensitive: idle-hold windows,",
               "heartbeat detection delay, raw connects/sec: bounded, never asserted exactly."],
     "style": "ink"},
]

edges_2 = []

notes_2 = [
    {"x": 470, "y": 495, "size": 11, "color": "#555555", "anchor": "middle",
     "text": "Each layer's blind spot is why the next layer up exists: none of the five alone proves the channel correct."},
]

generate_diagram.emit("21-layer-visibility", W2, H2, nodes=nodes_2, edges=edges_2, notes=notes_2)
