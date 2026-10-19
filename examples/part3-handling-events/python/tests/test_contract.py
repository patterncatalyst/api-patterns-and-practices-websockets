"""Ch9 example — conformance test.

Asserts two things against `build/handling-event.schema.json` (the
self-contained JSON Schema extracted from contracts/asyncapi.yaml by
../../../scripts/extract-message-schema.py — regenerate it before running
this test, see README.md):

1. Every frame the server would emit (app.feed.sequence_as_json(), the
   same values app/ws_server.py pushes over the wire) validates against the
   schema.
2. The generated `HandlingEvent` model round-trips: parsing a fixture event
   into the model and dumping it back out reproduces the exact same values
   (not just "still valid JSON") — including the `Z` UTC suffix on
   timestamps, which Pydantic v2's datetime serialization preserves from the
   input rather than normalizing to `+00:00`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.feed import load_fixture, sequence, sequence_as_json
from app.models_generated import HandlingEvent

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "build" / "handling-event.schema.json"


@pytest.fixture(scope="module")
def schema() -> dict:
    if not SCHEMA_PATH.exists():
        pytest.fail(
            f"{SCHEMA_PATH} not found — run "
            "`python3 -I scripts/extract-message-schema.py build/handling-event.schema.json` "
            "from the repo root first."
        )
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema)


def test_fixture_is_three_events_in_order() -> None:
    fixture = load_fixture()
    assert [e["eventType"] for e in fixture] == ["RECEIVE", "LOAD", "CUSTOMS"]


def test_emitted_frames_validate_against_schema(validator: Draft202012Validator) -> None:
    frames = sequence_as_json()
    assert len(frames) == 3
    for frame in frames:
        doc = json.loads(frame)
        errors = list(validator.iter_errors(doc))
        assert not errors, f"{frame} failed schema validation: {errors}"


def test_first_frame_is_the_receive_event_matching_the_fixture() -> None:
    fixture = load_fixture()
    frames = sequence_as_json()
    first = json.loads(frames[0])
    assert first == fixture[0]
    assert first["eventType"] == "RECEIVE"


def test_generated_model_round_trips_fixture_values_exactly() -> None:
    for raw in load_fixture():
        model = HandlingEvent.model_validate(raw)
        dumped = json.loads(model.model_dump_json(exclude_none=True))
        assert dumped == raw, f"round-trip drift for {raw['eventId']}: {dumped} != {raw}"


def test_sequence_events_validate_as_generated_model_instances() -> None:
    events = sequence()
    assert len(events) == 3
    assert all(isinstance(e, HandlingEvent) for e in events)
    assert [e.eventType.value for e in events] == ["RECEIVE", "LOAD", "CUSTOMS"]
