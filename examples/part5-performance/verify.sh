#!/usr/bin/env bash
# examples/part5-performance/verify.sh
#
# Part 5 "Performance" example — proves, live against both running stacks,
# that the `handlingEvents` channel (contracts/asyncapi.yaml
# `operations.receiveHandlingEvent`) carries the SAME fixture replay in TWO
# wire encodings negotiated via `Sec-WebSocket-Protocol` (DRQ-026):
#
#   handling-events.v1+json      -> JSON text frames (opcode 0x1)
#   handling-events.v1+protobuf  -> Protobuf binary frames (opcode 0x2)
#
# For EACH stack (Quarkus :8090, Python :8091) this script:
#   1. Opens the JSON path, reads the first frame as TEXT, schema-validates
#      it, and asserts eventType=RECEIVE + eventId/bookingId match the
#      fixture (../part3-handling-events/fixtures/handling-events.json).
#   2. Opens the Protobuf path, captures the first frame as BINARY, decodes
#      it with a generated `handling_event_pb2` stub, converts it to the
#      same JSON-shaped dict, schema-validates THAT, and asserts every field
#      value is identical to the JSON path's — proving one message, two
#      encodings, not two different messages that happen to both validate.
#   3. Asserts the Protobuf frame is strictly smaller than the JSON frame.
#   4. Asserts the server echoed the offered subprotocol back in the `101`
#      handshake response, for both encodings.
# Finally, runs scripts/check-proto-parity.py (the static proto-vs-JSON-
# Schema drift gate) and asserts it exits 0.
#
# This part drops part4's four connection concerns (no JWT, no
# backpressure/error/heartbeat one-off containers) — see compose.yaml's
# header comment — so this harness is simpler than part4-connection's.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_lib/lib.sh
source "$SCRIPT_DIR/../_lib/lib.sh"

PROFILE=""
if [[ "${1:-}" == "--profile" ]]; then
  PROFILE="${2:-}"
fi

PROJECT="part5-performance"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
SCHEMA_FILE="$SCRIPT_DIR/../../build/handling-event.schema.json"
EXTRACT_SCRIPT="$SCRIPT_DIR/../../scripts/extract-message-schema.py"
PARITY_SCRIPT="$SCRIPT_DIR/../../scripts/check-proto-parity.py"
PROTO_FILE="$SCRIPT_DIR/../../contracts/handling-event.proto"
CONTRACTS_DIR="$SCRIPT_DIR/../../contracts"

BOOKING_ID="bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A"
CHANNEL_PATH="/ws/v1/bookings/${BOOKING_ID}/handling-events"
EXPECTED_EVENT_TYPE="RECEIVE"
EXPECTED_EVENT_ID="evt_01HZY3M1V8X4D7Q6B2N9C0T5E8"

JSON_SUBPROTOCOL="handling-events.v1+json"
PROTOBUF_SUBPROTOCOL="handling-events.v1+protobuf"

# Pinned exact match for the protoc binary this host has (confirmed live:
# `protoc --version` reports `libprotoc 36.2`, and the `protobuf` PyPI
# package publishes a matching `7.36.2` — same pin the Python sibling app's
# README/pyproject.toml declares) — avoids installing an unrelated newer/
# older protobuf runtime into the ephemeral `uv run --with` venv that a
# protoc-36.2-generated descriptor might not load cleanly against.
PROTOBUF_PY_PIN="protobuf==7.36.2"

PROTO_STUB_DIR=""

cleanup_all() {
  compose_down "$COMPOSE_FILE" "$PROJECT" "$PROFILE"
  if [[ -n "$PROTO_STUB_DIR" && -d "$PROTO_STUB_DIR" ]]; then
    rm -rf "$PROTO_STUB_DIR"
  fi
}

for tool in uv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "verify.sh: FAIL — '$tool' is required but not found on PATH" >&2
    exit 1
  fi
done

# protoc is self-provisioned (pinned release download, cached under
# examples/_lib/.bin/) rather than required pre-installed — see
# ensure_protoc's doc comment in ../_lib/lib.sh. Must run before Step 1
# (stub generation) and before Step 5 (check-proto-parity.py, which shells
# out to `protoc --descriptor_set_out`).
ensure_protoc

