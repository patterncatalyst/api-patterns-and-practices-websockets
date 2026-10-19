#!/usr/bin/env bash
# examples/part4-backplane/openshift/verify-crc.sh
#
# Proves, LIVE, on an already-deployed OpenShift Local (CRC) instance, the
# same three things ../../k8s/verify-minikube.sh proves on minikube, ported
# to OpenShift-native mechanisms (Routes + `oc`, not Ingress + `kubectl`):
#
#   1. A schema-valid HandlingEvent seed frame on connect, for BOTH stacks,
#      through an edge-TLS Route — TLS verified against the cluster's OWN
#      ingress CA (never -k/--insecure).
#   2. A long-lived, quiet WebSocket connection survives past a 65s idle
#      hold and still delivers a late injected event — the
#      haproxy.router.openshift.io/timeout: "3600s" annotation
#      (openshift/helm/part4-backplane/templates/routes.yaml) is present and
#      nothing in the path (router, Service, pod) tears the connection down
#      on a timescale a real client would notice. NOTE: HAProxy's own
#      default tunnel timeout is already much longer than nginx's 60s
#      default (the minikube path's baseline), so this is a WEAKER proof
#      here than on minikube — it demonstrates survival + the annotation's
#      presence, not that the annotation moved the timeout close to its
#      edge. Treat it as "the socket is not torn down", not as a
#      before/after timing proof.
#   3. The Ch18 cross-pod fan-out proof: a client connected to instance A
#      (through its Route) receives an event injected through instance B's
#      in-cluster Service (reached via `oc exec`, never a port-forward), and
#      instance A's own pod log confirms it did the delivering — once over
#      the AMQ-Streams-managed Kafka backplane (the primary mode this
#      project deploys with) and once over the Redis backplane (toggled live
#      with `helm upgrade --set backplane=redis` + a rollout restart —
#      PROTOCOL.md "Backplane modes").
#
# This script does NOT start, stop, or build the cluster, and does NOT do
# the initial deploy — it PREFLIGHTS that ./deploy.sh already ran. It DOES
# perform one deploy mutation as part of the proof: the Redis leg toggles
# the backplane live with `helm upgrade --set backplane=redis` + a rollout
# restart (same as verify-minikube.sh's Step 7), then restores nothing —
# teardown.sh handles cleanup. The live cluster bring-up/teardown is the
# user's call (see ../README.md
# for the run order): crc start -> install-infra.sh -> build-images.sh ->
# deploy.sh -> verify-crc.sh -> capture-evidence.sh -> teardown.sh.
#
# `oc exec` into a running app Pod (curl another Service's cluster-DNS name)
# and `oc logs` to read a Pod's own log are the ONLY ways anything but the
# WebSocket client itself crosses into the cluster — the client reaches
# instance A exclusively through its Route, over wss://, CA-verified,
# proving the edge path for real (house preference: in-cluster exec, never
# port-forward/NodePort/tunnel — see this project's other CRC/minikube
# evidence captures).
#
# This file deliberately sources ONLY ../../_lib/lib.sh, NOT ../lib.sh — the
# two files both compute their own REPO_ROOT relative to their own location,
# and sourcing both would have the second overwrite the first's value
# (exactly why ../../k8s/verify-minikube.sh does not source the k8s install
# scripts either).
#
# Usage:
#   ./verify-crc.sh              # full run; both stacks, both backplanes
#   ./verify-crc.sh --help
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../_lib/lib.sh
source "$SCRIPT_DIR/../../_lib/lib.sh"

PROJECT="${PROJECT:-part4-backplane}"
NAMESPACE="${NAMESPACE:-part4-backplane}"
RELEASE="${RELEASE:-part4-backplane}"
OCP_CONTEXT="${OCP_CONTEXT:-crc-admin}"
IMAGE_TAG="${IMAGE_TAG:-v1}"
SCHEMA_FILE="$REPO_ROOT/build/handling-event.schema.json"
EXTRACT_SCRIPT="$REPO_ROOT/scripts/extract-message-schema.py"

for arg in "$@"; do
  case "$arg" in
    -h|--help)
      echo "Usage: $0"
      echo "Preflights an already-deployed part4-backplane on OpenShift Local (CRC)"
      echo "and proves seed + idle-hold + Ch18 fan-out live, through the edge-TLS"
      echo "Routes, for both stacks and both backplane modes (kafka then redis,"
      echo "toggled live via helm --set backplane=redis + a rollout restart)."
      echo "Does NOT start/stop the cluster or deploy anything — run"
      echo "./openshift/deploy.sh first."
      exit 0
      ;;
    *) echo "verify-crc.sh: unknown argument '$arg'" >&2; exit 2 ;;
  esac
