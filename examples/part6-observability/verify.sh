#!/usr/bin/env bash
# examples/part6-observability/verify.sh
#
# Part 6 "Observability" ANCHOR (Ch23, DRQ-028/DRQ-029) — both the Quarkus
# and the Python stack implement the SAME `handlingEvents` channel as
# part3/part4 (contracts/asyncapi.yaml `operations.receiveHandlingEvent`),
# now with LIVE OpenTelemetry: a manual per-connection span
# (`ws.handling-events.connection`), one structured trace-id log line per
# connection, and a `handling_events_delivered_total` counter — all exported
# to the `lgtm` compose service (Grafana/Tempo/Mimir/Loki), which is a HARD
# dependency here (see compose.yaml — no `profiles:` guard).
#
# Per DRQ-028's HARD/SOFT split (mirroring the gRPC sibling's
# examples/21-observability/verify.sh):
#   HARD — the connection's trace id appears in the app's own structured log
#          line, AND the app's own metrics endpoint shows
#          `handling_events_delivered_total` > 0 (a synchronous Prometheus
#          text-format scrape against the app itself, never against Mimir).
#   SOFT — Tempo (`:3200/api/traces/<id>`) eventually shows a span named
#          `ws.handling-events.connection` for that trace id — bounded-retry
#          poll, warns (never fails) on ingest lag.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_lib/lib.sh
source "$SCRIPT_DIR/../_lib/lib.sh"

PROJECT="part6-observability"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
SCHEMA_FILE="$SCRIPT_DIR/../../build/handling-event.schema.json"
EXTRACT_SCRIPT="$SCRIPT_DIR/../../scripts/extract-message-schema.py"

BOOKING_ID="bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A"
CHANNEL_PATH="/ws/v1/bookings/${BOOKING_ID}/handling-events"
EXPECTED_EVENT_TYPE="RECEIVE"
CONNECTION_SPAN_NAME="ws.handling-events.connection"
DELIVERED_METRIC="handling_events_delivered_total"

# ---------------------------------------------------------------------------
# Example-local helpers (specific to this chapter's assertions — not
# promoted to ../_lib/lib.sh, same rationale as the gRPC sibling's
# verify.sh-local wait_for_lgtm/assert_metric_present/check_tempo_trace).
# ---------------------------------------------------------------------------

# wait_for_grafana_health [timeout_secs] — poll the always-on LGTM stack's
# Grafana health endpoint. Budgeted generously (default 90s) to cover the
# stack's cold start (Grafana + Tempo + Mimir + Loki + the Collector, all in
# one image) on a first `docker compose up --build`.
wait_for_grafana_health() {
  local timeout="${1:-90}" waited=0 interval=5
  echo "verify.sh: waiting for lgtm (Grafana LGTM) health (timeout ${timeout}s) ..." >&2
  while (( waited < timeout )); do
    if curl -fsS -o /dev/null "http://localhost:3000/api/health"; then
      echo "verify.sh: lgtm is up after ${waited}s" >&2
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done
  echo "verify.sh: FAIL — lgtm did not become healthy within ${timeout}s" >&2
  return 1
}

# assert_metric_present <metrics-text> <metric-name> <context> — sums every
# Prometheus text-format sample line whose name is exactly <metric-name>
# (ignoring labels) and asserts the total is > 0. Used against each app's OWN
# metrics endpoint (/q/metrics on Quarkus, :8082/metrics on Python), never
# against Mimir, so the assertion is synchronous — no scrape-interval wait.
assert_metric_present() {
  local metrics_text="$1" metric_name="$2" context="${3:-$metric_name}"
  local total
  total="$(python3 -I -c '
import sys
text, name = sys.argv[1], sys.argv[2]
found = False
total = 0.0
for line in text.splitlines():
    line = line.strip()
    if not line or line.startswith("#") or not line.startswith(name):
        continue
    rest = line[len(name):]
    if rest and rest[0] not in (" ", "{"):
        continue  # a longer metric name that happens to share this prefix
    # The Micrometer Prometheus exporter appends an OpenMetrics EXEMPLAR
    # after the real sample value when a span is active at increment time —
    # e.g. `handling_events_delivered_total 3.0 # {span_id="...",trace_id="..."} 1.0 1792422733.119`
    # (confirmed live against the Quarkus stack here, which always has a
    # span active when the counter increments — see
    # HandlingEventObservabilityWebSocket#onOpen). A bare `rsplit(" ", 1)`
    # on the whole line would grab the trailing exemplar timestamp instead
    # of the actual counter value — strip everything from " #" onward
    # first, so only the real sample value is ever parsed. The Python side
    # (prometheus-client, no exemplar support) is unaffected by this split —
    # its lines never contain " #" mid-line.
    sample_part = line.split(" #", 1)[0]
    try:
        value = float(sample_part.rsplit(" ", 1)[-1])
    except ValueError:
        continue
    found = True
    total += value
print(total if found else "NOTFOUND")
' "$metrics_text" "$metric_name")"

  if [[ "$total" == "NOTFOUND" ]]; then
    echo "verify.sh: FAIL — ${context}: metric '$metric_name' not found" >&2
    return 1
  fi
  if ! python3 -I -c "import sys; sys.exit(0 if float(sys.argv[1]) > 0 else 1)" "$total"; then
    echo "verify.sh: FAIL — ${context}: metric '$metric_name' total is $total, expected > 0" >&2
    return 1
  fi
  echo "verify.sh: ok — ${context}: metric '$metric_name' total=$total" >&2
}

