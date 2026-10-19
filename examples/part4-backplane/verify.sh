#!/usr/bin/env bash
# examples/part4-backplane/verify.sh
#
# Part 4 "Production Concerns" backplane example — proves, live against
# BOTH stacks (Quarkus WebSockets Next + Python native `websockets`/FastAPI)
# AND both backplanes (Kafka, Redis), the three scenarios this example
# centers on (see ./PROTOCOL.md for the full wire/behavior contract):
#
#   Ch15 stateless gap   — default profile, single instance: a disconnected
#                          client's gap-era event is LOST (no broker, no
#                          history).
#   Ch16 kafka replay    — --profile kafka: the same gap-era event IS
#                          delivered after reconnect (replay via the shared
#                          Kafka topic), with no more than the documented
#                          benign replay-vs-live duplicate (see Step 2 below).
#   Ch18 scale-out fan-out (DRQ-005) — a client connected to instance A
#                          receives an event injected through instance B's
#                          `POST /internal/.../handling-events`, proven once
#                          on `--profile kafka` and once on `--profile
#                          redis`, for BOTH stacks.
#
# compose.yaml always starts FOUR app instances (quarkus-a/b, python-a/b);
# the active profile only controls which BROKER container comes up, and the
# BACKPLANE_MODE env var (set by this script before each `docker compose
# up`) controls which Backplane implementation every instance selects — see
# compose.yaml's header comment for why those two knobs are kept separate.
#
# Each scenario below uses its OWN freshly generated bookingId (gen_id) even
# though all four instances share ONE physical Kafka topic/Redis instance —
# this is what keeps the Kafka-replay and the two fan-out proofs from
# cross-contaminating each other (and the two stacks from contaminating each
# other) on that shared broker: every Backplane implementation filters
# strictly by bookingId.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_lib/lib.sh
source "$SCRIPT_DIR/../_lib/lib.sh"

PROJECT="part4-backplane"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
SCHEMA_FILE="$SCRIPT_DIR/../../build/handling-event.schema.json"
EXTRACT_SCRIPT="$SCRIPT_DIR/../../scripts/extract-message-schema.py"

# The fixture's own 3rd (CUSTOMS) event id — see
# examples/part3-handling-events/fixtures/handling-events.json. The seed
# sequence is delivered unconditionally on every connection, in every mode,
# regardless of the URL's bookingId (see each app's "Design note" in its
# README) — so this constant is the correct `?afterEventId=` value for every
# reconnect test below no matter which generated bookingId that test uses.
LAST_SEED_EVENT_ID="evt_01HZY3M3X0Z6F9S8D4Q1E2V7G0"

# A fixed, valid cargoId reused for every injected test event — the schema
# requires one, but its value carries no test meaning here.
CARGO_ID="crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5"

# Host targets for the four always-up instances (compose.yaml).
QUARKUS_A_WS="localhost:8080";  QUARKUS_A_HTTP="localhost:8080"
QUARKUS_B_WS="localhost:8083";  QUARKUS_B_HTTP="localhost:8083"
PYTHON_A_WS="localhost:8081";   PYTHON_A_HTTP="localhost:8082"
PYTHON_B_WS="localhost:8084";   PYTHON_B_HTTP="localhost:8085"

CONTAINER_QUARKUS_A="part4-backplane-quarkus-a"
CONTAINER_QUARKUS_B="part4-backplane-quarkus-b"
CONTAINER_PYTHON_A="part4-backplane-python-a"
CONTAINER_PYTHON_B="part4-backplane-python-b"

INSTANCE_QUARKUS_A="quarkus-a"; INSTANCE_QUARKUS_B="quarkus-b"
INSTANCE_PYTHON_A="python-a";   INSTANCE_PYTHON_B="python-b"

# ---------------------------------------------------------------------------
# Stage lifecycle: three sequential `docker compose up`/`down` cycles in ONE
# self-contained run (stateless, then kafka, then redis) — CURRENT_PROFILE
# tracks whichever is active so the single EXIT trap (cleanup_all) always
# tears down the right one, and BG_PIDS tracks every ws_connect_bg client so
# a failure mid-scenario never leaks a background websocat process.
# ---------------------------------------------------------------------------
CURRENT_PROFILE=""
BG_PIDS=()