done

# Every oc/helm call targets the crc-admin context explicitly — the
# kubeconfig's current-context is never read or changed (same convention as
# ../lib.sh and ../../k8s/verify-minikube.sh's kubectl()/helm() wrappers).
oc()   { command oc --context "$OCP_CONTEXT" "$@"; }
helm() { command helm --kube-context "$OCP_CONTEXT" "$@"; }

step() { printf '\n=== %s ===\n' "$*"; }

# The fixture's 3rd (CUSTOMS) seed event id — see
# examples/part3-handling-events/fixtures/handling-events.json, the same
# constant ../../verify.sh and ../../k8s/verify-minikube.sh use.
LAST_SEED_EVENT_ID="evt_01HZY3M3X0Z6F9S8D4Q1E2V7G0"
CARGO_ID="crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5"

gen_id() {
  python3 -I -c "import uuid, sys; print(sys.argv[1] + uuid.uuid4().hex[:26])" "$1"
}

channel_path() {
  echo "/ws/v1/bookings/$1/handling-events"
}

# ---------------------------------------------------------------------------
# In-cluster helpers (exec + logs — no port-forward)
# ---------------------------------------------------------------------------

# inject_event_crc <exec-deploy> <container> <target-url-base> <bookingId> <eventId> [eventType] [location]
#
# Runs curl INSIDE <exec-deploy>'s running Pod (`oc exec`), POSTing a
# schema-valid HandlingEvent to <target-url-base>/internal/bookings/...
# (PROTOCOL.md "Inject endpoint") and asserting 202. <target-url-base> is
# always an in-cluster, PLAIN HTTP address (http://localhost:<port> to hit
# the exec target's OWN listener, or http://<service>:<port> to cross into
# another instance's Service) — this inject endpoint is internal/demo-only,
# never exposed through a Route, so it never needs TLS.
inject_event_crc() {
  local exec_deploy="$1" container="$2" target_base="$3" booking_id="$4" event_id="$5"
  local event_type="${6:-DELIVERED}" location="${7:-NLRTM}"
  local now body code
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  body=$(printf '{"eventId":"%s","bookingId":"%s","cargoId":"%s","eventType":"%s","location":"%s","occurredAt":"%s","registeredAt":"%s"}' \
    "$event_id" "$booking_id" "$CARGO_ID" "$event_type" "$location" "$now" "$now")
  code="$(oc exec "deploy/$exec_deploy" -n "$NAMESPACE" -c "$container" -- \
    curl -sS -o /dev/null -w '%{http_code}' -X POST \
    "${target_base}/internal/bookings/${booking_id}/handling-events" \
    -H 'Content-Type: application/json' -d "$body")"
  echo "verify-crc.sh: inject eventId=$event_id bookingId=$booking_id via exec($exec_deploy)->$target_base -> HTTP $code" >&2
  assert_eq "202" "$code" "inject $event_id via exec($exec_deploy)->$target_base accepted"
}

# wait_for_oc_log_pattern <deploy> <container> <fixed-string-pattern> [timeout_secs]
#
# Polls `oc logs deploy/<deploy> -c <container>` — the in-cluster equivalent
# of ../../k8s/verify-minikube.sh's wait_for_k8s_log_pattern, used for the
# server-side half of the Ch18 proof ("instance A's own log shows it
# delivering").
wait_for_oc_log_pattern() {
  local deploy="$1" container="$2" pattern="$3" timeout="${4:-30}" waited=0 interval=1
  while (( waited < timeout )); do
    if oc logs "deploy/$deploy" -n "$NAMESPACE" -c "$container" --tail=1000 2>/dev/null | grep -qF -- "$pattern"; then
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done
  echo "verify-crc.sh: FAIL — wait_for_oc_log_pattern: '$pattern' not found in deploy/$deploy ($container) logs within ${timeout}s" >&2
  oc logs "deploy/$deploy" -n "$NAMESPACE" -c "$container" --tail=40 2>&1 >&2 || true
  return 1
}

