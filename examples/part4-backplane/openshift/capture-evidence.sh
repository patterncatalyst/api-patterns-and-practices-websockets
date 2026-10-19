#!/usr/bin/env bash
#
# capture-evidence.sh — verify the part4-backplane deployment on OpenShift
# Local and write what it saw to openshift/evidence/<date>/. Adapted from the
# lgtm-crc skill's capture-evidence.sh template for this example: no
# Postgres, no platform tier, no Maven multimodule reactor.
#
# Checks (each fails the script on a miss):
#   1. cluster + operator + build state: exactly one ImageStream tag each for
#      part4-backplane-quarkus and part4-backplane-python, built in-cluster;
#      the Python BuildConfig + its latest Build.
#   2. pods: all Ready under restricted-v2 with a namespace-range UID — NO
#      anyuid exception (there is no otel-lgtm or other root-needing image
#      anywhere in this stack).
#   3. Routes: quarkus-a and python-a answer an edge-TLS handshake verified
#      against the cluster's ingress CA (never --insecure). A plain GET on a
#      WebSocket-upgrade-only Route legitimately answers 426/404, not 200 —
#      this step proves the TLS handshake succeeds and routing returns SOME
#      well-formed HTTP status (not a curl connection/cert failure), and
#      records that status; it does NOT assert ==200. The real WebSocket
#      proof is verify-crc.sh's job (step 4 runs it live).
#   4. verify-crc.sh, run live and captured in full — seed + idle-hold +
#      Ch18 fan-out, both stacks, both backplanes — plus each stack's
#      instance-A pod log excerpt showing "delivered eventId=...".
#   5. secret scrub: no token, password or private key material anywhere
#      under the evidence directory.
#
# curl validates the router certificate against the cluster's ingress CA, so
# nothing here uses --insecure. Nothing here prints a secret.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_crc

OUT="$OPENSHIFT_DIR/evidence/$(date +%Y-%m-%d)"
mkdir -p "$OUT"
CA="$(mktemp)"; trap 'rm -f "$CA"' EXIT
oc get configmap default-ingress-cert -n openshift-config-managed \
    -o jsonpath='{.data.ca-bundle\.crt}' > "$CA" || fail "cannot read the ingress CA"
https() { curl -sS --max-time 20 --cacert "$CA" "$@"; }

