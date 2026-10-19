#!/usr/bin/env python3
"""Assert contracts/handling-event.proto matches build/handling-event.schema.json.

DRQ-025: `buf lint`/`buf breaking` can validate the `.proto` file in
isolation, but neither can see the AsyncAPI/JSON Schema side of the
contract, and proto-vs-JSON drift (a field renamed or dropped on one side
only, an enum member added out of order, a field moved between required and
optional) is the real failure mode Part 5 introduces. This script closes
that gap: it compiles the proto to a `FileDescriptorSet` with `protoc`
(a wrapper around the same descriptor-reflection API `grpcio-tools`' own
`protoc` binary exposes — no `grpcio-tools` install is required, just a
`protoc` on `PATH`), parses it with the standard `google.protobuf`
descriptor types, and diffs three things against the JSON Schema that
`scripts/extract-message-schema.py` produces from `contracts/asyncapi.yaml`:

  1. Field names       — proto `lower_snake_case` normalized to `camelCase`
                          must equal the JSON Schema's `properties` keys,
                          as a set (no field on one side only).
  2. Required/optional — a proto3 `optional` field must be exactly a JSON
                          Schema property that is absent from `required`;
                          every other proto field must be exactly a JSON
                          Schema property that IS listed in `required`.
  3. Enum               — `HandlingEventType`'s members, in declaration
                          order, after stripping the `HANDLING_EVENT_TYPE_`
                          prefix buf's ENUM_VALUE_PREFIX lint rule requires
                          (except on the zero value, which both sides spell
                          out in full: `HANDLING_EVENT_TYPE_UNSPECIFIED`),
                          must equal the JSON Schema's `eventType.enum`
                          list, in the same order.

Run with the standard library plus the system `google.protobuf` package
(no third-party install needed; isolated mode still resolves it because
it lives outside user-site):

    python3 -I scripts/check-proto-parity.py

Exits 0 and prints a one-line PASS summary when everything matches; exits 1
and prints every mismatch found (not just the first) otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROTO = REPO_ROOT / "contracts" / "handling-event.proto"
DEFAULT_SCHEMA = REPO_ROOT / "build" / "handling-event.schema.json"
MESSAGE_NAME = "HandlingEvent"
ENUM_NAME = "HandlingEventType"
ENUM_PROPERTY = "eventType"

# google.protobuf.descriptor_pb2.FieldDescriptorProto.TYPE_STRING / TYPE_ENUM,
# hardcoded rather than imported so a diff mismatch can't be masked by a
# descriptor_pb2 import failure being swallowed somewhere upstream.
TYPE_STRING = 9
TYPE_ENUM = 14


class ParityError(Exception):
    """Raised for setup failures (missing files/tools) — distinct from a
    parity mismatch, which is reported as a diff list instead of a raise."""


def pascal_to_upper_snake(name: str) -> str:
    """'HandlingEventType' -> 'HANDLING_EVENT_TYPE', matching buf's own
    ENUM_VALUE_PREFIX expectation for a PascalCase enum name."""
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name)
    return s.upper()


def snake_to_camel(name: str) -> str:
    """'occurred_at' -> 'occurredAt'."""
    head, *tail = name.split("_")
    return head + "".join(word.capitalize() for word in tail)


def compile_descriptor_set(proto_path: Path) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "handling-event.descset"
        try:
            subprocess.run(
                [
                    "protoc",
                    f"--proto_path={proto_path.parent}",
                    f"--descriptor_set_out={out_path}",
                    "--include_imports",
                    str(proto_path.name),
                ],
                cwd=proto_path.parent,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ParityError(
                "protoc not found on PATH — install it (see "
                "_plans/version-matrix.md) before running this gate"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise ParityError(
                f"protoc failed to compile {proto_path}:\n{exc.stderr}"
            ) from exc
        return out_path.read_bytes()


def load_proto_descriptor(proto_path: Path):
    from google.protobuf import descriptor_pb2

    fds = descriptor_pb2.FileDescriptorSet()
    fds.ParseFromString(compile_descriptor_set(proto_path))
    for f in fds.file:
        if f.name == proto_path.name:
            return f
    raise ParityError(f"{proto_path.name} not found in compiled descriptor set")


def extract_proto_shape(file_descriptor) -> dict:
    message = next(
        (m for m in file_descriptor.message_type if m.name == MESSAGE_NAME), None
    )
    if message is None:
        raise ParityError(f"message {MESSAGE_NAME} not found in {file_descriptor.name}")

    enum = next(
        (e for e in file_descriptor.enum_type if e.name == ENUM_NAME), None
    )
    if enum is None:
        raise ParityError(f"enum {ENUM_NAME} not found in {file_descriptor.name}")

    fields = {}
    for field in message.field:
        if field.type not in (TYPE_STRING, TYPE_ENUM):
            raise ParityError(
                f"field {field.name} has proto type {field.type}, expected "
                f"string ({TYPE_STRING}) or enum ({TYPE_ENUM}) — DRQ-025 "
                "requires occurredAt/registeredAt/amount/location/eventType "
                "to mirror the JSON value shapes exactly"
            )
        fields[snake_to_camel(field.name)] = {
            "proto_name": field.name,
            "number": field.number,
            "required": not field.proto3_optional,
        }

    prefix = pascal_to_upper_snake(ENUM_NAME) + "_"
    unspecified = prefix + "UNSPECIFIED"
    enum_values = []
    for value in enum.value:
        if value.name == unspecified:
            enum_values.append(value.name)
        elif value.name.startswith(prefix):
            enum_values.append(value.name[len(prefix):])
        else:
            raise ParityError(
                f"enum value {value.name} does not start with the expected "
                f"prefix {prefix!r} (buf's ENUM_VALUE_PREFIX lint rule should "
                "have caught this before this script ever ran)"
            )

    return {"fields": fields, "enum_values": enum_values}


def load_json_shape(schema_path: Path) -> dict:
    if not schema_path.exists():
        raise ParityError(
            f"{schema_path} does not exist — run "
            "`python3 -I scripts/extract-message-schema.py` first"
        )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    if ENUM_PROPERTY not in properties:
        raise ParityError(f"{schema_path} has no '{ENUM_PROPERTY}' property")
    enum_values = properties[ENUM_PROPERTY].get("enum")
    if not enum_values:
        raise ParityError(f"{schema_path}'s '{ENUM_PROPERTY}' property has no enum")

    fields = {
        name: {"required": name in required} for name in properties
    }
    return {"fields": fields, "enum_values": list(enum_values)}


def diff_shapes(proto_shape: dict, json_shape: dict) -> list[str]:
    diffs: list[str] = []

    proto_names = set(proto_shape["fields"])
    json_names = set(json_shape["fields"])

    only_in_proto = sorted(proto_names - json_names)
    only_in_json = sorted(json_names - proto_names)
    if only_in_proto:
        diffs.append(
            f"field(s) in {DEFAULT_PROTO.name} but missing from the JSON "
            f"Schema: {', '.join(only_in_proto)}"
        )
    if only_in_json:
        diffs.append(
            f"field(s) in the JSON Schema but missing from "
            f"{DEFAULT_PROTO.name}: {', '.join(only_in_json)}"
        )

    for name in sorted(proto_names & json_names):
        proto_required = proto_shape["fields"][name]["required"]
        json_required = json_shape["fields"][name]["required"]
        if proto_required != json_required:
            proto_desc = "required (no `optional` keyword)" if proto_required else "`optional`"
            json_desc = "required" if json_required else "not required"
            diffs.append(
                f"field '{name}': proto marks it {proto_desc} but the JSON "
                f"Schema marks it {json_desc}"
            )

    proto_enum = proto_shape["enum_values"]
    json_enum = json_shape["enum_values"]
    if proto_enum != json_enum:
        diffs.append(
            "enum HandlingEventType order/membership mismatch:\n"
            f"    proto (normalized): {proto_enum}\n"
            f"    JSON Schema:        {json_enum}"
        )

    return diffs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--proto",
        default=str(DEFAULT_PROTO),
        help=f"Path to the .proto file. Default: {DEFAULT_PROTO.relative_to(REPO_ROOT)}",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA),
        help=f"Path to the extracted JSON Schema. Default: {DEFAULT_SCHEMA.relative_to(REPO_ROOT)}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    proto_path = Path(args.proto)
    schema_path = Path(args.schema)

    try:
        file_descriptor = load_proto_descriptor(proto_path)
        proto_shape = extract_proto_shape(file_descriptor)
        json_shape = load_json_shape(schema_path)
    except ParityError as exc:
        print(f"check-proto-parity: ERROR: {exc}", file=sys.stderr)
        return 2

    diffs = diff_shapes(proto_shape, json_shape)
    if diffs:
        print(
            f"check-proto-parity: FAIL — {proto_path.name} and "
            f"{schema_path.name} disagree:",
            file=sys.stderr,
        )
        for d in diffs:
            print(f"  - {d}", file=sys.stderr)
        return 1

    print(
        f"check-proto-parity: PASS — {len(proto_shape['fields'])} fields, "
        f"{len(proto_shape['enum_values'])} enum members match "
        f"{schema_path.relative_to(REPO_ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
