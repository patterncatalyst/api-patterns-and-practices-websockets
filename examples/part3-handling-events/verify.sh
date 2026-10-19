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

# Set once the reconnect-check client (Step 4) is actually started; cleanup_all
# (installed as the EXIT trap right after compose_up, below) reaps it
# alongside the usual compose_down teardown, on both the success and the
# set -e failure path.
CLIENT_PID=""

cleanup_all() {
  if [[ -n "$CLIENT_PID" ]]; then
    kill "$CLIENT_PID" >/dev/null 2>&1 || true
    wait "$CLIENT_PID" 2>/dev/null || true
  fi
  compose_down "$COMPOSE_FILE" "$PROJECT" "$PROFILE"
}

# wait_for_log_pattern <file> <grep-pattern> [timeout_secs]
#
# Polls <file> for a line matching <grep-pattern> (fixed string, see `grep
# -F`), or fails loudly after timeout_secs (default 30).
wait_for_log_pattern() {
  local file="$1" pattern="$2" timeout="${3:-30}" waited=0 interval=1
  while (( waited < timeout )); do
    if grep -qF -- "$pattern" "$file" 2>/dev/null; then
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done
  echo "lib.sh: FAIL — wait_for_log_pattern: '$pattern' not found in $file within ${timeout}s" >&2
  echo "lib.sh: --- $file (tail) ---" >&2
  tail -n 40 "$file" >&2 2>/dev/null || true
  return 1
}

# wait_for_log_count <file> <grep-pattern> <min-count> [timeout_secs]
#
# Polls <file> until it contains at least <min-count> lines matching
# <grep-pattern> (fixed string), or fails loudly after timeout_secs (default
# 30). Unlike wait_for_log_pattern, this distinguishes "already happened
# once" from "happened again" — needed below to prove the client actually
# resumed receiving after reconnecting, not just that it received once
# before the forced disconnect.
wait_for_log_count() {
  local file="$1" pattern="$2" min_count="$3" timeout="${4:-30}" waited=0 interval=1 count=0
  while (( waited < timeout )); do
    count="$(grep -cF -- "$pattern" "$file" 2>/dev/null || true)"
    if (( count >= min_count )); then
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done
  echo "lib.sh: FAIL — wait_for_log_count: '$pattern' seen $count/$min_count times in $file within ${timeout}s" >&2
  echo "lib.sh: --- $file (tail) ---" >&2
  tail -n 40 "$file" >&2 2>/dev/null || true
  return 1
}

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
# Supersedes the EXIT trap compose_up just registered with one that also
# reaps the Step 4 reconnect-check client (CLIENT_PID, set by Step 4) —
# compose_down is still called with the identical arguments either way.
trap cleanup_all EXIT

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
echo "=== Step 4: client reconnect check — clients/python's consuming" \
     "client (examples/part3-handling-events/clients/python, uv-managed)" \
     "against the Python server, forced to drop and recover ==="

CLIENT_PY_DIR="$SCRIPT_DIR/clients/python"
CLIENT_LOG="$(mktemp -t handling-events-client.XXXXXX.log)"

echo "lib.sh: starting reconnect-check client -> ws://localhost:8081$CHANNEL_PATH (log: $CLIENT_LOG)" >&2
CLIENT_WS_HOST=localhost CLIENT_WS_PORT=8081 CLIENT_BOOKING_ID="$EXPECTED_BOOKING_ID" \
  uv run --project "$CLIENT_PY_DIR" python -m app.client >"$CLIENT_LOG" 2>&1 &
CLIENT_PID=$!

wait_for_log_pattern "$CLIENT_LOG" "received CUSTOMS" 30
echo "lib.sh: ok — reconnect-check client received the initial 3-event sequence" >&2

echo "lib.sh: docker compose -p $PROJECT restart python (forcing the client's connection to drop) ..." >&2
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" restart python >&2

wait_for_log_pattern "$CLIENT_LOG" "reconnecting in" 60
echo "lib.sh: ok — reconnect-check client logged a reconnect attempt after the forced disconnect" >&2

# The restarted container replays the fixture from the top on the new
# connection (see README.md — this chapter has no per-booking replay), so a
# SECOND "received CUSTOMS" line proves the client actually resumed
# receiving, not just that it retried (the first line is already in the log
# from before the forced disconnect).
wait_for_log_count "$CLIENT_LOG" "received CUSTOMS" 2 90
echo "lib.sh: ok — reconnect-check client resumed receiving after reconnecting" >&2

kill "$CLIENT_PID" >/dev/null 2>&1 || true
wait "$CLIENT_PID" 2>/dev/null || true
CLIENT_PID=""
rm -f "$CLIENT_LOG"

echo
echo "PASS — Part 3 handling-events: Quarkus and Python both implement" \
     "operations.receiveHandlingEvent identically — the same first RECEIVE" \
     "frame, field-for-field, from two independently generated" \
     "implementations of one AsyncAPI contract — and the reference" \
     "consuming client reconnects with backoff and resumes receiving after" \
     "a forced server-side disconnect."

# Explicit teardown in addition to the cleanup_all EXIT trap
# (belt-and-suspenders); compose_down is idempotent/safe to call twice.
compose_down "$COMPOSE_FILE" "$PROJECT" "$PROFILE"
