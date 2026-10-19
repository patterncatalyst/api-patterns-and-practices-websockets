#!/usr/bin/env bash
# examples/part4-backplane/k8s/verify-minikube.sh
#
# Deploys the part4-backplane example (Quarkus WebSockets Next + Python
# native `websockets`/FastAPI, Kafka via Strimzi, Redis) to a real minikube
# cluster (docker driver + containerd runtime — DRQ-007, podman NOT
# supported) and proves, live, through the ingress-nginx edge (DRQ-031):
#
#   1. A schema-valid HandlingEvent seed frame on connect, for BOTH stacks.
#   2. The raised proxy-read-timeout/proxy-send-timeout annotations actually
#      keep a quiet WebSocket connection open PAST nginx's 60s default idle
#      timeout — hold the socket 65s with no traffic, then inject one more
#      event and assert it still arrives.
#   3. The Ch18 cross-pod fan-out proof (same contract as
#      examples/part4-backplane/verify.sh, ported to a real cluster instead
#      of compose): a client connected to instance A (through the ingress)
#      receives an event injected through instance B's in-cluster Service,
#      and instance A's own pod log confirms it did the delivering — once
#      over the Kafka backplane (overlays/minikube, the primary mode) and
#      once over the Redis backplane (overlays/minikube-redis, the toggle
#      component — PROTOCOL.md "Backplane modes").
#
# This file is deliberately OUTSIDE the examples/*/verify.sh naming
# convention (it lives in k8s/, a subdirectory) so the repo's `examples`
# matrix glob (CI; see scripts/validate.py) never picks it up — it is slow
# (cluster bring-up, two image builds, Strimzi, three `kubectl apply -k`
# rollouts) and requires minikube, which the compose-based CI job does not
# have.
#
# In-cluster-exec, never port-forward, for everything the inject/log checks
# need to reach (house preference — see the project's own OpenShift/minikube
# evidence captures): `kubectl exec` into a running app Pod to curl another
# Service's cluster-DNS name, and `kubectl logs` to read a Pod's own log.
# The only thing that crosses the cluster boundary from the host is the
# WebSocket client itself, through the ingress — proving the ingress path
# for real, not a shortcut around it.
#
# Usage:
#   ./verify-minikube.sh              # full run, tears the profile down at the end
#   ./verify-minikube.sh --keep       # leave the minikube profile running after
#   KUBERNETES_VERSION=v1.38.0 ./verify-minikube.sh   # override the pinned k8s version
#
# Pins (see ../../../_plans/version-matrix.md "Kubernetes / minikube
# (Part 7)"): minikube >= v1.39.0, Kubernetes v1.37.1, Strimzi 1.3.0 (Kafka
# 4.3.1 default), Redis 8.10.2-alpine, kustomize (bundled with kubectl
# v1.37.1 / kustomize v5.8.1), kubeconform v0.8.0.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../../_lib/lib.sh
source "$SCRIPT_DIR/../../_lib/lib.sh"

PROFILE="${PROFILE:-part4-backplane}"
NAMESPACE="${NAMESPACE:-part4-backplane}"
MINIKUBE_MIN="v1.39.0"
KUBERNETES_VERSION="${KUBERNETES_VERSION:-v1.37.1}"
QUARKUS_IMAGE="part4-backplane-quarkus:minikube"
PYTHON_IMAGE="part4-backplane-python:minikube"
SCHEMA_FILE="$REPO_ROOT/build/handling-event.schema.json"
EXTRACT_SCRIPT="$REPO_ROOT/scripts/extract-message-schema.py"

KEEP=0
for arg in "$@"; do
  case "$arg" in
    --keep) KEEP=1 ;;
    -h|--help)
      echo "Usage: $0 [--keep]"
      exit 0
      ;;
    *) echo "verify-minikube.sh: unknown argument '$arg'" >&2; exit 2 ;;
  esac
done

# Every kubectl/helm/minikube call targets this profile's context explicitly
# — kubectl's current-context is never read or changed (same convention as
# modernizing-enterprise-applications/deploy/k8s/scripts/lib.sh and the
# lgtm-minikube-stack skill).
kubectl() { command kubectl --context "$PROFILE" "$@"; }
helm()    { command helm --kube-context "$PROFILE" "$@"; }

step() { printf '\n=== %s ===\n' "$*"; }

# The fixture's 3rd (CUSTOMS) seed event id — see
# examples/part3-handling-events/fixtures/handling-events.json, same
# constant examples/part4-backplane/verify.sh uses.
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

