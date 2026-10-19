"""Part 5 example — conformance + encoding-parity unit tests.

Forked from examples/part4-connection/python/tests/test_contract.py. The
first block (JSON schema conformance) is unchanged in spirit — this example
replays the identical shared fixture, so the same invariants hold. The
second block is new (DRQ-025): a Protobuf round-trip test per fixture event
— model -> proto -> bytes -> proto -> dict — validated against the SAME
`build/handling-event.schema.json` the JSON encoding uses (via
app/mapper.py's `proto_to_dict`, which produces the same shape
`model_dump(mode="json")` would), plus the wire-size assertion Ch19/20 is
about: Protobuf bytes are smaller than the equivalent JSON text frame.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.feed import load_fixture, sequence, sequence_as_json
from app.handling_event_pb2 import HandlingEvent as HandlingEventProto
from app.mapper import proto_to_dict, to_proto
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


# ---------------------------------------------------------------------------
# JSON schema conformance (shared fixture, forked from Part 3/4's suites)
# ---------------------------------------------------------------------------


def test_fixture_is_three_events_in_order() -> None:
    fixture = load_fixture()
    assert [e["eventType"] for e in fixture] == ["RECEIVE", "LOAD", "CUSTOMS"]


def test_emitted_json_frames_validate_against_schema(validator: Draft202012Validator) -> None:
    frames = sequence_as_json()
    assert len(frames) == 3
    for frame in frames:
        doc = json.loads(frame)
        errors = list(validator.iter_errors(doc))
        assert not errors, f"{frame} failed schema validation: {errors}"


def test_first_json_frame_is_the_receive_event_matching_the_fixture() -> None:
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


# ---------------------------------------------------------------------------
# Ch19 Protobuf — app/mapper.py, app/handling_event_pb2.py (DRQ-025)
# ---------------------------------------------------------------------------


def test_proto_round_trip_matches_schema_and_json_values(validator: Draft202012Validator) -> None:
    """model -> proto -> bytes -> proto -> dict must validate against the
    SAME JSON Schema the JSON encoding validates against, AND equal the
    JSON-mode dump of the same model exactly — the "value parity" DRQ-025
    requires between the two wire encodings.
    """
    for event in sequence():
        proto = to_proto(event)
        wire_bytes = proto.SerializeToString()

        decoded = HandlingEventProto()
        decoded.ParseFromString(wire_bytes)
        decoded_dict = proto_to_dict(decoded)

        errors = list(validator.iter_errors(decoded_dict))
        assert not errors, f"{decoded_dict} failed schema validation: {errors}"

        json_dict = json.loads(event.model_dump_json(exclude_none=True))
        assert decoded_dict == json_dict, (
            f"proto round-trip drift for {json_dict['eventId']}: "
            f"{decoded_dict} != {json_dict}"
        )


def test_proto_wire_bytes_are_smaller_than_the_equivalent_json_frame() -> None:
    """Ch19/20's headline claim: the binary frame is smaller than the JSON
    text frame carrying the exact same field values, for every fixture
    event."""
    events = sequence()
    json_frames = sequence_as_json()
    assert len(events) == len(json_frames)

    for event, json_frame in zip(events, json_frames):
        proto_size = len(to_proto(event).SerializeToString())
        json_size = len(json_frame.encode("utf-8"))
        assert proto_size < json_size, (
            f"expected Protobuf ({proto_size} bytes) < JSON ({json_size} bytes) "
            f"for {event.eventId}"
        )


def test_proto_enum_values_round_trip_every_fixture_event_type() -> None:
    """Every fixture event's eventType member round-trips through the
    proto's HANDLING_EVENT_TYPE_-prefixed enum and back to the bare JSON
    member name (RECEIVE, LOAD, CUSTOMS) — see app/mapper.py."""
    for event in sequence():
        proto = to_proto(event)
        decoded_dict = proto_to_dict(proto)
        assert decoded_dict["eventType"] == event.eventType.value