# ---------------------------------------------------------------------------
# Cleanup — kills only background websocat clients this script started.
# NEVER touches the cluster (no crc stop, no oc delete, no helm uninstall) —
# verify-crc.sh only reads a deployment someone else brought up and leaves it
# running for capture-evidence.sh / further inspection.
# ---------------------------------------------------------------------------
BG_PIDS=()
CA_FILE=""
COMBINED_CA=""
cleanup() {
  local pid
  for pid in "${BG_PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" >/dev/null 2>&1 || true
  done
  for pid in "${BG_PIDS[@]:-}"; do
    [[ -n "$pid" ]] && wait "$pid" 2>/dev/null || true
  done
  BG_PIDS=()
  [[ -n "$CA_FILE" ]] && rm -f "$CA_FILE"
  [[ -n "$COMBINED_CA" ]] && rm -f "$COMBINED_CA"
}
trap cleanup EXIT

# ===========================================================================
step "Step 0: tool checks + crc-admin context + regenerate the contract-derived JSON Schema"
# ===========================================================================
for tool in oc helm python3 curl; do
  command -v "$tool" >/dev/null 2>&1 || { echo "verify-crc.sh: FAIL — '$tool' not on PATH (run: eval \"\$(crc oc-env)\")" >&2; exit 1; }
done
if command -v minikube >/dev/null 2>&1; then
  running="$(minikube profile list -o json 2>/dev/null | python3 -I -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except Exception:
    doc = {}
for p in (doc.get("valid") or []):
    if p.get("Status") in ("OK", "Running"):
        print(p.get("Name", ""))
' 2>/dev/null)"
  if [[ -n "$running" ]]; then
    echo "verify-crc.sh: FAIL — minikube profile(s) running: $running. Stop them first (minikube stop -p <profile>); run one cluster at a time" >&2
    exit 1
  fi
fi
# Context existence is checked WITHOUT the oc() wrapper (and without
# `config use-context`, which would mutate the kubeconfig's current-context)
# — a plain read of the kubeconfig's context list.
command oc config get-contexts "$OCP_CONTEXT" >/dev/null 2>&1 \
  || { echo "verify-crc.sh: FAIL — kubeconfig context '$OCP_CONTEXT' not found (crc start writes it)" >&2; exit 1; }
API="$(oc whoami --show-server 2>/dev/null || true)"
[[ "$API" == *api.crc.testing* ]] \
  || { echo "verify-crc.sh: FAIL — context '$OCP_CONTEXT' points at '$API', not OpenShift Local (api.crc.testing)" >&2; exit 1; }
ensure_websocat
python3 -I "$EXTRACT_SCRIPT" "$SCHEMA_FILE"
echo "verify-crc.sh: crc-admin context OK ($API); schema regenerated at $SCHEMA_FILE"

# ===========================================================================
step "Step 1: preflight — the four Deployments must already be rolled out (run ./openshift/deploy.sh first)"
# ===========================================================================
for d in quarkus-a quarkus-b python-a python-b; do
  oc rollout status "deployment/$d" -n "$NAMESPACE" --timeout=10s >/dev/null 2>&1 \
    || { echo "verify-crc.sh: FAIL — deployment/$d is not rolled out in namespace $NAMESPACE. Run ./openshift/deploy.sh first." >&2; exit 1; }
done
echo "verify-crc.sh: all four app Deployments are already rolled out"

step "Step 1b: extract the cluster's ingress CA for CA-verified wss:// (NEVER -k/--insecure)"
CA_FILE="$(mktemp -t part4-backplane-crc-ingress-ca.XXXXXX.crt)"
oc get configmap default-ingress-cert -n openshift-config-managed \
  -o jsonpath='{.data.ca-bundle\.crt}' > "$CA_FILE" \
  || { echo "verify-crc.sh: FAIL — could not read the ingress CA (configmap/default-ingress-cert -n openshift-config-managed)" >&2; exit 1; }
[[ -s "$CA_FILE" ]] || { echo "verify-crc.sh: FAIL — ingress CA bundle at $CA_FILE is empty" >&2; exit 1; }
# websocat's TLS stack (native-tls/openssl) reads SSL_CERT_FILE as the
# trusted-CA bundle — this is how a `wss://` connection to the Route's
# edge-TLS endpoint gets verified against the cluster's OWN CA without ever
# passing -k/--insecure. SSL_CERT_FILE is exported, so it is inherited by
# EVERY child process in this script — including schema_validate's jsonschema
# fetch. If it pointed at the ingress CA ALONE, that fetch (and anything else
# reaching a public TLS endpoint) would fail with "UnknownIssuer". So the
# exported bundle is the SYSTEM trust store PLUS the ingress CA appended —
# the cluster edge cert verifies AND public endpoints still verify.
SYS_CA=""
for c in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt \
         /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem; do
  [[ -r "$c" ]] && { SYS_CA="$c"; break; }