cleanup_all() {
  local pid
  for pid in "${BG_PIDS[@]}"; do
    [[ -n "$pid" ]] && kill "$pid" >/dev/null 2>&1 || true
  done
  for pid in "${BG_PIDS[@]}"; do
    [[ -n "$pid" ]] && wait "$pid" 2>/dev/null || true
  done
  BG_PIDS=()
  compose_down "$COMPOSE_FILE" "$PROJECT" "$CURRENT_PROFILE"
}
trap cleanup_all EXIT

start_stage() {
  local profile="$1" mode="$2"
  CURRENT_PROFILE="$profile"

  # compose.yaml's KAFKA_BOOTSTRAP_SERVERS/REDIS_URL default to
  # localhost:9092 / redis://localhost:6379/0 — resolvable-but-unreachable,
  # which both apps' READMEs document as safe even in stateless mode. Only
  # point them at the real broker hostname for the stage that actually
  # brings that broker up — confirmed live: handing Quarkus's always-wired
  # Kafka consumer an UNRESOLVABLE hostname (e.g. `kafka` when no such
  # container/DNS entry exists in this stage) crashes the app at startup
  # with `ConfigException: No resolvable bootstrap urls`, a hard failure,
  # not the soft "unreachable but resolvable" case.
  local kafka_servers="localhost:9092" redis_url="redis://localhost:6379/0"
  if [[ "$profile" == "kafka" ]]; then
    kafka_servers="kafka:9092"
  elif [[ "$profile" == "redis" ]]; then
    redis_url="redis://redis:6379/0"
  fi

  echo
  echo "=== docker compose up (profile='${profile:-<none>}' BACKPLANE_MODE=$mode) ==="
  BACKPLANE_MODE="$mode" KAFKA_BOOTSTRAP_SERVERS="$kafka_servers" REDIS_URL="$redis_url" \
    compose_up "$COMPOSE_FILE" "$PROJECT" "$profile"
  trap cleanup_all EXIT # compose_up installs its own trap; reassert ours

  if [[ "$profile" == "kafka" ]]; then
    wait_for_tcp localhost 9092 90
  elif [[ "$profile" == "redis" ]]; then
    wait_for_tcp localhost 6379 60
  fi

  # Readiness probe — any valid-shaped bookingId works (the seed feed
  # doesn't filter by it); this only proves each listener accepts the WS
  # upgrade before any scenario starts hitting it.
  local ready_path
  ready_path="$(channel_path bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A)"
  wait_for_ws "$QUARKUS_A_WS" "$ready_path"
  wait_for_ws "$QUARKUS_B_WS" "$ready_path"
  wait_for_ws "$PYTHON_A_WS" "$ready_path"
  wait_for_ws "$PYTHON_B_WS" "$ready_path"
}

end_stage() {
  compose_down "$COMPOSE_FILE" "$PROJECT" "$CURRENT_PROFILE"
  CURRENT_PROFILE=""
}

# ---------------------------------------------------------------------------
# Helpers specific to this verify.sh
# ---------------------------------------------------------------------------

# gen_id <prefix> — a fresh id matching the contract's `^(evt|bkg|crg)_[0-9A-Za-z]{26}$`
# patterns (contracts/asyncapi.yaml): <prefix> + the first 26 hex chars of a
# UUID4 (a subset of [0-9A-Za-z], so always pattern-valid).
gen_id() {
  python3 -I -c "import uuid, sys; print(sys.argv[1] + uuid.uuid4().hex[:26])" "$1"
}

channel_path() {
  echo "/ws/v1/bookings/$1/handling-events"
}

# inject_event <host:port> <bookingId> <eventId> [eventType] [location]
#
# POSTs a schema-valid HandlingEvent to <host:port>'s
# `/internal/bookings/{bookingId}/handling-events` inject endpoint
# (PROTOCOL.md "Inject endpoint") and asserts the `202 Accepted` response.
inject_event() {
  local target="$1" booking_id="$2" event_id="$3" event_type="${4:-DELIVERED}" location="${5:-NLRTM}"
  local now body code
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  body=$(printf '{"eventId":"%s","bookingId":"%s","cargoId":"%s","eventType":"%s","location":"%s","occurredAt":"%s","registeredAt":"%s"}' \
    "$event_id" "$booking_id" "$CARGO_ID" "$event_type" "$location" "$now" "$now")
  code="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
    "http://${target}/internal/bookings/${booking_id}/handling-events" \
    -H 'Content-Type: application/json' -d "$body")"
  echo "lib.sh: inject eventId=$event_id bookingId=$booking_id via $target -> HTTP $code" >&2
  assert_eq "202" "$code" "inject $event_id via $target accepted"
}