# wait_for_trace_id_log <service> <instance-name> — HARD assertion. Polls
# `docker compose logs <service>` (bounded retry; a few seconds of grace for
# the log line to flush to the container's stdout/the compose log buffer)
# for the EXACT trace-id log line shape both stacks share:
#
#   otel.trace_id=<32-hex-trace-id> span=ws.handling-events.connection bookingId=<id> instance=<instance-name>
#
# Takes the LAST matching line (not the first) — by the time this runs, the
# just-completed ws_first_frame connection is the most recent one to have
# logged this line for $BOOKING_ID (wait_for_ws's own upgrade probes may
# have logged earlier ones for the same booking id, since @OnOpen/the
# connection handler fires on every accepted upgrade regardless of how
# quickly the probing client disconnects) — and extracts/validates the trace
# id is a 32-hex-digit string.
wait_for_trace_id_log() {
  local service="$1" instance="$2" attempts=15 delay=1 i logs trace_id
  local pattern="span=${CONNECTION_SPAN_NAME} bookingId=${BOOKING_ID} instance=${instance}"
  for (( i = 1; i <= attempts; i++ )); do
    logs="$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" logs "$service" 2>&1)"
    if grep -qF -- "$pattern" <<<"$logs"; then
      trace_id="$(grep -F -- "$pattern" <<<"$logs" | tail -1 \
        | sed -n 's/.*otel\.trace_id=\([0-9a-f]\{32\}\).*/\1/p')"
      if [[ -n "$trace_id" ]]; then
        echo "verify.sh: ok — $service: found trace-id log line, otel.trace_id=$trace_id" >&2
        echo "$trace_id"
        return 0
      fi
    fi
    sleep "$delay"
  done
  echo "verify.sh: FAIL — $service: no trace-id log line matching '$pattern' found within $(( attempts * delay ))s" >&2
  echo "--- $service logs ---" >&2
  docker compose -p "$PROJECT" -f "$COMPOSE_FILE" logs "$service" >&2 2>&1 || true
  return 1
}

# check_tempo_trace <trace-id> — SOFT, bounded-retry poll of Tempo's query
# API for a trace carrying a span literally named
# `ws.handling-events.connection`. NEVER fails the build — logs ok or a
# non-fatal warning (ingest lag is expected, especially on a cold `lgtm`
# start plus the app's own OTLP batch-export interval).
check_tempo_trace() {
  local trace_id="$1" attempts=10 delay=3 i resp
  echo "verify.sh: polling Tempo for trace $trace_id (soft, up to $(( attempts * delay ))s) ..." >&2
  for (( i = 1; i <= attempts; i++ )); do
    resp="$(curl -fsS "http://localhost:3200/api/traces/${trace_id}" 2>/dev/null || true)"
    if [[ -n "$resp" ]] && grep -qF "\"${CONNECTION_SPAN_NAME}\"" <<<"$resp"; then
      echo "verify.sh: ok (soft) — Tempo has trace $trace_id with span '${CONNECTION_SPAN_NAME}'" >&2
      return 0
    fi
    sleep "$delay"
  done
  echo "verify.sh: WARN (soft, non-fatal) — Tempo did not show span '${CONNECTION_SPAN_NAME}'" \
       "for trace $trace_id within $(( attempts * delay ))s (ingest lag); not failing the build" >&2
  return 0
}