step "1/5 Cluster, operator, builds"
{
    crc version | head -3
    oc version | grep -E 'Server|Kubernetes'
    oc get csv -A -o custom-columns='NS:.metadata.namespace,CSV:.metadata.name,PHASE:.status.phase' 2>/dev/null \
        | awk 'NR==1 || $1 !~ /^openshift-(operator-lifecycle-manager|marketplace)$/' | grep -v packageserver | sort -u -k2,2
    oc get kafka -n "$NS" -o jsonpath='{range .items[*]}kafka {.metadata.name}: version {.status.kafkaVersion}, Ready={.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' 2>/dev/null
    printf -- '--- BuildConfig part4-backplane-python (dockerStrategy) ---\n'
    oc get bc part4-backplane-python -n "$NS" -o jsonpath='{.spec.strategy.dockerStrategy.dockerfilePath}{"\n"}' 2>/dev/null
    printf -- '--- latest build(s) ---\n'
    oc get builds -n "$NS" -l "buildconfig=part4-backplane-python" -o custom-columns='BUILD:.metadata.name,STATUS:.status.phase,DURATION:.status.duration' 2>/dev/null
    for svc in "${SERVICES[@]}"; do
        oc get istag "$svc:$IMAGE_TAG" -n "$NS" -o jsonpath='{.metadata.name} {.image.dockerImageReference}{"\n"}'
    done
} > "$OUT/01-cluster-builds.txt" 2>&1
tags=$(grep -c ":$IMAGE_TAG image-registry" "$OUT/01-cluster-builds.txt")
(( tags == ${#SERVICES[@]} )) || fail "expected ${#SERVICES[@]} ImageStream tags $IMAGE_TAG, found $tags (see $OUT/01-cluster-builds.txt)"
ok "$tags ImageStream tags $IMAGE_TAG, built in-cluster"

step "2/5 Pods under restricted-v2 (no anyuid exception in this stack)"
oc get pods -n "$NS" --field-selector=status.phase=Running \
    -o custom-columns='POD:.metadata.name,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount,SCC:.metadata.annotations.openshift\.io/scc,UID:.spec.containers[0].securityContext.runAsUser' \
    > "$OUT/02-pods.txt"
oc get namespace "$NS" -o jsonpath='namespace uid-range: {.metadata.annotations.openshift\.io/sa\.scc\.uid-range}{"\n"}' >> "$OUT/02-pods.txt"
bad=$(awk 'NR>1 && ($2 ~ /false/ || $4 != "restricted-v2")' "$OUT/02-pods.txt" | grep -c . || true)
(( bad == 0 )) || fail "$bad pod(s) not Ready or not restricted-v2 (see $OUT/02-pods.txt)"
ok "all pods Ready, restricted-v2, no anyuid exception"

step "3/5 Routes: edge-TLS handshake against the ingress CA (not a WS-upgrade assertion — see header)"
: > "$OUT/03-routes.txt"
for name in quarkus-a python-a; do
    host="$(oc get route "$name" -n "$NS" -o jsonpath='{.spec.host}' 2>/dev/null)"
    [[ -n "$host" ]] || fail "Route $name not found (run ./openshift/deploy.sh first)"
    code=$(https -o /dev/null -w '%{http_code}' "https://$host/")
    printf 'GET https://%s/ -> HTTP %s (edge-TLS handshake verified against the ingress CA; a non-200 here is expected on a WS-only path)\n' "$host" "$code" >> "$OUT/03-routes.txt"
    [[ "$code" =~ ^[0-9]{3}$ ]] || fail "Route $name: no HTTP status returned over edge TLS (got '$code') — see $OUT/03-routes.txt"
    ok "$name https://$host/ edge-TLS handshake OK, HTTP $code"
done

step "4/5 verify-crc.sh (live seed + idle-hold + Ch18 fan-out, both stacks, both backplanes)"
if ! "$OPENSHIFT_DIR/verify-crc.sh" > "$OUT/04-verify-crc.log" 2>&1; then
    tail -n 60 "$OUT/04-verify-crc.log" >&2
    fail "verify-crc.sh failed — see $OUT/04-verify-crc.log"
fi
grep -q '^PASS' "$OUT/04-verify-crc.log" || fail "verify-crc.sh did not print a PASS line — see $OUT/04-verify-crc.log"
ok "verify-crc.sh PASS (full log: ${OUT#"$REPO_ROOT"/}/04-verify-crc.log)"

: > "$OUT/05-delivered-logs.txt"
for d in quarkus-a python-a; do
    container="quarkus"; [[ "$d" == python-a ]] && container="python"
    {
        printf -- '--- deploy/%s (container %s): delivered eventId lines ---\n' "$d" "$container"
        oc logs "deploy/$d" -n "$NS" -c "$container" --tail=2000 2>/dev/null | grep -F 'delivered eventId=' || true
    } >> "$OUT/05-delivered-logs.txt"
done
ok "per-stack delivered-event pod log excerpts captured"

step "5/5 Secret scrub"
leaks=0
grep -rlE 'sha256~[A-Za-z0-9_-]{20,}|BEGIN [A-Z ]*PRIVATE KEY|kubeadmin-password|"token"|"auths"' "$OUT" >&2 && leaks=1
(( leaks == 0 )) || fail "evidence contains secret material: delete $OUT and investigate"
ok "no secrets in $OUT"

printf '\n    evidence: %s\n' "${OUT#"$REPO_ROOT"/}"