# wait_for_docker_log_pattern <container> <fixed-string-pattern> [timeout_secs]
#
# Like lib.sh's wait_for_log_pattern, but polls `docker logs <container>`
# instead of a file — used for the Ch18 proof's SERVER-side assertion
# ("instance A's own log shows it delivering"), where the only place that
# log line exists is the container's stdout, not a client-observed frame.
wait_for_docker_log_pattern() {
  local container="$1" pattern="$2" timeout="${3:-30}" waited=0 interval=1
  while (( waited < timeout )); do
    if docker logs "$container" 2>&1 | grep -qF -- "$pattern"; then
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done
  echo "lib.sh: FAIL — wait_for_docker_log_pattern: '$pattern' not found in $container logs within ${timeout}s" >&2
  docker logs --tail 40 "$container" >&2 2>&1 || true
  return 1
}

# ---------------------------------------------------------------------------
# Scenario 1 (Ch15): stateless gap — connect, confirm 3 seed frames,
# disconnect, inject a gap event, reconnect with ?afterEventId=<last seed
# id>, assert the gap event is NOT delivered (no broker => no history).
# ---------------------------------------------------------------------------
run_ch15_stateless_gap() {
  local stack="$1" ws_target="$2" http_target="$3" booking_id="$4"
  local path; path="$(channel_path "$booking_id")"

  echo
  echo "--- $stack Ch15 stateless gap (bookingId=$booking_id) ---"

  local frames last_frame last_event_id
  frames="$(ws_frames_n "ws://${ws_target}${path}" 3 20)"
  last_frame="$(tail -n1 <<<"$frames")"
  last_event_id="$(json_field '.eventId' <<<"$last_frame")"
  assert_eq "$LAST_SEED_EVENT_ID" "$last_event_id" "$stack ch15: 3rd seed frame is the fixture's CUSTOMS event"
  echo "lib.sh: ok — $stack ch15: connected, received 3 seed frames, disconnected" >&2

  local gap_event_id
  gap_event_id="$(gen_id evt_)"
  inject_event "$http_target" "$booking_id" "$gap_event_id"

  local log pid
  log="$(mktemp -t "part4-backplane-ch15-${stack}.XXXXXX.log")"
  pid="$(ws_connect_bg "ws://${ws_target}${path}?afterEventId=${LAST_SEED_EVENT_ID}" "$log")"
  BG_PIDS+=("$pid")

  wait_for_log_count "$log" '"eventType":"CUSTOMS"' 1 20
  # Grace window: if stateless mode were (incorrectly) delivering the gap
  # event, it would show up within this short wait — there is no live
  # producer left to eventually deliver it later.
  sleep 3

  if grep -qF "\"eventId\":\"${gap_event_id}\"" "$log"; then
    echo "lib.sh: FAIL — $stack ch15: gap event $gap_event_id WAS delivered after reconnect (stateless must lose it)" >&2
    cat "$log" >&2
    return 1
  fi
  echo "lib.sh: ok — $stack ch15: gap event $gap_event_id NOT delivered after reconnect (stateless loses gap-era events, as spec'd)" >&2

  kill "$pid" >/dev/null 2>&1 || true
  wait "$pid" 2>/dev/null || true
  rm -f "$log"
}

