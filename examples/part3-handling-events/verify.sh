#!/usr/bin/env bash
# examples/part3-handling-events/verify.sh
#
# Part 3 "Handling It" example — the reference both-stack implementation of
# `operations.receiveHandlingEvent` (contracts/asyncapi.yaml
# `channels.handlingEvents`): one WebSocket connection per booking,
# server-to-client push only. Both the Quarkus and the Python stack must
# replay the IDENTICAL, DETERMINISTIC 3-event fixture
# (fixtures/handling-events.json) — asserted on FIELD SEMANTICS against the
# fixture AND against the contract-derived JSON Schema, not just "the socket
# upgraded". See README.md for the full event sequence.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_lib/lib.sh
source "$SCRIPT_DIR/../_lib/lib.sh"

# --profile <name> is optional (e.g. `./verify.sh --profile observability`)
# and brings up compose.yaml's opt-in `lgtm` service alongside the app
# stack — it does not change which assertions run; the two app stacks are
# always verified the same way either way.
PROFILE=""
if [[ "${1:-}" == "--profile" ]]; then
  PROFILE="${2:-}"
fi

PROJECT="part3-handling-events"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
SCHEMA_FILE="$SCRIPT_DIR/../../build/handling-event.schema.json"
EXTRACT_SCRIPT="$SCRIPT_DIR/../../scripts/extract-message-schema.py"

# First fixture event (fixtures/handling-events.json[0]) — the RECEIVE event
# both stacks must push as the FIRST frame on any booking connection (see
# README.md's event table).
EXPECTED_EVENT_ID="evt_01HZY3M1V8X4D7Q6B2N9C0T5E8"
EXPECTED_BOOKING_ID="bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A"
EXPECTED_CARGO_ID="crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5"
EXPECTED_EVENT_TYPE="RECEIVE"
EXPECTED_LOCATION="USNYC"

CHANNEL_PATH="/ws/v1/bookings/${EXPECTED_BOOKING_ID}/handling-events"

echo "=== Step 0: regenerate the contract-derived JSON Schema ==="
ensure_websocat
python3 -I "$EXTRACT_SCRIPT" "$SCHEMA_FILE"

declare -A FRAME_FIELD

# run_stack_tests <stack> <host:port>
#
# Captures the first pushed frame, validates it against the extracted
# schema, asserts it matches fixture[0] field-by-field, and stashes each
# field in FRAME_FIELD["<stack> <field>"] for the cross-stack comparison
# that follows.
run_stack_tests() {
  local stack="$1" target="$2"

  echo
  echo "=== verifying stack '$stack' at $target$CHANNEL_PATH ==="

  wait_for_ws "$target" "$CHANNEL_PATH"

  local frame
  frame="$(ws_first_frame "ws://${target}${CHANNEL_PATH}")"
  echo "lib.sh: $stack first frame: $frame" >&2

  schema_validate "$frame" "$SCHEMA_FILE"

  local event_id event_type booking_id cargo_id location occurred_at registered_at
  event_id="$(json_field '.eventId' <<<"$frame")"
  event_type="$(json_field '.eventType' <<<"$frame")"
  booking_id="$(json_field '.bookingId' <<<"$frame")"
  cargo_id="$(json_field '.cargoId' <<<"$frame")"
  location="$(json_field '.location' <<<"$frame")"
  occurred_at="$(json_field '.occurredAt' <<<"$frame")"
  registered_at="$(json_field '.registeredAt' <<<"$frame")"

  assert_eq "$EXPECTED_EVENT_TYPE" "$event_type" "$stack event[0].eventType"
  assert_eq "$EXPECTED_EVENT_ID" "$event_id" "$stack event[0].eventId"
  assert_eq "$EXPECTED_BOOKING_ID" "$booking_id" "$stack event[0].bookingId"
  assert_eq "$EXPECTED_CARGO_ID" "$cargo_id" "$stack event[0].cargoId"
  assert_eq "$EXPECTED_LOCATION" "$location" "$stack event[0].location"

  FRAME_FIELD["$stack eventId"]="$event_id"
  FRAME_FIELD["$stack eventType"]="$event_type"
  FRAME_FIELD["$stack bookingId"]="$booking_id"
  FRAME_FIELD["$stack cargoId"]="$cargo_id"
  FRAME_FIELD["$stack location"]="$location"
  FRAME_FIELD["$stack occurredAt"]="$occurred_at"
  FRAME_FIELD["$stack registeredAt"]="$registered_at"

  echo "=== $stack: all assertions passed ==="
}

echo
echo "=== Step 1: docker compose up${PROFILE:+ (--profile $PROFILE)} ==="
compose_up "$COMPOSE_FILE" "$PROJECT" "$PROFILE"

echo
echo "=== Step 2: verify both stacks individually ==="
run_stack_tests "quarkus" "localhost:8080"
run_stack_tests "python" "localhost:8081"

echo
echo "=== Step 3: cross-stack agreement (parsed fields, not raw bytes — key" \
     "order differs between Jackson and Pydantic, and that's fine) ==="
for field in eventId eventType bookingId cargoId location occurredAt registeredAt; do
  assert_eq "${FRAME_FIELD["quarkus $field"]}" "${FRAME_FIELD["python $field"]}" \
    "quarkus vs python event[0].$field"
done

echo
echo "PASS — Part 3 handling-events: Quarkus and Python both implement" \
     "operations.receiveHandlingEvent identically — the same first RECEIVE" \
     "frame, field-for-field, from two independently generated" \
     "implementations of one AsyncAPI contract."

# Explicit teardown in addition to lib.sh's EXIT trap (belt-and-suspenders);
# compose_down is idempotent/safe to call twice.
compose_down "$COMPOSE_FILE" "$PROJECT" "$PROFILE"