# inject_event_k8s <exec-deploy> <container> <target-url-base> <bookingId> <eventId> [eventType] [location]
#
# Runs curl INSIDE <exec-deploy>'s running Pod (kubectl exec), POSTing a
# schema-valid HandlingEvent to <target-url-base>/internal/bookings/...
# (PROTOCOL.md "Inject endpoint") and asserting 202. <target-url-base> is
# always an in-cluster address (http://localhost:<port> to hit the exec
# target's OWN listener, or http://<service>:<port> to cross into another
# instance's Service) — the host running this script never reaches the
# inject endpoint directly.
inject_event_k8s() {
  local exec_deploy="$1" container="$2" target_base="$3" booking_id="$4" event_id="$5"
  local event_type="${6:-DELIVERED}" location="${7:-NLRTM}"
  local now body code
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  body=$(printf '{"eventId":"%s","bookingId":"%s","cargoId":"%s","eventType":"%s","location":"%s","occurredAt":"%s","registeredAt":"%s"}' \
    "$event_id" "$booking_id" "$CARGO_ID" "$event_type" "$location" "$now" "$now")
  code="$(kubectl exec "deploy/$exec_deploy" -n "$NAMESPACE" -c "$container" -- \
    curl -sS -o /dev/null -w '%{http_code}' -X POST \
    "${target_base}/internal/bookings/${booking_id}/handling-events" \
    -H 'Content-Type: application/json' -d "$body")"
  echo "verify-minikube.sh: inject eventId=$event_id bookingId=$booking_id via exec($exec_deploy)->$target_base -> HTTP $code" >&2
  assert_eq "202" "$code" "inject $event_id via exec($exec_deploy)->$target_base accepted"
}

# wait_for_k8s_log_pattern <deploy> <fixed-string-pattern> [timeout_secs]
#
# Polls `kubectl logs deploy/<deploy>` — the in-cluster equivalent of
# verify.sh's wait_for_docker_log_pattern, used for the server-side half of
# the Ch18 proof ("instance A's own log shows it delivering").
wait_for_k8s_log_pattern() {
  local deploy="$1" pattern="$2" timeout="${3:-30}" waited=0 interval=1
  while (( waited < timeout )); do
    if kubectl logs "deploy/$deploy" -n "$NAMESPACE" --tail=1000 2>/dev/null | grep -qF -- "$pattern"; then
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done
  echo "verify-minikube.sh: FAIL — wait_for_k8s_log_pattern: '$pattern' not found in deploy/$deploy logs within ${timeout}s" >&2
  kubectl logs "deploy/$deploy" -n "$NAMESPACE" --tail=40 2>&1 >&2 || true
  return 1
}

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
BG_PIDS=()
cleanup() {
  local pid
  for pid in "${BG_PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" >/dev/null 2>&1 || true
  done
  for pid in "${BG_PIDS[@]:-}"; do
    [[ -n "$pid" ]] && wait "$pid" 2>/dev/null || true
  done
  BG_PIDS=()
  if [[ "$KEEP" -eq 1 ]]; then
    echo "verify-minikube.sh: --keep set — leaving profile '$PROFILE' running" >&2
  else
    echo "verify-minikube.sh: tearing down minikube profile '$PROFILE'" >&2
    minikube delete -p "$PROFILE" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

# ===========================================================================
step "Step 0: tool checks + regenerate the contract-derived JSON Schema"
# ===========================================================================
for tool in minikube kubectl helm docker python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "verify-minikube.sh: FAIL — '$tool' not on PATH" >&2; exit 1; }
done
mk_ver="$(minikube version --short 2>/dev/null || echo v0.0.0)"
[[ "$(printf '%s\n%s\n' "$MINIKUBE_MIN" "$mk_ver" | sort -V | head -1)" == "$MINIKUBE_MIN" ]] \
  || { echo "verify-minikube.sh: FAIL — minikube $mk_ver is older than required $MINIKUBE_MIN" >&2; exit 1; }
ensure_websocat
python3 -I "$EXTRACT_SCRIPT" "$SCHEMA_FILE"
echo "verify-minikube.sh: minikube $mk_ver OK (>= $MINIKUBE_MIN); schema regenerated at $SCHEMA_FILE"

# ===========================================================================
step "Step 1: minikube profile '$PROFILE' (docker driver, containerd, Kubernetes $KUBERNETES_VERSION)"
# ===========================================================================
if minikube status -p "$PROFILE" >/dev/null 2>&1; then
  echo "verify-minikube.sh: profile '$PROFILE' already running — reusing it"