# ---------------------------------------------------------------------------
# Scenario 2 (Ch16): kafka replay — same connect/disconnect/inject/reconnect
# sequence as Ch15, but this time the gap event MUST be delivered after
# reconnect. PROTOCOL.md documents a narrow, benign replay-vs-live race (the
# newly reconnected client can, in rare timing, see the SAME event once from
# the replay burst and once from the live-tail push); verify.sh dedups by
# eventId per the project's harness convention — a raw frame count of 1 OR 2
# for this one eventId both count as PASS (0 = lost, >2 = a real bug).
# ---------------------------------------------------------------------------
run_ch16_kafka_replay() {
  local stack="$1" ws_target="$2" http_target="$3" booking_id="$4"
  local path; path="$(channel_path "$booking_id")"

  echo
  echo "--- $stack Ch16 kafka replay (bookingId=$booking_id) ---"

  local frames last_frame last_event_id
  frames="$(ws_frames_n "ws://${ws_target}${path}" 3 20)"
  last_frame="$(tail -n1 <<<"$frames")"
  last_event_id="$(json_field '.eventId' <<<"$last_frame")"
  assert_eq "$LAST_SEED_EVENT_ID" "$last_event_id" "$stack ch16: 3rd seed frame is the fixture's CUSTOMS event"
  echo "lib.sh: ok — $stack ch16: connected, received 3 seed frames, disconnected" >&2

  local gap_event_id
  gap_event_id="$(gen_id evt_)"
  inject_event "$http_target" "$booking_id" "$gap_event_id"

  local log pid
  log="$(mktemp -t "part4-backplane-ch16-${stack}.XXXXXX.log")"
  pid="$(ws_connect_bg "ws://${ws_target}${path}?afterEventId=${LAST_SEED_EVENT_ID}" "$log")"
  BG_PIDS+=("$pid")

  wait_for_log_count "$log" '"eventType":"CUSTOMS"' 1 20
  wait_for_log_pattern "$log" "\"eventId\":\"${gap_event_id}\"" 40
  # Grace window to let a benign duplicate (see function comment) surface
  # before counting, so the count below is trustworthy either way.
  sleep 3

  local raw_count
  raw_count="$(grep -cF "\"eventId\":\"${gap_event_id}\"" "$log" || true)"
  if (( raw_count < 1 )); then
    echo "lib.sh: FAIL — $stack ch16: gap event $gap_event_id was NOT delivered after reconnect" >&2
    cat "$log" >&2
    return 1
  fi
  if (( raw_count > 2 )); then
    echo "lib.sh: FAIL — $stack ch16: gap event $gap_event_id delivered $raw_count times — beyond the documented at-most-2 replay/live race" >&2
    cat "$log" >&2
    return 1
  fi
  echo "lib.sh: ok — $stack ch16: gap event $gap_event_id delivered after reconnect (raw frame count=$raw_count;" \
       "dedup-by-eventId => exactly one logical delivery; count=2 is PROTOCOL.md's documented benign replay-vs-live race)" >&2

  kill "$pid" >/dev/null 2>&1 || true
  wait "$pid" 2>/dev/null || true
  rm -f "$log"
}

# ---------------------------------------------------------------------------
# Scenario 3 (Ch18): scale-out fan-out — a client connected to instance A
# receives an event injected through instance B's inject endpoint, proving
# the event crossed instances via the shared backplane (kafka or redis).
# Asserts BOTH the client-observed frame (A's client got B's event) AND
# A's own server log line (A's own INSTANCE_ID did the delivering).
# ---------------------------------------------------------------------------
run_ch18_fanout() {
  local stack="$1" broker_label="$2"
  local ws_target_a="$3" container_a="$4" instance_a="$5"
  local http_target_b="$6"
  local booking_id="$7"
  local path; path="$(channel_path "$booking_id")"

  echo
  echo "--- $stack/$broker_label Ch18 fan-out: instance A ($ws_target_a) <- instance B ($http_target_b) (bookingId=$booking_id) ---"

  local log pid
  log="$(mktemp -t "part4-backplane-ch18-${stack}-${broker_label}.XXXXXX.log")"
  pid="$(ws_connect_bg "ws://${ws_target_a}${path}" "$log")"
  BG_PIDS+=("$pid")

  wait_for_log_count "$log" '"eventType":"CUSTOMS"' 1 20
  # Grace window: both backplanes subscribe lazily/asynchronously on first
  # connect (RedisBackplane's subscribe().with(...) is fire-and-forget; even
  # the always-on Kafka consumer needs a moment the very first time a
  # booking is touched) — this avoids a narrow startup race where the
  # inject below outruns instance A's subscription/registration.
  sleep 2

  local event_id
  event_id="$(gen_id evt_)"
  inject_event "$http_target_b" "$booking_id" "$event_id"

  wait_for_log_pattern "$log" "\"eventId\":\"${event_id}\"" 30
  echo "lib.sh: ok — $stack/$broker_label: instance A's CLIENT received instance B's injected event $event_id" >&2

  wait_for_docker_log_pattern "$container_a" "delivered eventId=${event_id} bookingId=${booking_id} instance=${instance_a}" 30
  echo "lib.sh: ok — $stack/$broker_label: instance A's own SERVER LOG shows it delivering (instance=${instance_a})" >&2

  kill "$pid" >/dev/null 2>&1 || true
  wait "$pid" 2>/dev/null || true
  rm -f "$log"
}