done
COMBINED_CA="$(mktemp -t part4-backplane-crc-combined-ca.XXXXXX.crt)"
{ [[ -n "$SYS_CA" ]] && cat "$SYS_CA"; echo; cat "$CA_FILE"; } > "$COMBINED_CA"
export SSL_CERT_FILE="$COMBINED_CA"
echo "verify-crc.sh: ingress CA ($CA_FILE) appended to the system trust store ($SYS_CA) -> $COMBINED_CA (SSL_CERT_FILE)"

step "Step 1c: resolve the Route hosts"
QUARKUS_HOST="$(oc get route quarkus-a -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || true)"
PYTHON_HOST="$(oc get route python-a -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || true)"
[[ -n "$QUARKUS_HOST" && -n "$PYTHON_HOST" ]] \
  || { echo "verify-crc.sh: FAIL — could not resolve Route hosts (routes/quarkus-a, routes/python-a). Run ./openshift/deploy.sh first." >&2; exit 1; }
echo "verify-crc.sh: quarkus Route = https://$QUARKUS_HOST/"
echo "verify-crc.sh: python  Route = https://$PYTHON_HOST/"

# wait_route_serving <host> — block until the HAProxy router actually has a
# ready backend for this Route. `oc rollout status` returns on pod-Ready,
# which is BEFORE the router finishes swapping endpoints after a rollout, so a
# WS connect in that window gets a router 503 (confirmed live on CRC
# 2026-10-19: the Redis-toggle rollout 503'd the first connect). A plain GET
# on the WS root returns 426/404/400/200 once a backend is reachable and 503
# (or curl's 000) while it is not — so poll for any non-503, non-000 status.
# CA-verified via the exported SSL_CERT_FILE combined bundle; never -k.
wait_route_serving() {
  local host="$1" waited=0 code
  while (( waited < 90 )); do
    # On a connect failure curl's -w still prints "000"; capture it cleanly
    # (no `|| echo 000`, which would concatenate to "000000" and defeat the
    # guard below) and default an empty result to 000.
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 \
            --cacert "$SSL_CERT_FILE" "https://$host/" 2>/dev/null)" || true
    [[ -z "$code" ]] && code=000
    [[ "$code" != "503" && "$code" != "000" ]] && {
      echo "verify-crc.sh: Route https://$host/ is serving (HTTP $code) after ${waited}s"; return 0; }
    sleep 3; waited=$(( waited + 3 ))
  done
  echo "verify-crc.sh: FAIL — Route https://$host/ still 503/unreachable after ${waited}s (router has no ready backend)" >&2
  return 1
}

step "Step 1d: wait for both Routes to serve a backend (router endpoint reconcile)"
wait_route_serving "$QUARKUS_HOST" || exit 1
wait_route_serving "$PYTHON_HOST" || exit 1