# ---------------------------------------------------------------------------
# decode_protobuf_frame <bin-file>
#
# Decodes a captured Protobuf-binary WebSocket frame into a JSON-shaped dict
# (camelCase keys, enum value with the HANDLING_EVENT_TYPE_ prefix stripped,
# optional fields present ONLY when HasField() is true — mirroring exactly
# what the JSON encoding would have sent) using the stub generated once into
# $PROTO_STUB_DIR below. Prints one line of compact, sort_keys JSON.
# ---------------------------------------------------------------------------
decode_protobuf_frame() {
  local bin_file="$1"
  uv run --with "$PROTOBUF_PY_PIN" python3 -I -c '
import json, sys

stub_dir, bin_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, stub_dir)
import handling_event_pb2 as pb  # generated stub — see verify.sh Step 1

with open(bin_path, "rb") as f:
    data = f.read()

msg = pb.HandlingEvent()
msg.ParseFromString(data)

ENUM_PREFIX = "HANDLING_EVENT_TYPE_"
type_name = pb.HandlingEventType.Name(msg.event_type)
if type_name.startswith(ENUM_PREFIX):
    type_name = type_name[len(ENUM_PREFIX):]

doc = {
    "eventId": msg.event_id,
    "bookingId": msg.booking_id,
    "cargoId": msg.cargo_id,
    "eventType": type_name,
    "location": msg.location,
    "occurredAt": msg.occurred_at,
    "registeredAt": msg.registered_at,
}
if msg.HasField("voyage_number"):
    doc["voyageNumber"] = msg.voyage_number
if msg.HasField("amount"):
    doc["amount"] = msg.amount

print(json.dumps(doc, sort_keys=True, separators=(",", ":")))
' "$PROTO_STUB_DIR" "$bin_file" 2>/dev/null
}

# ---------------------------------------------------------------------------
# assert_json_objects_eq <json1> <json2> <context>
#
# Parses both arguments as JSON and asserts they are deeply equal (key sets
# AND values) — used to prove the JSON-decoded frame and the
# Protobuf-decoded frame carry IDENTICAL field values, not just that both
# independently validate against the schema.
# ---------------------------------------------------------------------------
assert_json_objects_eq() {
  local a="$1" b="$2" context="${3:-json objects equal}"
  local result
  result="$(python3 -I -c '
import json, sys
a = json.loads(sys.argv[1])
b = json.loads(sys.argv[2])
if a == b:
    print("true")
else:
    print("false")
    only_a = {k: a[k] for k in a if k not in b or a[k] != b.get(k)}
    only_b = {k: b[k] for k in b if k not in a or b[k] != a.get(k)}
    print(f"lib.sh: diff — left-only/different: {only_a}", file=sys.stderr)
    print(f"lib.sh: diff — right-only/different: {only_b}", file=sys.stderr)
' "$a" "$b")"
  if [[ "$result" != "true" ]]; then
    echo "verify.sh: FAIL — ${context}: JSON and Protobuf decoded field values differ" >&2
    return 1
  fi
  echo "lib.sh: ok — ${context}: JSON and Protobuf decoded field values are identical" >&2
}