else
  minikube start -p "$PROFILE" \
    --driver=docker \
    --container-runtime=containerd \
    --kubernetes-version="$KUBERNETES_VERSION"
fi
kubectl get nodes

step "Step 1b: ingress-nginx addon"
minikube addons enable ingress -p "$PROFILE"
kubectl rollout status deployment/ingress-nginx-controller -n ingress-nginx --timeout=180s

# ===========================================================================
step "Step 2: build + load both app images (docker build from repo root, minikube image load — no registry)"
# ===========================================================================
docker build -f "$REPO_ROOT/examples/part4-backplane/quarkus/Containerfile" -t "$QUARKUS_IMAGE" "$REPO_ROOT"
docker build -f "$REPO_ROOT/examples/part4-backplane/python/Containerfile" -t "$PYTHON_IMAGE" "$REPO_ROOT"
minikube image load "$QUARKUS_IMAGE" -p "$PROFILE"
minikube image load "$PYTHON_IMAGE" -p "$PROFILE"
echo "verify-minikube.sh: images built and loaded into profile '$PROFILE': $QUARKUS_IMAGE, $PYTHON_IMAGE"

# ===========================================================================
step "Step 3: Strimzi operator + Kafka + Redis (must be Ready before the apps roll out)"
# ===========================================================================
PROFILE="$PROFILE" NAMESPACE="$NAMESPACE" "$SCRIPT_DIR/scripts/install-strimzi.sh"

# ===========================================================================
step "Step 4: deploy the apps (overlays/minikube — Kafka-mode primary)"
# ===========================================================================
kubectl apply -k "$SCRIPT_DIR/overlays/minikube"
for d in quarkus-a quarkus-b python-a python-b; do
  kubectl rollout status "deployment/$d" -n "$NAMESPACE" --timeout=180s
done
echo "verify-minikube.sh: all four app Deployments rolled out"

# ===========================================================================
step "Step 5: resolve the ingress URL"
# ===========================================================================
# websocat 1.14.1 does NOT let a custom `-H` header override the Host header
# it derives from the connection URL's own authority (confirmed live: a
# packet capture showed the `-H=Host:...`/`-H Host:...` value never leaving
# the client — only the URL's own host:port ever appears as `Host:`). So
# rather than connect to the bare `minikube ip` and try to force a Host
# header, this uses nip.io — a public wildcard DNS service that resolves
# `<anything>.<ip>.nip.io` to `<ip>` — so the WS URL's own authority IS the
# real, DNS-resolvable Ingress hostname, no `/etc/hosts` edit and no
# `minikube tunnel` required. Needs outbound DNS to nip.io; no in-cluster
# dependency.
MINIKUBE_IP="$(minikube ip -p "$PROFILE")"
QUARKUS_HOST="quarkus.${MINIKUBE_IP}.nip.io"
PYTHON_HOST="python.${MINIKUBE_IP}.nip.io"
echo "verify-minikube.sh: minikube ip = $MINIKUBE_IP"
echo "verify-minikube.sh: quarkus ingress host = http://$QUARKUS_HOST/"
echo "verify-minikube.sh: python  ingress host = http://$PYTHON_HOST/"

# patch_ingress_hosts_and_wait — (re-)patches the Ingress's two `host`
# values to the live nip.io hostnames and blocks until nginx-ingress is
# actually routing them. MUST be called again after every `kubectl apply -k`
# that touches base/ingress.yaml (Step 4's initial apply AND Step 7's
# overlay switch) — confirmed live: `kubectl apply -k` re-applies the
# OVERLAY's static placeholder hosts verbatim, silently clobbering this
# live patch, so skipping the re-patch after Step 7's apply broke the WS
# checks with the exact same symptom as below.
#
# A plain curl exit code is NOT enough to confirm the patch has taken
# effect: nginx-ingress's own generic default-backend 404 page ALSO answers
# with HTTP-something-and-exit-0 for an unmatched host while the controller
# is still reloading (config reload is asynchronous, typically a few
# seconds) — confirmed live: the very first probe right after a patch
# returned a 404 that LOOKED like a real answer but was actually the
# default backend, and the WebSocket check that followed immediately after
# failed with that same 404. The `nginx.ingress.kubernetes.io/affinity: cookie`
# annotation on THIS Ingress (base/ingress.yaml) sets a
# `part4-backplane-affinity` cookie on every response that actually went
# through OUR rule — the default backend never sets it — so grepping for
# that cookie is a deterministic "the reload has actually happened" signal,
# not a fixed guess at how long reloads take.
patch_ingress_hosts_and_wait() {
  kubectl patch ingress part4-backplane -n "$NAMESPACE" --type=json -p "$(cat <<EOF
[
  {"op": "replace", "path": "/spec/rules/0/host", "value": "$QUARKUS_HOST"},
  {"op": "replace", "path": "/spec/rules/1/host", "value": "$PYTHON_HOST"}
]
EOF
)"
  local h waited ok
  for h in "$QUARKUS_HOST" "$PYTHON_HOST"; do
    waited=0
    ok=0
    while (( waited < 60 )); do
      if curl -sS -D - -o /dev/null "http://$h/" 2>/dev/null | grep -qi "part4-backplane-affinity"; then
        ok=1
        break
      fi
      sleep 2
      waited=$(( waited + 2 ))
    done
    if [[ "$ok" -ne 1 ]]; then
      echo "verify-minikube.sh: FAIL — ingress never routed Host: $h to our rule (no affinity cookie seen) within 60s" >&2
      exit 1
    fi
    echo "verify-minikube.sh: ingress routing confirmed for Host: $h after ${waited}s"
  done
}