# ===========================================================================
# run_stack_checks — one stack's full proof set over whichever backplane
# mode is currently deployed (the caller names it only for log labeling; the
# live BACKPLANE_MODE comes from whichever `helm upgrade --set backplane=...`
# was last applied).
#
#   stack          "quarkus" | "python"
#   broker_label   "kafka" | "redis" (log label only)
#   route_host     instance A's Route host (wss:// connects here, port 443
#                  implied — edge TLS always terminates on the router)
#   self_base      in-cluster PLAIN-HTTP URL base for instance A's OWN
#                  inject endpoint (used only by the idle-hold-then-late-
#                  frame check)
#   cross_base     in-cluster PLAIN-HTTP URL base for instance B's inject
#                  endpoint, i.e. http://<B's Service name>:<port> (used by
#                  the Ch18 fan-out check)
#   exec_deploy_a  Deployment AND Route name to `oc exec`/inspect — always
#                  instance A (it always has curl, same binary the compose
#                  healthcheck already uses)
#   container      container name inside that Deployment
#   deploy_a_log   Deployment whose logs prove "instance A delivered it"
#                  (always the same as exec_deploy_a here)
# ===========================================================================
run_stack_checks() {
  local stack="$1" broker_label="$2" route_host="$3" self_base="$4" cross_base="$5" \
        exec_deploy_a="$6" container="$7" deploy_a_log="$8"
  local path booking_id frames

  echo
  echo "--- $stack/$broker_label: seed frame + schema validation (through the edge-TLS Route, CA-verified) ---"
  booking_id="$(gen_id bkg_)"
  path="$(channel_path "$booking_id")"
  frames="$(ws_frames_n "wss://${route_host}${path}" 3 30)"
  local last_frame last_event_id
  last_frame="$(tail -n1 <<<"$frames")"
  last_event_id="$(json_field '.eventId' <<<"$last_frame")"
  assert_eq "$LAST_SEED_EVENT_ID" "$last_event_id" "$stack/$broker_label: 3rd seed frame is the fixture's CUSTOMS event"
  schema_validate "$last_frame" "$SCHEMA_FILE"
  echo "verify-crc.sh: ok — $stack/$broker_label: seed frame received through the edge-TLS Route and is schema-valid" >&2

  echo
  echo "--- $stack/$broker_label: idle-hold, then a late frame must still arrive ---"
  # NOTE on what this step actually proves on OpenShift: HAProxy's own
  # default tunnel timeout is already far longer than nginx's 60s default
  # (the minikube path's baseline), so a 65s idle hold getting a late frame
  # back is a WEAKER signal here than it was on minikube/nginx — it mostly
  # shows the socket survives at all, not that the raised annotation moved
  # the timeout close to a timescale that would otherwise bite. The
  # assertion this step makes is narrower, and still real: the
  # haproxy.router.openshift.io/timeout: "3600s" annotation IS present on
  # the Route (checked below) AND a WebSocket held idle for 65s with no
  # traffic is STILL delivered a late frame afterward — nothing in this
  # path (router, Service, pod) tears the connection down on its own on a
  # timescale a real client would notice.
  local route_timeout
  route_timeout="$(oc get route "$exec_deploy_a" -n "$NAMESPACE" -o jsonpath='{.metadata.annotations.haproxy\.router\.openshift\.io/timeout}' 2>/dev/null || true)"
  assert_eq "3600s" "$route_timeout" "$stack/$broker_label: Route $exec_deploy_a carries haproxy.router.openshift.io/timeout: 3600s"
  booking_id="$(gen_id bkg_)"
  path="$(channel_path "$booking_id")"
  local idle_log idle_pid
  idle_log="$(mktemp -t "part4-backplane-crc-idle-${stack}.XXXXXX.log")"
  idle_pid="$(ws_connect_bg "wss://${route_host}${path}" "$idle_log")"
  BG_PIDS+=("$idle_pid")
  wait_for_log_count "$idle_log" '"eventType":"CUSTOMS"' 1 20
  echo "verify-crc.sh: $stack/$broker_label: connected, received the 3 seed frames; holding idle for 65s ..." >&2
  sleep 65
  local late_event_id
  late_event_id="$(gen_id evt_)"
  inject_event_crc "$exec_deploy_a" "$container" "$self_base" "$booking_id" "$late_event_id"
  wait_for_log_pattern "$idle_log" "\"eventId\":\"${late_event_id}\"" 30
  echo "verify-crc.sh: ok — $stack/$broker_label: late frame arrived after a 65s idle hold over the edge-TLS Route (haproxy.router.openshift.io/timeout: 3600s present)" >&2
  kill "$idle_pid" >/dev/null 2>&1 || true
  wait "$idle_pid" 2>/dev/null || true
  rm -f "$idle_log"

  echo
  echo "--- $stack/$broker_label: Ch18 cross-pod fan-out — instance A (Route) <- instance B (oc exec into B's Service) ---"
  booking_id="$(gen_id bkg_)"
  path="$(channel_path "$booking_id")"
  local fanout_log fanout_pid
  fanout_log="$(mktemp -t "part4-backplane-crc-fanout-${stack}.XXXXXX.log")"
  fanout_pid="$(ws_connect_bg "wss://${route_host}${path}" "$fanout_log")"
  BG_PIDS+=("$fanout_pid")
  wait_for_log_count "$fanout_log" '"eventType":"CUSTOMS"' 1 20
  sleep 2 # let the backplane subscription settle (same grace window as verify.sh / verify-minikube.sh)
  local fanout_event_id
  fanout_event_id="$(gen_id evt_)"
  inject_event_crc "$exec_deploy_a" "$container" "$cross_base" "$booking_id" "$fanout_event_id"
  wait_for_log_pattern "$fanout_log" "\"eventId\":\"${fanout_event_id}\"" 30
  echo "verify-crc.sh: ok — $stack/$broker_label: instance A's CLIENT (through the Route) received instance B's injected event $fanout_event_id" >&2
  wait_for_oc_log_pattern "$deploy_a_log" "$container" "delivered eventId=${fanout_event_id} bookingId=${booking_id} instance=${stack}-a" 30
  echo "verify-crc.sh: ok — $stack/$broker_label: instance A's own POD LOG shows it delivering" >&2
  kill "$fanout_pid" >/dev/null 2>&1 || true
  wait "$fanout_pid" 2>/dev/null || true
  rm -f "$fanout_log"
}