# ---------------------------------------------------------------------------
# Per-stack assertions
# ---------------------------------------------------------------------------

# run_stack_tests <stack> <ws-target> <metrics-url> <log-service> <instance-name>
#
# Prints the captured trace id to stdout on success (caller captures it for
# the final report); everything else goes to stderr.
run_stack_tests() {
  local stack="$1" ws_target="$2" metrics_url="$3" log_service="$4" instance="$5"
  local url="ws://${ws_target}${CHANNEL_PATH}"

  echo >&2
  echo "=== verifying stack '$stack' ($url, metrics $metrics_url) ===" >&2

  wait_for_ws "$ws_target" "$CHANNEL_PATH"

  # --- 1. Functional: first frame is the fixture's RECEIVE event, schema-valid ---
  local frame
  frame="$(ws_first_frame "$url")"
  echo "verify.sh: $stack first frame: $frame" >&2
  schema_validate "$frame" "$SCHEMA_FILE"
  assert_eq "$EXPECTED_EVENT_TYPE" "$(json_field '.eventType' <<<"$frame")" "$stack first frame eventType"
  assert_eq "$BOOKING_ID" "$(json_field '.bookingId' <<<"$frame")" "$stack first frame bookingId"

  # --- 2. HARD: this connection's trace id appears in the app's own logs ---
  local trace_id
  trace_id="$(wait_for_trace_id_log "$log_service" "$instance")"
  if [[ ! "$trace_id" =~ ^[0-9a-f]{32}$ ]]; then
    echo "verify.sh: FAIL — $stack: captured trace id '$trace_id' is not a 32-hex-digit id" >&2
    exit 1
  fi

  # --- 3. HARD: the app's OWN metrics endpoint shows the delivered counter ---
  local metrics_text
  metrics_text="$(curl -fsS "$metrics_url")"
  assert_metric_present "$metrics_text" "$DELIVERED_METRIC" "$stack delivered counter"

  # --- 4. SOFT: Tempo eventually ingests a span for this trace id ---
  check_tempo_trace "$trace_id"

  echo "=== $stack: all HARD assertions passed (trace_id=$trace_id) ===" >&2
  printf '%s\n' "$trace_id"
}

echo "=== Step 0: regenerate the contract-derived JSON Schema ==="
ensure_websocat
python3 -I "$EXTRACT_SCRIPT" "$SCHEMA_FILE"

echo
echo "=== Step 1: docker compose up (incl. the always-on lgtm service) ==="
compose_up "$COMPOSE_FILE" "$PROJECT"

echo
echo "=== Step 2: wait for the LGTM stack (OTLP port + Grafana health) ==="
wait_for_tcp localhost 4317 90
wait_for_grafana_health 90

echo
echo "=== Step 3: verify both stacks ==="
QUARKUS_TRACE_ID="$(run_stack_tests "quarkus" "localhost:8080" "http://localhost:8080/q/metrics" \
  "quarkus" "part6-observability-quarkus")"

PYTHON_TRACE_ID="$(run_stack_tests "python" "localhost:8081" "http://localhost:8082/metrics" \
  "python" "part6-observability-python")"

echo
echo "PASS — Part 6 observability anchor: on BOTH the Quarkus and the Python" \
     "stack, the handlingEvents channel streams a schema-valid RECEIVE" \
     "event AND the connection's trace id appears in the app's own" \
     "structured log line (quarkus trace_id=$QUARKUS_TRACE_ID," \
     "python trace_id=$PYTHON_TRACE_ID) AND each app's own metrics endpoint" \
     "shows handling_events_delivered_total > 0 — the HARD DRQ-028" \
     "assertions. The SOFT Tempo poll (ingest lag tolerant, never fails" \
     "the build) ran against both trace ids above; see the per-stack" \
     "'polling Tempo' / 'ok (soft)' / 'WARN (soft, non-fatal)' lines above" \
     "for the outcome."

# Explicit teardown in addition to lib.sh's EXIT trap (belt-and-suspenders);
# compose_down is idempotent/safe to call twice.
compose_down "$COMPOSE_FILE" "$PROJECT"