step "Step 5b: patch the Ingress to the live nip.io hostnames"
patch_ingress_hosts_and_wait

# ===========================================================================
# run_stack_checks — one stack's full proof set over whichever backplane
# mode is currently deployed (the caller names it only for log labeling;
# the live BACKPLANE_MODE comes from whichever overlay was last applied).
#
#   stack          "quarkus" | "python"
#   broker_label   "kafka" | "redis" (log label only)
#   ws_host        the Ingress host header for instance A's WS
#   ws_port_note   informational only (A always listens on the port the
#                  Ingress rule for ws_host points at)
#   self_base      in-cluster URL base for instance A's OWN inject endpoint
#                  (used only by the idle-hold-then-late-frame check)
#   cross_base     in-cluster URL base for instance B's inject endpoint
#                  (used by the Ch18 fan-out check)
#   exec_deploy_a  Deployment to `kubectl exec` into (always instance A —
#                  it always has curl, same binary the compose healthcheck
#                  already uses)
#   container      container name inside that Deployment
#   deploy_a_log   Deployment whose logs prove "instance A delivered it"
# ===========================================================================
run_stack_checks() {
  local stack="$1" broker_label="$2" ws_host="$3" self_base="$4" cross_base="$5" \
        exec_deploy_a="$6" container="$7" deploy_a_log="$8"
  local path booking_id frames

  echo
  echo "--- $stack/$broker_label: seed frame + schema validation ---"
  booking_id="$(gen_id bkg_)"
  path="$(channel_path "$booking_id")"
  frames="$(ws_frames_n "ws://${ws_host}${path}" 3 30)"
  local last_frame last_event_id
  last_frame="$(tail -n1 <<<"$frames")"
  last_event_id="$(json_field '.eventId' <<<"$last_frame")"
  assert_eq "$LAST_SEED_EVENT_ID" "$last_event_id" "$stack/$broker_label: 3rd seed frame is the fixture's CUSTOMS event"
  schema_validate "$last_frame" "$SCHEMA_FILE"
  echo "verify-minikube.sh: ok — $stack/$broker_label: seed frame received through the ingress and is schema-valid" >&2

  echo
  echo "--- $stack/$broker_label: idle-hold past 60s, then a late frame must still arrive (proves the raised proxy timeouts) ---"
  booking_id="$(gen_id bkg_)"
  path="$(channel_path "$booking_id")"
  local idle_log idle_pid
  idle_log="$(mktemp -t "part4-backplane-k8s-idle-${stack}.XXXXXX.log")"
  idle_pid="$(ws_connect_bg "ws://${ws_host}${path}" "$idle_log")"
  BG_PIDS+=("$idle_pid")
  wait_for_log_count "$idle_log" '"eventType":"CUSTOMS"' 1 20
  echo "verify-minikube.sh: $stack/$broker_label: connected, received the 3 seed frames; holding idle for 65s (nginx's default proxy-read-timeout is 60s) ..." >&2
  sleep 65
  local late_event_id
  late_event_id="$(gen_id evt_)"
  inject_event_k8s "$exec_deploy_a" "$container" "$self_base" "$booking_id" "$late_event_id"
  wait_for_log_pattern "$idle_log" "\"eventId\":\"${late_event_id}\"" 30
  echo "verify-minikube.sh: ok — $stack/$broker_label: late frame arrived after a 65s idle hold — the raised proxy-read-timeout/proxy-send-timeout annotations are working" >&2
  kill "$idle_pid" >/dev/null 2>&1 || true
  wait "$idle_pid" 2>/dev/null || true
  rm -f "$idle_log"

  echo
  echo "--- $stack/$broker_label: Ch18 cross-pod fan-out — instance A (ingress) <- instance B (in-cluster inject) ---"
  booking_id="$(gen_id bkg_)"
  path="$(channel_path "$booking_id")"
  local fanout_log fanout_pid
  fanout_log="$(mktemp -t "part4-backplane-k8s-fanout-${stack}.XXXXXX.log")"
  fanout_pid="$(ws_connect_bg "ws://${ws_host}${path}" "$fanout_log")"
  BG_PIDS+=("$fanout_pid")
  wait_for_log_count "$fanout_log" '"eventType":"CUSTOMS"' 1 20
  sleep 2 # let the backplane subscription settle (same grace window as verify.sh's compose version)
  local fanout_event_id
  fanout_event_id="$(gen_id evt_)"
  inject_event_k8s "$exec_deploy_a" "$container" "$cross_base" "$booking_id" "$fanout_event_id"
  wait_for_log_pattern "$fanout_log" "\"eventId\":\"${fanout_event_id}\"" 30
  echo "verify-minikube.sh: ok — $stack/$broker_label: instance A's CLIENT (through the ingress) received instance B's injected event $fanout_event_id" >&2
  wait_for_k8s_log_pattern "$deploy_a_log" "delivered eventId=${fanout_event_id} bookingId=${booking_id} instance=${stack}-a" 30
  echo "verify-minikube.sh: ok — $stack/$broker_label: instance A's own POD LOG shows it delivering" >&2
  kill "$fanout_pid" >/dev/null 2>&1 || true
  wait "$fanout_pid" 2>/dev/null || true
  rm -f "$fanout_log"
}

