#!/usr/bin/env bash
# Build-time model generation for the Part 4 Python backplane example.
# Forked from examples/part4-connection/python/scripts/generate-models.sh —
# see that script for the full rationale.
#
# `contracts/asyncapi.yaml` is the single source of truth (see
# ../../../contracts/README.md). `datamodel-code-generator`'s AsyncAPI input
# support is unreliable for this document, so this script generates from the
# extracted, self-contained JSON Schema instead (that's what
# ../../../scripts/extract-message-schema.py exists for): it inlines the
# HandlingEventType/Location/Money $refs into one Draft 2020-12 document,
# which datamodel-code-generator consumes cleanly.
#
# Output: app/models_generated.py — gitignored, regenerated on every build
# (see ../.gitignore and ../Containerfile). The app imports the generated
# `HandlingEvent` Pydantic v2 model from it; never hand-edit the output.
#
# Usage (from this directory, python/):
#   ./scripts/generate-models.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PYTHON_DIR/../../.." && pwd)"
SCHEMA="$REPO_ROOT/build/handling-event.schema.json"

echo "generate-models.sh: extracting $SCHEMA from the AsyncAPI contract ..." >&2
python3 -I "$REPO_ROOT/scripts/extract-message-schema.py" "$SCHEMA"

echo "generate-models.sh: generating app/models_generated.py ..." >&2
cd "$PYTHON_DIR"
uv run datamodel-codegen \
  --input "$SCHEMA" \
  --input-file-type jsonschema \
  --output app/models_generated.py \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.15 \
  --use-schema-description \
  --disable-timestamp \
  --formatters black isort

echo "generate-models.sh: wrote $PYTHON_DIR/app/models_generated.py" >&2
