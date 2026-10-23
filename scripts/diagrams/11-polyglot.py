#!/usr/bin/env python3
"""Chapter 11 "Polyglot: One Contract, Two Stacks": two diagrams.

1. 11-contract-to-identical-frames: the SAME `contracts/asyncapi.yaml`
   reaches Quarkus and Python by two different mechanisms (hand-kept +
   conformance test vs. generated model), and `verify.sh` proves both
   converge on an identical first frame, field-by-field (JSON key order
   differs; values don't).
2. 11-drift-gate-pipeline: the `.github/workflows/contracts.yml` gate:
   a contract edit fans out to four jobs (validate, breaking, drift,
   examples), and the gate only allows a merge when all four are green.

See examples/part3-handling-events/README.md and
.github/workflows/contracts.yml for the artifacts these diagrams describe.
"""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Diagram 1: contract -> two generation paths -> identical wire frame
# ---------------------------------------------------------------------------

W1, H1 = 900, 460

nodes1 = [
    {"x": 300, "y": 15, "w": 300, "h": 60,
     "lines": ["contracts/asyncapi.yaml", "components.schemas.HandlingEvent"],
     "style": "ink"},

    {"x": 300, "y": 95, "w": 300, "h": 55,
     "lines": ["extract-message-schema.py", "inlines $refs -> build/handling-event.schema.json"],
     "style": "ghost"},

    {"x": 40, "y": 195, "w": 350, "h": 110,
     "lines": ["Quarkus: hand-kept",
               "HandlingEvent record + HandlingEventType enum",
               "checked by HandlingEventContractTest"],
     "style": "accent"},

    {"x": 510, "y": 195, "w": 350, "h": 110,
     "lines": ["Python: generated",
               "datamodel-codegen -> app/models_generated.py",
               "Pydantic v2 model, checked by test_contract.py"],
     "style": "box"},

    {"x": 225, "y": 345, "w": 450, "h": 95,
     "lines": ["verify.sh Step 3: cross-stack agreement",
               "same eventId / eventType / bookingId / cargoId / location / occurredAt / registeredAt",
               "JSON key order differs (Jackson vs. Pydantic): values are identical"],
     "style": "ink"},
]

edges1 = [
    {"x1": 450, "y1": 75, "x2": 450, "y2": 95},
    {"x1": 400, "y1": 150, "x2": 215, "y2": 195,
     "label": "validates against", "amber": True},
    {"x1": 500, "y1": 150, "x2": 685, "y2": 195,
     "label": "generates from", "amber": True},
    {"x1": 215, "y1": 305, "x2": 370, "y2": 345,
     "label": "first frame"},
    {"x1": 685, "y1": 305, "x2": 530, "y2": 345,
     "label": "first frame"},
]

notes1 = [
    {"x": 450, "y": 440, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "Two different mechanisms generate from or validate against the same file; neither stack reads the other's source."},
]

generate_diagram.emit("11-contract-to-identical-frames", W1, H1, nodes=nodes1, edges=edges1, notes=notes1)

# ---------------------------------------------------------------------------
# Diagram 2: the contracts.yml drift gate
# ---------------------------------------------------------------------------

W2, H2 = 980, 460

nodes2 = [
    {"x": 20, "y": 185, "w": 170, "h": 90,
     "lines": ["PR: edit", "contracts/asyncapi.yaml"],
     "style": "user"},

    {"x": 250, "y": 15, "w": 210, "h": 65,
     "lines": ["validate", "asyncapi validate (CLI)"],
     "style": "box"},

    {"x": 250, "y": 115, "w": 210, "h": 95,
     "lines": ["breaking", "asyncapi diff -t all + jq:",
               "remove / edit type|pattern / add required"],
     "style": "accent"},

    {"x": 250, "y": 245, "w": 210, "h": 95,
     "lines": ["drift", "extract schema, regenerate Python model,",
               "run both conformance tests"],
     "style": "box"},

    {"x": 250, "y": 375, "w": 210, "h": 70,
     "lines": ["examples matrix", "verify.sh per example, 3x retry"],
     "style": "box"},

    {"x": 540, "y": 175, "w": 220, "h": 110,
     "lines": ["examples-summary", "gate: all 4 jobs green?"],
     "style": "ink"},

    {"x": 830, "y": 80, "w": 140, "h": 70,
     "lines": ["merge allowed", "contract change lands"],
     "style": "accent"},

    {"x": 830, "y": 280, "w": 140, "h": 70,
     "lines": ["gate fails", "caught before merge"],
     "style": "ghost"},
]

edges2 = [
    {"x1": 190, "y1": 210, "x2": 250, "y2": 48},
    {"x1": 190, "y1": 220, "x2": 250, "y2": 162},
    {"x1": 190, "y1": 235, "x2": 250, "y2": 292},
    {"x1": 190, "y1": 250, "x2": 250, "y2": 410},
    {"x1": 460, "y1": 48, "x2": 540, "y2": 200},
    {"x1": 460, "y1": 162, "x2": 540, "y2": 215},
    {"x1": 460, "y1": 292, "x2": 540, "y2": 250},
    {"x1": 460, "y1": 410, "x2": 540, "y2": 270},
    {"x1": 760, "y1": 205, "x2": 830, "y2": 115,
     "label": "all green", "amber": True},
    {"x1": 760, "y1": 250, "x2": 830, "y2": 310,
     "label": "any red", "dashed": True},
]

notes2 = [
    {"x": 490, "y": 440, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "asyncapi diff's own -t breaking misses payload-schema changes: the breaking job's jq filter closes that gap itself."},
]

generate_diagram.emit("11-drift-gate-pipeline", W2, H2, nodes=nodes2, edges=edges2, notes=notes2)