# ---------------------------------------------------------------------------
# ws_handshake_subprotocol <host> <port> <path> <offered-subprotocol>
#
# Hand-rolls the WebSocket opening handshake with Python's stdlib `socket`
# module (no WebSocket client library), offering <offered-subprotocol> in
# the `Sec-WebSocket-Protocol` request header, confirms the `101` response,
# then prints whatever the server echoed back in ITS `Sec-WebSocket-
# Protocol` response header (empty string if that header is absent). Closes
# the raw TCP connection immediately afterward without completing a
# WebSocket close handshake — this probe only cares about the upgrade
# response headers, never reads an application frame, and the server
# tearing down an abruptly-closed TCP connection is expected, not an error
# (see verify.sh's "benign broken-pipe" tolerance note below).
# ---------------------------------------------------------------------------
ws_handshake_subprotocol() {
  local host="$1" port="$2" path="$3" offered="$4"
  python3 -I -c '
import base64, os, socket, sys

host, port, path, offered = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
key = base64.b64encode(os.urandom(16)).decode()
req = (
    f"GET {path} HTTP/1.1\r\n"
    f"Host: {host}:{port}\r\n"
    "Upgrade: websocket\r\n"
    "Connection: Upgrade\r\n"
    f"Sec-WebSocket-Key: {key}\r\n"
    "Sec-WebSocket-Version: 13\r\n"
    f"Sec-WebSocket-Protocol: {offered}\r\n"
    "\r\n"
).encode()

sock = socket.create_connection((host, port), timeout=10)
sock.sendall(req)
sock.settimeout(10)
resp = b""
while b"\r\n\r\n" not in resp:
    chunk = sock.recv(4096)
    if not chunk:
        print("NOUPGRADE:no-response")
        raise SystemExit(0)
    resp += chunk
head, _, _ = resp.partition(b"\r\n\r\n")
lines = head.split(b"\r\n")
status_line = lines[0]
if b"101" not in status_line:
    print(f"NOUPGRADE:{status_line!r}")
    raise SystemExit(0)

echoed = ""
for line in lines[1:]:
    if line.lower().startswith(b"sec-websocket-protocol:"):
        echoed = line.split(b":", 1)[1].strip().decode()
        break
print(echoed)
try:
    sock.close()
except OSError:
    pass
' "$host" "$port" "$path" "$offered"
}

echo "=== Step 0: regenerate the contract-derived JSON Schema ==="
ensure_websocat
# Run via uv so PyYAML is present even on a bare CI runner whose system
# python3 has no third-party modules (self-contained, no system pip).
uv run --no-project --with pyyaml python3 -I "$EXTRACT_SCRIPT" "$SCHEMA_FILE"

echo
echo "=== Step 1: generate the Protobuf stub once (from contracts/handling-event.proto) ==="
PROTO_STUB_DIR="$(mktemp -d)"
protoc -I "$CONTRACTS_DIR" --python_out="$PROTO_STUB_DIR" "$PROTO_FILE"
if [[ ! -f "$PROTO_STUB_DIR/handling_event_pb2.py" ]]; then
  echo "verify.sh: FAIL — protoc did not produce handling_event_pb2.py in $PROTO_STUB_DIR" >&2
  exit 1
fi
echo "lib.sh: generated $PROTO_STUB_DIR/handling_event_pb2.py" >&2

echo
echo "=== Step 2: docker compose up${PROFILE:+ (--profile $PROFILE)} ==="
compose_up "$COMPOSE_FILE" "$PROJECT" "$PROFILE"
trap cleanup_all EXIT