# ===========================================================================
step "Step 2: live proof over the KAFKA backplane (primary mode, as deployed) — both stacks"
# ===========================================================================
run_stack_checks "quarkus" "kafka" "$QUARKUS_HOST" \
  "http://localhost:8080" "http://quarkus-b:8080" \
  "quarkus-a" "quarkus" "quarkus-a"

run_stack_checks "python" "kafka" "$PYTHON_HOST" \
  "http://localhost:8082" "http://python-b:8082" \
  "python-a" "python" "python-a"

echo
echo "=== Step 2 complete: seed + idle-hold + Ch18 Kafka fan-out PROVEN LIVE on both stacks ==="

# ===========================================================================
step "Step 3: switch to the REDIS backplane (helm upgrade --set backplane=redis) and re-prove Ch18 fan-out"
# ===========================================================================
helm upgrade --install "$RELEASE" "$SCRIPT_DIR/helm/$PROJECT" \
  -n "$NAMESPACE" --reset-then-reuse-values \
  --set imageTag="$IMAGE_TAG" --set backplane=redis >/dev/null \
  || { echo "verify-crc.sh: FAIL — helm upgrade --set backplane=redis failed" >&2; exit 1; }
# envFrom/configMapRef does NOT hot-reload into running Pods — force a
# rollout so every instance picks up BACKPLANE_MODE=redis (same reason
# ../../k8s/verify-minikube.sh's Step 7 does this).
for d in quarkus-a quarkus-b python-a python-b; do
  oc rollout restart "deployment/$d" -n "$NAMESPACE" >/dev/null
done
for d in quarkus-a quarkus-b python-a python-b; do
  oc rollout status "deployment/$d" -n "$NAMESPACE" --timeout=180s
done
# The rollout restart cycles the Route-facing pods, so the router briefly 503s
# until it re-adds the new endpoints — wait for it before the WS connect (same
# "serving, not just Ready" gate as Step 1d).
wait_route_serving "$QUARKUS_HOST" || exit 1
wait_route_serving "$PYTHON_HOST" || exit 1

run_stack_checks "quarkus" "redis" "$QUARKUS_HOST" \
  "http://localhost:8080" "http://quarkus-b:8080" \
  "quarkus-a" "quarkus" "quarkus-a"

run_stack_checks "python" "redis" "$PYTHON_HOST" \
  "http://localhost:8082" "http://python-b:8082" \
  "python-a" "python" "python-a"

echo
echo "=== Step 3 complete: Ch18 Redis fan-out PROVEN LIVE on both stacks (the helm backplane toggle works) ==="

# ===========================================================================
echo
echo "PASS — part4-backplane on OpenShift Local (CRC, crc-admin context):" \
     "edge-TLS Routes (CA-verified against the cluster's own ingress CA," \
     "never -k/--insecure) deliver a schema-valid seed frame on both stacks;" \
     "a 65s idle hold still gets a late frame back with the" \
     "haproxy.router.openshift.io/timeout: 3600s annotation present on both" \
     "Routes; and the Ch18 cross-pod fan-out proof holds over BOTH the" \
     "AMQ-Streams-managed Kafka backplane and the Helm-toggled Redis" \
     "backplane, with instance A's own pod log confirming every delivery." \
     "verify-crc.sh did not start, stop, or build the cluster; it toggled" \
     "the backplane to Redis (helm upgrade --set + rollout restart) as part" \
     "of the proof, same as verify-minikube.sh."
echo "exit 0"
