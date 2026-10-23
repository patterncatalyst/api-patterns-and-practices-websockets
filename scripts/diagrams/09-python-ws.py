#!/usr/bin/env python3
"""Fig 9.1/9.2: Ch9: the Python example's two-listeners-one-event-loop
architecture (app/main.py), and the build-time model-generation flow that
turns contracts/asyncapi.yaml into the Pydantic v2 model app/feed.py
imports (scripts/generate-models.sh / Containerfile)."""
import sys
sys.path.insert(0, "scripts")
import generate_diagram
generate_diagram.OUT = "assets/diagrams"
import os
os.makedirs(generate_diagram.OUT, exist_ok=True)

# ---------------------------------------------------------------------------
# Figure 9.1: two listeners, one asyncio event loop (app/main.py)
# ---------------------------------------------------------------------------
W1, H1 = 860, 420

bands_1 = [
    {"x": 20, "y": 20, "w": 820, "h": 380,
     "label": "app/main.py, asyncio.run(main()): one process, one event loop",
     "fill": "#fafafa"},
]

nodes_1 = [
    {"x": 290, "y": 55, "w": 280, "h": 65,
     "lines": ["await asyncio.gather(", "_run_ws(), _run_http())"],
     "style": "ink"},

    {"x": 70, "y": 165, "w": 320, "h": 100,
     "lines": ["_run_ws(): app/ws_server.py",
               "websockets.asyncio.server.serve(handler, ...)",
               "WS_HOST:WS_PORT: 0.0.0.0:8081",
               "one handler() coroutine per connection"],
     "style": "accent"},

    {"x": 470, "y": 165, "w": 320, "h": 100,
     "lines": ["_run_http(): app/http_app.py",
               "uvicorn.Server(Config(http_app, ...))",
               "HTTP_HOST:HTTP_PORT: 0.0.0.0:8082",
               "FastAPI: GET /healthz, GET /"],
     "style": "user"},

    {"x": 70, "y": 320, "w": 320, "h": 60,
     "lines": ["WS client", "ws://.../ws/v1/bookings/{bookingId}/handling-events"],
     "style": "ghost"},

    {"x": 470, "y": 320, "w": 320, "h": 60,
     "lines": ["HTTP client / k8s probe", "GET /healthz"],
     "style": "ghost"},
]

edges_1 = [
    {"x1": 380, "y1": 120, "x2": 260, "y2": 165, "label": "task 1"},
    {"x1": 480, "y1": 120, "x2": 600, "y2": 165, "label": "task 2"},
    {"x1": 230, "y1": 265, "x2": 230, "y2": 320, "label": "pushes 3 frames, then idles"},
    {"x1": 630, "y1": 265, "x2": 630, "y2": 320, "label": "liveness/readiness only", "dashed": True},
]

notes_1 = [
    {"x": 430, "y": 405, "size": 12, "color": "#b8650a", "anchor": "middle", "bold": True,
     "text": "Neither listener blocks the other: both are coroutines on the same loop, not separate processes or threads."},
]

generate_diagram.emit("09-two-listeners-one-loop", W1, H1, bands=bands_1, nodes=nodes_1, edges=edges_1, notes=notes_1)

# ---------------------------------------------------------------------------
# Figure 9.2: build-time model generation: contract -> schema -> Pydantic
# ---------------------------------------------------------------------------
W2, H2 = 900, 380

bands_2 = [
    {"x": 20, "y": 20, "w": 860, "h": 160, "label": "build time (scripts/generate-models.sh, Containerfile)", "fill": "#fafafa"},
    {"x": 20, "y": 210, "w": 860, "h": 150, "label": "runtime (app/feed.py, app/ws_server.py)", "fill": "#fafafa"},
]

nodes_2 = [
    {"x": 50, "y": 60, "w": 190, "h": 80,
     "lines": ["contracts/asyncapi.yaml", "components.schemas", ".HandlingEvent"],
     "style": "ink"},

    {"x": 280, "y": 60, "w": 200, "h": 80,
     "lines": ["extract-message-schema.py", "inlines $refs,", "sort_keys=True"],
     "style": "box"},

    {"x": 520, "y": 60, "w": 200, "h": 80,
     "lines": ["build/handling-event", ".schema.json", "(gitignored, Draft 2020-12)"],
     "style": "ghost"},

    {"x": 760, "y": 60, "w": 100, "h": 80,
     "lines": ["datamodel-", "codegen"],
     "style": "box"},

    {"x": 50, "y": 250, "w": 230, "h": 80,
     "lines": ["app/models_generated.py", "(gitignored)", "class HandlingEvent(BaseModel)"],
     "style": "ghost"},

    {"x": 340, "y": 250, "w": 230, "h": 80,
     "lines": ["app/feed.py", "HandlingEvent.model_validate(fixture)", "sequence_as_json()"],
     "style": "accent"},

    {"x": 630, "y": 250, "w": 230, "h": 80,
     "lines": ["app/ws_server.py", "handler(): await websocket.send(frame)", "for frame in sequence_as_json()"],
     "style": "accent"},
]

edges_2 = [
    {"x1": 240, "y1": 100, "x2": 280, "y2": 100, "label": "reads"},
    {"x1": 480, "y1": 100, "x2": 520, "y2": 100, "label": "writes"},
    {"x1": 720, "y1": 100, "x2": 760, "y2": 100, "label": "--input"},
    {"x1": 810, "y1": 140, "x2": 165, "y2": 250, "label": "pydantic_v2.BaseModel", "amber": True},
    {"x1": 280, "y1": 290, "x2": 340, "y2": 290, "label": "import HandlingEvent"},
    {"x1": 570, "y1": 290, "x2": 630, "y2": 290, "label": "validated frames"},
]

notes_2 = [
    {"x": 450, "y": 370, "size": 12, "color": "#555555", "anchor": "middle",
     "text": "One generated model does both jobs: validate the fixture in, serialize the wire frame out, nothing hand-written in between to drift from the contract."},
]

generate_diagram.emit("09-model-generation-flow", W2, H2, bands=bands_2, nodes=nodes_2, edges=edges_2, notes=notes_2)
