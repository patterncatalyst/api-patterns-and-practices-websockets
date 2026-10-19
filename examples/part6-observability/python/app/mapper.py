"""Part 6 example — maps a validated `HandlingEvent` contract-model instance
to its outbound wire frame (a JSON string).

Every prior Python example folded this into `feed.py` as `sequence_as_json`.
This example splits it into its own module instead: `app/ws_server.py`'s
per-connection loop needs a per-event hook to increment the
`handling_events_delivered_total` counter (DRQ-029) and emit the manual
`ws.handling-events.connection` span's trace-id log line (see that module)
at the point a frame actually leaves the server — not at the point the
fixture is loaded/validated (`feed.py`, which runs once and has no notion of
"delivery"). Keeping "load + validate" (`feed.py`) and "serialize for the
wire" (this module) as two single-purpose steps makes that per-event
instrumentation hook a one-line call in `ws_server.py` instead of a second
responsibility bolted onto `feed.py`.
"""
from __future__ import annotations

from app.models_generated import HandlingEvent


def to_wire_frame(event: HandlingEvent) -> str:
    """Serialize one validated `HandlingEvent` to the JSON string sent over
    the wire, via the generated model's own `model_dump_json`, dropping
    absent optional fields (`voyageNumber`, `amount`) the same way the
    fixture omits them — byte-for-byte identical to every other Python
    example's frames for the same fixture event.
    """
    return event.model_dump_json(exclude_none=True)
