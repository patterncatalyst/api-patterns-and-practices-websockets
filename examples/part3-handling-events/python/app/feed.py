"""Ch9 example — the DETERMINISTIC handling-event sequence the WS server
replays, shared with the Quarkus stack (both stacks read the same fixture
file, see ../../fixtures/handling-events.json and
../../quarkus/README.md).

The fixture is the single source of truth for VALUES (three HandlingEvents:
RECEIVE, LOAD, CUSTOMS, in that order, for one booking); this module's job
is only to load it and hand back validated, contract-conformant
`HandlingEvent` model instances, in the same order, every time. It never
mutates or re-derives any field — field names/values must stay exact.
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from app.models_generated import HandlingEvent

# ../../fixtures/handling-events.json relative to this file in a local
# checkout — the fixture lives one level above both the python/ and
# quarkus/ example directories because it is shared between the two stacks
# (replay the identical sequence, not independently-plausible data). The
# Containerfile doesn't preserve that same directory depth (it COPYs the
# fixture to /app/fixtures, a sibling of /app/app), so HANDLING_EVENTS_FIXTURE
# overrides the path there instead of coupling this module to the container
# layout.
_DEFAULT_FIXTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "fixtures" / "handling-events.json"
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
    """The wire-ready frames: each validated HandlingEvent re-serialized via
    the generated model's own `model_dump_json`, dropping absent optional
    fields (`voyageNumber`, `amount`) the same way the fixture omits them.
    Because the model's JSON serialization reproduces every fixture value
    byte-for-byte (verified in tests/test_contract.py — including the `Z`
    UTC suffix on timestamps), emitting the model's own serialization keeps
    the wire frame and the contract model a single source of truth instead
    of re-implementing serialization by hand.
    """
    return [event.model_dump_json(exclude_none=True) for event in sequence(path)]
