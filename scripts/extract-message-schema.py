#!/usr/bin/env python3
"""Extract a standalone JSON Schema for HandlingEvent from the AsyncAPI contract.

`contracts/asyncapi.yaml` is the single source of truth (see
`contracts/README.md`); the `HandlingEvent` message's payload schema lives in
`components.schemas.HandlingEvent` and references three sibling schemas by
`$ref` (`HandlingEventType`, `Location`, `Money`). This script inlines those
refs into one self-contained JSON Schema Draft 2020-12 document — no external
`$ref`s left — so a drift gate, a client generator, or a test runner can
consume `HandlingEvent` without also parsing the whole AsyncAPI document.

Run with the standard library's isolated mode plus PyYAML (the only
dependency, already used to author the contract itself):

    python3 -I scripts/extract-message-schema.py
    python3 -I scripts/extract-message-schema.py -            # stdout
    python3 -I scripts/extract-message-schema.py build/out.json

Output is build-time only (gitignored, see `build/`, DRQ-018) and
deterministic (sorted keys, 2-space indent, trailing newline) so repeated
runs diff cleanly for a drift gate.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = REPO_ROOT / "contracts" / "asyncapi.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "build" / "handling-event.schema.json"
MESSAGE_NAME = "HandlingEvent"
SCHEMA_REF_PREFIX = "#/components/schemas/"


def load_contract(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    if not isinstance(doc, dict):
        raise ValueError(f"{path}: expected a YAML mapping at the document root")
    return doc


def _inline(node, schemas: dict, expanding: frozenset[str] = frozenset()):
    """Recursively replace `$ref: '#/components/schemas/<Name>'` with a deep
    copy of the referenced schema, resolved the same way, so the result has
    no remaining external `$ref`s. Sibling keys alongside a `$ref` (none in
    this contract today, but valid under Draft 2020-12) win over the inlined
    schema's keys of the same name.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            if not ref.startswith(SCHEMA_REF_PREFIX):
                raise ValueError(f"Unsupported $ref outside components.schemas: {ref}")
            name = ref[len(SCHEMA_REF_PREFIX):]
            if name not in schemas:
                raise KeyError(f"$ref target not found in components.schemas: {name}")
            if name in expanding:
                raise ValueError(f"Cyclic $ref detected while expanding: {name}")
            target = _inline(copy.deepcopy(schemas[name]), schemas, expanding | {name})
            merged = dict(target)
            for key, value in node.items():
                if key == "$ref":
                    continue
                merged[key] = _inline(value, schemas, expanding)
            return merged
        return {key: _inline(value, schemas, expanding) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline(item, schemas, expanding) for item in node]
    return node


def extract_handling_event_schema(contract: dict) -> dict:
    schemas = contract.get("components", {}).get("schemas", {})
    if MESSAGE_NAME not in schemas:
        raise KeyError(
            f"components.schemas.{MESSAGE_NAME} not found in the contract"
        )
    resolved = _inline(copy.deepcopy(schemas[MESSAGE_NAME]), schemas, frozenset({MESSAGE_NAME}))
    if not isinstance(resolved, dict):
        raise ValueError(f"components.schemas.{MESSAGE_NAME} did not resolve to a mapping")

    schema: dict = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": MESSAGE_NAME,
    }
    schema.update(resolved)
    return schema


def render(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract a self-contained JSON Schema (Draft 2020-12) for the "
            "HandlingEvent message from contracts/asyncapi.yaml."
        )
    )
    parser.add_argument(
        "output",
        nargs="?",
        default=str(DEFAULT_OUTPUT),
        help=(
            "Path to write the extracted schema to (parent directories are "
            f"created as needed). Pass '-' to print to stdout instead. "
            f"Default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)}"
        ),
    )
    parser.add_argument(
        "--contract",
        default=str(DEFAULT_CONTRACT),
        help=f"Path to the AsyncAPI contract. Default: {DEFAULT_CONTRACT.relative_to(REPO_ROOT)}",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    contract_path = Path(args.contract)
    contract = load_contract(contract_path)
    schema = extract_handling_event_schema(contract)
    text = render(schema)

    if args.output == "-":
        sys.stdout.write(text)
        return 0

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    print(f"Wrote {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