# ---------------------------------------------------------------------------
# run_stack_performance_tests <stack> <host:port>
#
# JSON path + Protobuf path + size + subprotocol-echo assertions, against
# ONE stack. A broken-pipe log line on the server side from these single-
# frame probes (the client closes right after reading one message, which
# can race the server's own send) is benign and NOT treated as failure —
# only the assertions below decide pass/fail.
# ---------------------------------------------------------------------------
run_stack_performance_tests() {
  local stack="$1" target="$2"
  local host="${target%%:*}" port="${target##*:}"
  local base_url="ws://${target}${CHANNEL_PATH}"

  echo
  echo "=== verifying stack '$stack' at $target$CHANNEL_PATH ==="

  wait_for_ws "$target" "$CHANNEL_PATH"

  echo "--- JSON path (+json subprotocol): first frame is TEXT, schema-valid, RECEIVE ---"
  local json_frame json_bytes
  json_frame="$(websocat --protocol "$JSON_SUBPROTOCOL" -1 -n -t "$base_url" </dev/null)"
  echo "lib.sh: $stack JSON first frame: $json_frame" >&2
  schema_validate "$json_frame" "$SCHEMA_FILE"
  assert_eq "$EXPECTED_EVENT_TYPE" "$(json_field '.eventType' <<<"$json_frame")" "$stack JSON first frame eventType"
  assert_eq "$EXPECTED_EVENT_ID" "$(json_field '.eventId' <<<"$json_frame")" "$stack JSON first frame eventId"
  assert_eq "$BOOKING_ID" "$(json_field '.bookingId' <<<"$json_frame")" "$stack JSON first frame bookingId"
  json_bytes="$(printf '%s' "$json_frame" | wc -c)"
  echo "lib.sh: $stack JSON frame size: ${json_bytes} bytes" >&2

  echo "--- Protobuf path (+protobuf subprotocol): first frame is BINARY, decodes to the SAME values ---"
  local bin_file bin_bytes
  bin_file="$(mktemp)"
  websocat --protocol "$PROTOBUF_SUBPROTOCOL" -1 -n -b "$base_url" </dev/null >"$bin_file"
  bin_bytes="$(wc -c <"$bin_file")"
  echo "lib.sh: $stack Protobuf frame size: ${bin_bytes} bytes" >&2

  local proto_decoded
  proto_decoded="$(decode_protobuf_frame "$bin_file")"
  rm -f "$bin_file"
  if [[ -z "$proto_decoded" ]]; then
    echo "verify.sh: FAIL — $stack: decode_protobuf_frame produced no output" >&2
    return 1
  fi
  echo "lib.sh: $stack Protobuf frame decoded: $proto_decoded" >&2
  schema_validate "$proto_decoded" "$SCHEMA_FILE"
  assert_eq "$EXPECTED_EVENT_TYPE" "$(json_field '.eventType' <<<"$proto_decoded")" "$stack Protobuf decoded eventType"
  assert_eq "$EXPECTED_EVENT_ID" "$(json_field '.eventId' <<<"$proto_decoded")" "$stack Protobuf decoded eventId"
  assert_json_objects_eq "$json_frame" "$proto_decoded" "$stack JSON vs Protobuf field values"

  echo "--- Size: Protobuf frame strictly smaller than the JSON frame ---"
  if (( bin_bytes >= json_bytes )); then
    echo "verify.sh: FAIL — $stack: Protobuf frame (${bin_bytes}B) is not smaller than the JSON frame (${json_bytes}B)" >&2
    return 1
  fi
  local reduction_pct
  reduction_pct="$(python3 -I -c "print(f'{(1 - $bin_bytes / $json_bytes) * 100:.1f}')")"
  echo "lib.sh: ok — $stack: Protobuf (${bin_bytes}B) < JSON (${json_bytes}B), ${reduction_pct}% smaller" >&2

  echo "--- Subprotocol echo: server echoes the offered subprotocol in the 101 response ---"
  local echoed
  echoed="$(ws_handshake_subprotocol "$host" "$port" "${CHANNEL_PATH}" "$JSON_SUBPROTOCOL")"
  assert_eq "$JSON_SUBPROTOCOL" "$echoed" "$stack handshake echo (+json)"
  echoed="$(ws_handshake_subprotocol "$host" "$port" "${CHANNEL_PATH}" "$PROTOBUF_SUBPROTOCOL")"
  assert_eq "$PROTOBUF_SUBPROTOCOL" "$echoed" "$stack handshake echo (+protobuf)"

  echo "=== $stack: JSON-vs-Protobuf assertions passed ==="
}

echo
echo "=== Step 3: Quarkus — JSON vs Protobuf ==="
run_stack_performance_tests "quarkus" "localhost:8090"

echo
echo "=== Step 4: Python — JSON vs Protobuf ==="
run_stack_performance_tests "python" "localhost:8091"

echo
echo "=== Step 5: proto-vs-JSON-Schema parity smoke (scripts/check-proto-parity.py) ==="
if ! ( cd "$SCRIPT_DIR/../.." && uv run --no-project --with "$PROTOBUF_PY_PIN" python3 -I scripts/check-proto-parity.py ); then
  echo "verify.sh: FAIL — scripts/check-proto-parity.py did not exit 0" >&2
  exit 1
fi
echo "lib.sh: ok — check-proto-parity.py exited 0" >&2

echo
echo "PASS — Part 5 performance: Quarkus and Python both negotiate" \
     "handling-events.v1+json (JSON text) and handling-events.v1+protobuf" \
     "(Protobuf binary) against the SAME contract, decode to IDENTICAL" \
     "field values on both encodings, the Protobuf frame is strictly" \
     "smaller than the JSON frame, the server echoes the negotiated" \
     "subprotocol on both stacks, and the proto/JSON-Schema parity gate" \
     "passes."

# Explicit teardown in addition to the cleanup_all EXIT trap
# (belt-and-suspenders); compose_down/rm -rf are idempotent.
cleanup_all
