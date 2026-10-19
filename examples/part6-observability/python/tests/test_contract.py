"""Part 6 example — conformance + observability unit tests.

Forked from examples/part4-connection/python/tests/test_contract.py. The
first block (schema conformance) is unchanged in spirit — this example
replays the identical shared fixture, so the same invariants hold, run
against `build/handling-event.schema.json` (the self-contained JSON Schema
extracted from contracts/asyncapi.yaml by
../../../scripts/extract-message-schema.py — regenerate it before running
this test, see README.md). The second block is new: pure-Python unit tests
(no socket) for this chapter's two observability primitives —
`app/ws_server.py`'s trace-id log line and `app/metrics.py`'s delivered-
events counter — that don't require a live OTLP collector or a running WS
server to verify.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from opentelemetry import trace

from app.feed import load_fixture, sequence
from app.mapper import to_wire_frame
from app.metrics import HANDLING_EVENTS_DELIVERED_TOTAL
from app.models_generated import HandlingEvent
from app.ws_server import CONNECTION_SPAN_NAME, INSTANCE_NAME, _log_trace_id, tracer

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
SCHEMA_PATH = REPO_ROOT / "build" / "handling-event.schema.json"

# Mirrors the SHARED OTEL CONVENTIONS log-line shape (identical on the
# Quarkus sibling — see app/ws_server.py's `_log_trace_id` docstring):
#   otel.trace_id=<32-hex> span=ws.handling-events.connection bookingId=<id> instance=<name>
TRACE_ID_LOG_LINE = re.compile(
    r"^otel\.trace_id=[0-9a-f]{32} span=ws\.handling-events\.connection "
    r"bookingId=\S+ instance=\S+$"
)


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
# Schema conformance (shared fixture, forked from Part 3/4's test suite)
# ---------------------------------------------------------------------------


def test_fixture_is_three_events_in_order() -> None:
    fixture = load_fixture()
    assert [e["eventType"] for e in fixture] == ["RECEIVE", "LOAD", "CUSTOMS"]


def test_mapped_frames_validate_against_schema(validator: Draft202012Validator) -> None:
    frames = [to_wire_frame(event) for event in sequence()]
    assert len(frames) == 3
    for frame in frames:
        doc = json.loads(frame)
        errors = list(validator.iter_errors(doc))
        assert not errors, f"{frame} failed schema validation: {errors}"


def test_first_frame_is_the_receive_event_matching_the_fixture() -> None:
    fixture = load_fixture()
    frames = [to_wire_frame(event) for event in sequence()]
    first = json.loads(frames[0])
    assert first == fixture[0]
    assert first["eventType"] == "RECEIVE"


def test_generated_model_round_trips_fixture_values_exactly() -> None:
    for raw in load_fixture():
        model = HandlingEvent.model_validate(raw)
        dumped = json.loads(to_wire_frame(model))
        assert dumped == raw, f"round-trip drift for {raw['eventId']}: {dumped} != {raw}"


def test_sequence_events_validate_as_generated_model_instances() -> None:
    events = sequence()
    assert len(events) == 3
    assert all(isinstance(e, HandlingEvent) for e in events)
    assert [e.eventType.value for e in events] == ["RECEIVE", "LOAD", "CUSTOMS"]


# ---------------------------------------------------------------------------
# Ch23 observability — app/ws_server.py's trace-id log line + app/metrics.py
# ---------------------------------------------------------------------------


def test_trace_id_log_line_matches_the_shared_otel_convention(caplog: pytest.LogCaptureFixture) -> None:
    """A manual span (no live collector required — the SDK's default
    TracerProvider still assigns a real random trace id even with no
    exporter configured) must produce the EXACT log-line shape both stacks'
    verify.sh greps for.
    """
    with caplog.at_level(logging.INFO, logger="handling-events-python"):
        with tracer.start_as_current_span(CONNECTION_SPAN_NAME) as span:
            _log_trace_id(span, "bkg_test")

    matching = [r.message for r in caplog.records if TRACE_ID_LOG_LINE.match(r.message)]
    assert matching, f"no log record matched the trace-id line shape; got: {[r.message for r in caplog.records]}"
    assert "bookingId=bkg_test" in matching[0]
    assert f"instance={INSTANCE_NAME}" in matching[0]


def test_trace_id_in_log_line_matches_the_spans_own_trace_id(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="handling-events-python"):
        with tracer.start_as_current_span(CONNECTION_SPAN_NAME) as span:
            expected_trace_id = format(span.get_span_context().trace_id, "032x")
            _log_trace_id(span, "bkg_test")

    logged = next(r.message for r in caplog.records if TRACE_ID_LOG_LINE.match(r.message))
    assert f"otel.trace_id={expected_trace_id}" in logged


def _counter_value() -> float:
    """Reads the counter's current value via the public Collector protocol
    (`collect()`), rather than reaching into the private `_value` attribute
    — the same thing `/metrics` (`generate_latest()`, see app/http_app.py)
    does under the hood. A Counter's `collect()` yields two samples (the
    `_total` value itself and a `_created` timestamp); only the former is
    the delivered-events count.
    """
    (metric,) = HANDLING_EVENTS_DELIVERED_TOTAL.collect()
    (sample,) = (s for s in metric.samples if s.name.endswith("_total"))
    return sample.value


def test_handling_events_delivered_total_increments_per_delivered_event() -> None:
    before = _counter_value()
    for _ in sequence():
        HANDLING_EVENTS_DELIVERED_TOTAL.inc()
    after = _counter_value()
    assert after - before == 3
