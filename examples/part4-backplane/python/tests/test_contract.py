"""Part 4 example — conformance + backplane unit tests.

Forked from examples/part4-connection/python/tests/test_contract.py. The
first block (schema conformance) is unchanged in spirit — this example
replays the identical shared fixture as its deterministic seed, so the same
invariants hold. The second block is new: pure-Python (no socket, no live
broker) unit tests for the backplane abstraction — the `stateless` mode's
in-process fan-out can be exercised directly; `kafka`/`redis` modes need a
live broker, which is out of scope for this pytest suite (see README.md's
"Self-verify" section for the live-broker proof via a standalone container).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.backplane import create_backplane
from app.backplane.kafka_backplane import KafkaBackplane
from app.backplane.redis_backplane import RedisBackplane
from app.backplane.stateless_backplane import StatelessBackplane
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
# Schema conformance (shared fixture, forked from Part 3/Part 4-connection's
# test suite)
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
# Ch13-style error envelope — app/ws_server.py's error envelope shape
# ---------------------------------------------------------------------------


def test_error_envelope_shape() -> None:
    envelope = _error_envelope("invalid JSON: boom")
    assert envelope == {"error": {"code": "BAD_REQUEST", "message": "invalid JSON: boom"}}


# ---------------------------------------------------------------------------
# Ch18 backplane — app/backplane/*, pure-Python (no socket, no live broker)
# ---------------------------------------------------------------------------


def _sample_event(event_id: str = "evt_01HZYTESTAAAAAAAAAAAAAAAAA") -> HandlingEvent:
    raw = load_fixture()[0]
    raw = {**raw, "eventId": event_id}
    return HandlingEvent.model_validate(raw)


def test_create_backplane_defaults_to_stateless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BACKPLANE_MODE", raising=False)
    assert isinstance(create_backplane(), StatelessBackplane)


def test_create_backplane_selects_kafka() -> None:
    assert isinstance(create_backplane("kafka"), KafkaBackplane)


def test_create_backplane_selects_redis() -> None:
    assert isinstance(create_backplane("redis"), RedisBackplane)


def test_create_backplane_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError):
        create_backplane("not-a-real-mode")


def test_stateless_backplane_delivers_to_a_local_subscriber() -> None:
    async def scenario() -> HandlingEvent:
        backplane = StatelessBackplane()
        booking_id = "bkg_test_01"
        event = _sample_event()

        subscription = backplane.subscribe(booking_id, after_event_id=None)
        received: HandlingEvent | None = None

        async def consume_one() -> None:
            nonlocal received
            async for e in subscription:
                received = e
                break

        consume_task = asyncio.ensure_future(consume_one())
        # Let the subscriber register itself before publishing.
        await asyncio.sleep(0)
        await backplane.publish(booking_id, event)
        await asyncio.wait_for(consume_task, timeout=2)
        return received

    received = asyncio.run(scenario())
    assert received is not None
    assert received.eventId == "evt_01HZYTESTAAAAAAAAAAAAAAAAA"


def test_stateless_backplane_drops_a_publish_with_no_subscribers() -> None:
    async def scenario() -> None:
        backplane = StatelessBackplane()
        # No subscriber registered for this booking — publish must not raise.
        await backplane.publish("bkg_no_subscribers", _sample_event())

    asyncio.run(scenario())  # no exception == pass


def test_stateless_backplane_does_not_cross_deliver_between_bookings() -> None:
    async def scenario() -> list[HandlingEvent]:
        backplane = StatelessBackplane()
        subscription = backplane.subscribe("bkg_a", after_event_id=None)
        received: list[HandlingEvent] = []

        async def consume() -> None:
            async for e in subscription:
                received.append(e)

        consume_task = asyncio.ensure_future(consume())
        await asyncio.sleep(0)
        await backplane.publish("bkg_b", _sample_event())  # different booking — must not be received
        await asyncio.sleep(0.05)
        consume_task.cancel()
        return received

    received = asyncio.run(scenario())
    assert received == []
