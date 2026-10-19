#!/usr/bin/env bash
# examples/part6-testing/verify.sh
#
# Part 6 "Testing, Debugging & Observability" (Ch21, DRQ-030) — the
# functional-HTTP testing layer this WebSocket-only site still needs at its
# HTTP seams (DRQ-006: Newman = functional, k6 = load). This example has no
# app of its own: it brings up examples/part4-backplane's EXISTING compose
# stack (default/stateless profile — no broker needed for these checks) and
# runs newman/collection.json against it with a pinned Newman, exactly the
# way k6/smoke.js runs against part4-backplane's live containers from a
# neighboring directory.
#
# Covers (see newman/collection.json for the assertions):
#   - GET /healthz on both Python instances (python-a, python-b) -> 200
#     {"status":"ok"}.
#   - POST /internal/bookings/{bookingId}/handling-events (PROTOCOL.md
#     "Inject endpoint") on both stacks (quarkus-a, python-a): a
#     schema-valid HandlingEvent -> 202 Accepted; a malformed body (bad
#     eventType enum / bad bookingId pattern) -> 4xx (400 Quarkus's plain
#     record + Jackson enum rejection, 422 Python's Pydantic v2 validation).
#
# NOT covered here: examples/part6-observability's HTTP surface. Its Quarkus
# app has no dedicated health endpoint at all (no quarkus-smallrye-health
# dependency — confirmed in its pom.xml and compose.yaml's healthcheck
# comment), and its `handling_events_delivered_total` Micrometer counter is
# only registered once a WebSocket connection actually opens (@PostConstruct
# on a per-connection WebSockets Next endpoint bean, not an app-startup
# singleton) — proving it live would mean driving a WS connection first and
# bringing up the example's hard-dependency LGTM stack (Grafana/Loki/Tempo/
# Mimir) just to scrape two HTTP endpoints. That's WS+observability
# territory Ch23's own verify.sh already owns; out of scope for a
# functional-HTTP Newman pass (DRQ-006).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_lib/lib.sh
source "$SCRIPT_DIR/../_lib/lib.sh"

PROJECT="part4-backplane"
COMPOSE_FILE="$SCRIPT_DIR/../part4-backplane/compose.yaml"
COLLECTION="$SCRIPT_DIR/newman/collection.json"
ENVIRONMENT="$SCRIPT_DIR/newman/environment.json"
REPORT_DIR="$SCRIPT_DIR/newman/reports"

# Pin: Newman 6.2.3 (npm, current stable as of this survey — 2026-10-19;
# see ../../_plans/version-matrix.md and _docs/00-setup-and-the-lab.md's Ch0
# version matrix). No `docker.io/postman/newman` image tag newer than 6.1.3
# exists yet (checked live against Docker Hub), so — per the project's
# "upgrade the tool, never downgrade the pin" policy — this uses `npx
# newman@<pin>` instead: the same self-contained, no-local-install-required
# philosophy as lib.sh's ensure_websocat/ensure_protoc, just via npm's cache
# rather than a downloaded binary. Override NEWMAN_VERSION to re-pin.
NEWMAN_VERSION="${NEWMAN_VERSION:-6.2.3}"

if ! command -v npx >/dev/null 2>&1; then
  echo "verify.sh: FAIL — npx (Node.js) is required to run the pinned 'npx newman@${NEWMAN_VERSION}'" >&2
  exit 1
fi

# wait_for_http <url> [timeout_secs] — polls <url> until it answers ANY HTTP
# response (even a 404), or fails loudly. Not in examples/_lib/lib.sh (which
# only has WebSocket/TCP waiters) — local to this HTTP-only example.
wait_for_http() {
  local url="$1"
  local timeout="${2:-90}"
  local waited=0
  local interval=2
  echo "verify.sh: waiting for HTTP $url (timeout ${timeout}s) ..." >&2
  while (( waited < timeout )); do
    if curl -s -o /dev/null "$url" 2>/dev/null; then
      echo "verify.sh: HTTP $url is up after ${waited}s" >&2
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done
  echo "verify.sh: FAIL — HTTP $url did not answer within ${timeout}s" >&2
  return 1
}

echo
echo "=== docker compose up (part4-backplane, default/stateless profile) ==="
compose_up "$COMPOSE_FILE" "$PROJECT" ""

# Readiness: python-a's /healthz (uvicorn, fast to answer) + quarkus-a's bare
# root (no dedicated health endpoint — see compose.yaml's own comment) prove
# both stacks' instance-A HTTP listeners are up before newman hits them;
# python-b/quarkus-b follow the same four-instance cold-start curve so a
# short settle is enough once A is answering.
wait_for_http "http://localhost:8082/healthz" 90
wait_for_http "http://localhost:8080/" 90
wait_for_http "http://localhost:8085/healthz" 30
wait_for_http "http://localhost:8083/" 30

mkdir -p "$REPORT_DIR"
REPORT_JSON="$REPORT_DIR/newman-report.json"

echo
echo "=== npx newman@${NEWMAN_VERSION} run (pinned) ==="
if npx -y "newman@${NEWMAN_VERSION}" run "$COLLECTION" \
    -e "$ENVIRONMENT" \
    --reporters cli,json \
    --reporter-json-export "$REPORT_JSON"; then
  echo
  echo "PASS — Part 6 functional-HTTP: newman (pinned ${NEWMAN_VERSION}) ran" \
       "examples/part6-testing/newman/collection.json against the live" \
       "part4-backplane stack (both stacks' inject endpoint, both Python" \
       "instances' /healthz) with 0 failed assertions. Report:" \
       "$REPORT_JSON"
else
  rc=$?
  echo "verify.sh: FAIL — newman run exited $rc (see CLI output above / $REPORT_JSON)" >&2
  exit "$rc"
fi

compose_down "$COMPOSE_FILE" "$PROJECT" ""