# ===========================================================================
step "Step 6: live proof over the KAFKA backplane (primary mode) — both stacks"
# ===========================================================================
run_stack_checks "quarkus" "kafka" "$QUARKUS_HOST" \
  "http://localhost:8080" "http://quarkus-b:8080" \
  "quarkus-a" "quarkus" "quarkus-a"

run_stack_checks "python" "kafka" "$PYTHON_HOST" \
  "http://localhost:8082" "http://python-b:8082" \
  "python-a" "python" "python-a"

echo
echo "=== Step 6 complete: seed + idle-hold + Ch18 Kafka fan-out PROVEN LIVE on both stacks ==="

# ===========================================================================
step "Step 7: switch to the REDIS backplane toggle (overlays/minikube-redis) and re-prove Ch18 fan-out"
# ===========================================================================
kubectl apply -k "$SCRIPT_DIR/overlays/minikube-redis"
# envFrom/configMapRef does NOT hot-reload into running Pods — force a
# rollout so every instance picks up BACKPLANE_MODE=redis.
for d in quarkus-a quarkus-b python-a python-b; do
  kubectl rollout restart "deployment/$d" -n "$NAMESPACE"
done
for d in quarkus-a quarkus-b python-a python-b; do
  kubectl rollout status "deployment/$d" -n "$NAMESPACE" --timeout=180s
done
# The apply above re-applied base/ingress.yaml's STATIC placeholder hosts,
# clobbering Step 5b's live patch — re-patch before trusting the Ingress
# again (see patch_ingress_hosts_and_wait's doc comment).
patch_ingress_hosts_and_wait

run_stack_checks "quarkus" "redis" "$QUARKUS_HOST" \
  "http://localhost:8080" "http://quarkus-b:8080" \
  "quarkus-a" "quarkus" "quarkus-a"

run_stack_checks "python" "redis" "$PYTHON_HOST" \
  "http://localhost:8082" "http://python-b:8082" \
  "python-a" "python" "python-a"

echo
echo "=== Step 7 complete: Ch18 Redis fan-out PROVEN LIVE on both stacks (toggle overlay works) ==="

# ===========================================================================
echo
echo "PASS — part4-backplane on minikube (docker+containerd, Kubernetes $KUBERNETES_VERSION):" \
     "ingress-nginx delivers a schema-valid seed frame on both stacks, the raised" \
     "proxy-read-timeout/proxy-send-timeout annotations keep an idle WS open past" \
     "nginx's 60s default, and the Ch18 cross-pod fan-out proof holds over BOTH" \
     "the Strimzi-managed Kafka backplane and the Redis toggle overlay, with" \
     "instance A's own pod log confirming every delivery."
echo "exit 0"
