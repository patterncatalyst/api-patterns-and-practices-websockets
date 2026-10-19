"""Part 5 example — maps a validated `HandlingEvent` (the generated Pydantic
model, app/models_generated.py) to its Protobuf binary twin
(contracts/handling-event.proto, app/handling_event_pb2.py) and back
(DRQ-025).

Both directions operate on PLAIN JSON-MODE VALUES
(`model.model_dump(mode="json")`) rather than native Python types (datetime,
Decimal, ...), so every value placed into — or read back out of — the proto
message is the EXACT same string the JSON encoding already carries
(RFC-3339 date-time strings, decimal-string Money) — see
`contracts/handling-event.proto`'s module docstring on why timestamps and
amount stay plain `string` fields instead of typed Protobuf equivalents.
`proto_to_dict` produces a dict with the same keys/shape
`model_dump(mode="json")` would, so the round-trip test
(tests/test_contract.py) can validate a DECODED Protobuf message against
`build/handling-event.schema.json` — the same JSON Schema the JSON encoding
is validated against — without a second, proto-specific schema.
"""
from __future__ import annotations

from app.handling_event_pb2 import HandlingEvent as HandlingEventProto
from app.handling_event_pb2 import HandlingEventType as HandlingEventTypeProto
from app.models_generated import HandlingEvent as HandlingEventModel

# Proto enum members are prefixed per buf's ENUM_VALUE_PREFIX lint rule
# (contracts/handling-event.proto); the AsyncAPI contract and the generated
# Pydantic model both use the bare member name (RECEIVE, LOAD, ...). This is
# the same prefix scripts/check-proto-parity.py strips/re-adds when diffing
# the two contracts' enum shapes.
_PROTO_ENUM_PREFIX = "HANDLING_EVENT_TYPE_"

# Optional fields: a proto3 `optional` keyword gives each one explicit wire
# presence (HasField works), mirroring the JSON Schema's required/optional
# split (DRQ-025) — see scripts/check-proto-parity.py's "required/optional"
# check.
_OPTIONAL_FIELDS = ("voyageNumber", "amount")


def _event_type_to_proto(value: str) -> int:
    return HandlingEventTypeProto.Value(_PROTO_ENUM_PREFIX + value)


def _event_type_from_proto(value: int) -> str:
    name = HandlingEventTypeProto.Name(value)
    return name[len(_PROTO_ENUM_PREFIX) :]


def to_proto(event: HandlingEventModel) -> HandlingEventProto:
    """Validated model -> Protobuf message, field VALUES byte-for-byte
    identical to the JSON encoding."""
    data = event.model_dump(mode="json", exclude_none=True)
    kwargs = {
        "event_id": data["eventId"],
        "booking_id": data["bookingId"],
        "cargo_id": data["cargoId"],
        "event_type": _event_type_to_proto(data["eventType"]),
        "location": data["location"],
        "occurred_at": data["occurredAt"],
        "registered_at": data["registeredAt"],
    }
    if "voyageNumber" in data:
        kwargs["voyage_number"] = data["voyageNumber"]
    if "amount" in data:
        kwargs["amount"] = data["amount"]
    return HandlingEventProto(**kwargs)


def proto_to_dict(proto: HandlingEventProto) -> dict:
    """Decoded Protobuf message -> a plain dict with the same keys/shape
    `HandlingEventModel.model_dump(mode="json")` produces — the shape
    `build/handling-event.schema.json` validates."""
    data = {
        "eventId": proto.event_id,
        "bookingId": proto.booking_id,
        "cargoId": proto.cargo_id,
        "eventType": _event_type_from_proto(proto.event_type),
        "location": proto.location,
        "occurredAt": proto.occurred_at,
        "registeredAt": proto.registered_at,
    }
    if proto.HasField("voyage_number"):
        data["voyageNumber"] = proto.voyage_number
    if proto.HasField("amount"):
        data["amount"] = proto.amount
    return data
