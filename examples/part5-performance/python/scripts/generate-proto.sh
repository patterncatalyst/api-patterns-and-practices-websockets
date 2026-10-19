#!/usr/bin/env bash
# Build-time Protobuf stub generation for the Part 5 Python performance
# example (Ch19, DRQ-025). `contracts/handling-event.proto` is the single
# source of truth for the binary encoding (see ../../../contracts/README.md);
# this script compiles it with `grpcio-tools`' bundled `protoc` (no gRPC
# service on this site — only the message-class generator is used, see
# _plans/version-matrix.md) into a plain Python module plus a `.pyi` stub.
#
# Output: app/handling_event_pb2.py + app/handling_event_pb2.pyi — gitignored,
# regenerated on every build (see ../.gitignore and ../Containerfile). The
# app imports the generated `HandlingEvent`/`HandlingEventType` symbols from
# it; never hand-edit the output.
#
# The JSON side of this example generates separately — see
# ./generate-models.sh.
#
# Usage (from this directory, python/):
#   ./scripts/generate-proto.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PYTHON_DIR/../../.." && pwd)"
CONTRACTS_DIR="$REPO_ROOT/contracts"

echo "generate-proto.sh: generating app/handling_event_pb2.py(+.pyi) from $CONTRACTS_DIR/handling-event.proto ..." >&2
cd "$PYTHON_DIR"
uv run python -m grpc_tools.protoc \
  -I "$CONTRACTS_DIR" \
  --python_out=app \
  --pyi_out=app \
  "$CONTRACTS_DIR/handling-event.proto"

echo "generate-proto.sh: wrote $PYTHON_DIR/app/handling_event_pb2.py and .pyi" >&2
