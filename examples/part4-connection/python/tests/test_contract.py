"""Part 4 example — conformance + connection-concerns unit tests.

Forked from examples/part3-handling-events/python/tests/test_contract.py.
The first block (schema conformance) is unchanged in spirit — this example
replays the identical shared fixture, so the same invariants hold. The
second block is new: unit tests for the Ch17 auth module and the Ch13 error
envelope shape, both pure-Python (no socket needed), run against
`build/handling-event.schema.json` (the self-contained JSON Schema
extracted from contracts/asyncapi.yaml by
../../../scripts/extract-message-schema.py — regenerate it before running
this test, see README.md).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import jwt
import pytest
from jsonschema import Draft202012Validator

from app import auth
from app.feed import load_fixture, sequence, sequence_as_json
from app.models_generated import HandlingEvent
from app.ws_server import _error_envelope

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
# Schema conformance (shared fixture, forked from Part 3's test suite)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Ch17 auth — app/auth.py, pure-Python (no socket)
# ---------------------------------------------------------------------------


def _token(claims: dict, secret: str = auth.JWT_SECRET) -> str:
    return jwt.encode(claims, secret, algorithm=auth.JWT_ALGORITHM)


def test_validate_token_accepts_a_valid_token() -> None:
    now = int(time.time())
    token = _token({"sub": "test-client", "iat": now, "exp": now + 300})
    claims = auth.validate_token(token)
    assert claims["sub"] == "test-client"


def test_validate_token_rejects_a_missing_token() -> None:
    with pytest.raises(auth.AuthError):
        auth.validate_token(None)
    with pytest.raises(auth.AuthError):
        auth.validate_token("")


def test_validate_token_rejects_an_expired_token() -> None:
    now = int(time.time())
    token = _token({"sub": "test-client", "iat": now - 400, "exp": now - 10})
    with pytest.raises(auth.AuthError):
        auth.validate_token(token)


def test_validate_token_rejects_a_bad_signature() -> None:
    now = int(time.time())
    token = _token({"sub": "test-client", "iat": now, "exp": now + 300}, secret="wrong-secret")
    with pytest.raises(auth.AuthError):
        auth.validate_token(token)


def test_validate_token_rejects_a_malformed_token() -> None:
    with pytest.raises(auth.AuthError):
        auth.validate_token("not-a-jwt-at-all")


# ---------------------------------------------------------------------------
# Ch13 errors — app/ws_server.py's error envelope shape
# ---------------------------------------------------------------------------


def test_error_envelope_shape() -> None:
    envelope = _error_envelope("invalid JSON: boom")
    assert envelope == {"error": {"code": "BAD_REQUEST", "message": "invalid JSON: boom"}}