# ===========================================================================
echo "=== Step 0: regenerate the contract-derived JSON Schema ==="
ensure_websocat
python3 -I "$EXTRACT_SCRIPT" "$SCHEMA_FILE"

# ===========================================================================
echo
echo "=== Stage A: default profile (stateless) — Ch15 visible-gap proof ==="
start_stage "" "stateless"

run_ch15_stateless_gap "quarkus" "$QUARKUS_A_WS" "$QUARKUS_A_HTTP" "$(gen_id bkg_)"
run_ch15_stateless_gap "python"  "$PYTHON_A_WS"  "$PYTHON_A_HTTP"  "$(gen_id bkg_)"

echo
echo "=== Stage A complete: Ch15 stateless gap PROVEN LIVE on both stacks ==="
end_stage

# ===========================================================================
echo
echo "=== Stage B: --profile kafka — Ch16 replay + Ch18 fan-out (kafka) ==="
start_stage "kafka" "kafka"

run_ch16_kafka_replay "quarkus" "$QUARKUS_A_WS" "$QUARKUS_A_HTTP" "$(gen_id bkg_)"
run_ch16_kafka_replay "python"  "$PYTHON_A_WS"  "$PYTHON_A_HTTP"  "$(gen_id bkg_)"

echo
echo "=== Stage B: Ch16 kafka replay PROVEN LIVE on both stacks ==="

run_ch18_fanout "quarkus" "kafka" "$QUARKUS_A_WS" "$CONTAINER_QUARKUS_A" "$INSTANCE_QUARKUS_A" "$QUARKUS_B_HTTP" "$(gen_id bkg_)"
run_ch18_fanout "python"  "kafka" "$PYTHON_A_WS"  "$CONTAINER_PYTHON_A"  "$INSTANCE_PYTHON_A"  "$PYTHON_B_HTTP"  "$(gen_id bkg_)"

echo
echo "=== Stage B complete: Ch18 fan-out PROVEN LIVE on both stacks over Kafka ==="
end_stage

# ===========================================================================
echo
echo "=== Stage C: --profile redis — Ch18 fan-out (redis) ==="
start_stage "redis" "redis"

run_ch18_fanout "quarkus" "redis" "$QUARKUS_A_WS" "$CONTAINER_QUARKUS_A" "$INSTANCE_QUARKUS_A" "$QUARKUS_B_HTTP" "$(gen_id bkg_)"
run_ch18_fanout "python"  "redis" "$PYTHON_A_WS"  "$CONTAINER_PYTHON_A"  "$INSTANCE_PYTHON_A"  "$PYTHON_B_HTTP"  "$(gen_id bkg_)"

echo
echo "=== Stage C complete: Ch18 fan-out PROVEN LIVE on both stacks over Redis ==="
end_stage

# ===========================================================================
echo
echo "PASS — Part 4 backplane: Quarkus and Python both implement the SAME" \
     "reconnect + scale-out behavior (PROTOCOL.md) — Ch15 stateless mode" \
     "loses a gap-era event, Ch16 kafka mode replays it after reconnect" \
     "(dedup by eventId, no more than the documented benign duplicate)," \
     "and Ch18 an event injected through instance B reaches a client" \
     "connected to instance A over BOTH the Kafka and the Redis backplane," \
     "with instance A's own log confirming it did the delivering."

# Explicit teardown in addition to the cleanup_all EXIT trap
# (belt-and-suspenders); compose_down is idempotent/safe to call twice.
compose_down "$COMPOSE_FILE" "$PROJECT" ""
