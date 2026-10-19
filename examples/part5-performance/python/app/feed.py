"""Part 5 example — the DETERMINISTIC handling-event sequence the WS server
replays, SHARED with examples/part3-handling-events and
examples/part4-connection (all three replay the identical fixture — three
HandlingEvents: RECEIVE, LOAD, CUSTOMS, in that order, for one booking — see
../../part3-handling-events/fixtures/handling-events.json). This module's
job is only to load it and hand back validated, contract-conformant
`HandlingEvent` model instances, in the same order, every time. It never
mutates or re-derives any field — field names/values must stay exact, since
Part 5's whole point (DRQ-025/DRQ-026) is that the JSON and Protobuf
encodings of these same values are byte-for-byte comparable.

This example does not own its own fixture file: Part 5 is about wire
encoding (JSON text vs Protobuf binary), not new message content, so reusing
Part 3's fixture keeps all three examples' "happy path" frame VALUES
identical and lets a reader compare them directly. See app/mapper.py for how
each validated event becomes either a JSON text frame or a Protobuf binary
frame.
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from app.models_generated import HandlingEvent

# ../../../part3-handling-events/fixtures/handling-events.json relative to
# this file in a local checkout — the fixture lives under the Part 3
# example directory and is reused here rather than duplicated. The
# Containerfile doesn't preserve that same directory layout (it COPYs the
# fixture to /app/fixtures, a sibling of /app/app), so
# HANDLING_EVENTS_FIXTURE overrides the path there instead of coupling this
# module to the container layout.
_DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "part3-handling-events"
    / "fixtures"
    / "handling-events.json"
)
FIXTURE_PATH = Path(os.environ.get("HANDLING_EVENTS_FIXTURE", str(_DEFAULT_FIXTURE_PATH)))


def load_fixture(path: Path = FIXTURE_PATH) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def sequence(path: Path = FIXTURE_PATH) -> Sequence[HandlingEvent]:
    """Return the fixture's HandlingEvents, in file order, each validated
    against the generated contract model. A fixture that drifts from the
    contract (missing a required field, a bad enum value, a malformed
    UN/LOCODE, ...) fails here — at import/startup time, not silently on
    the wire — via Pydantic's validation errors.
    """
    return [HandlingEvent.model_validate(raw) for raw in load_fixture(path)]


def sequence_as_json(path: Path = FIXTURE_PATH) -> list[str]:
    """The JSON-encoding wire-ready frames: each validated HandlingEvent
    re-serialized via the generated model's own `model_dump_json`, dropping
    absent optional fields (`voyageNumber`, `amount`) the same way the
    fixture omits them. See app/mapper.py for the Protobuf-encoding
    equivalent.
    """
    return [event.model_dump_json(exclude_none=True) for event in sequence(path)]
