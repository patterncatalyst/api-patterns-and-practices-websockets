# shellcheck shell=bash
# examples/part4-backplane/openshift/lib.sh
#
# Shared helpers for the openshift/ scripts (sourced, not run). Every
# oc/helm call targets the "crc-admin" kubeconfig context explicitly that
# `crc start` writes — current-context is never read or changed — so no
# password is ever typed, printed or stored. Run `eval "$(crc oc-env)"`
# first if `oc` is not on PATH.
#
# Adapted from the lgtm-crc skill's templates/openshift/lib.sh for THIS
# example: no Postgres, no Maven multimodule reactor, no platform tier (mesh/
# KEDA/observability/GitOps/AI/native) — just the AMQ Streams Kafka operator
# plus a Helm chart for the four app instances and Redis.
#
# verify-crc.sh does NOT source this file (it sources ../../_lib/lib.sh
# instead, which defines its own REPO_ROOT — sourcing both would clobber
# one's REPO_ROOT with the other's, exactly as ../../k8s/verify-minikube.sh
# deliberately does not source the k8s install scripts either).

PROJECT="part4-backplane"
NS="${PROJECT_NAMESPACE:-$PROJECT}"
RELEASE="${RELEASE:-$PROJECT}"
OCP_CONTEXT="${OCP_CONTEXT:-crc-admin}"
OPENSHIFT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# openshift/ -> part4-backplane -> examples -> repo root
REPO_ROOT="$(cd "$OPENSHIFT_DIR/../../.." && pwd)"
CHART_DIR="$OPENSHIFT_DIR/helm/$PROJECT"
# ImageStream tag every in-cluster build produces and the chart deploys.
IMAGE_TAG="${IMAGE_TAG:-v1}"

# The two ImageStream names built in-cluster (build-images.sh): the four app
# Deployments (quarkus-a/b, python-a/b) share these two images.
SERVICES=(part4-backplane-quarkus part4-backplane-python)

oc()   { command oc --context "$OCP_CONTEXT" "$@"; }
helm() { command helm --kube-context "$OCP_CONTEXT" "$@"; }

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
ok()   { printf '    \xe2\x9c\x93 %s\n' "$1"; }
warn() { printf '    ! %s\n' "$1" >&2; }
fail() { printf '\n\xe2\x9c\x97 %s\n' "$1" >&2; exit 1; }

# require_single_cluster: one local cluster at a time. A running minikube
# profile competes with the CRC VM for memory; stop it first.
require_single_cluster() {
    command -v minikube >/dev/null 2>&1 || return 0
    local running
    running="$(minikube profile list -o json 2>/dev/null \
        | jq -r '.valid[]? | select(.Status == "OK" or .Status == "Running") | .Name' 2>/dev/null)"
    [[ -z "$running" ]] || fail "minikube profile(s) running: $running. Stop them first (minikube stop -p <profile>); run one cluster at a time"
}

# require_crc: oc on PATH, the crc-admin context reachable, and the API
# server is OpenShift Local's. Fails fast instead of touching another cluster.
require_crc() {
    command -v oc >/dev/null 2>&1 || fail "oc not on PATH: run eval \"\$(crc oc-env)\""
    command -v crc >/dev/null 2>&1 || fail "crc not on PATH"
    command -v jq >/dev/null 2>&1 || fail "jq not on PATH"
    require_single_cluster
    crc status 2>/dev/null | grep -q 'OpenShift:.*Running' || fail "OpenShift Local is not running: crc start"
    command oc config get-contexts "$OCP_CONTEXT" >/dev/null 2>&1 \
        || fail "kubeconfig context $OCP_CONTEXT not found (crc start writes it)"
    local api
    api="$(oc whoami --show-server 2>/dev/null)" || fail "cannot reach the OpenShift API"
    [[ "$api" == *api.crc.testing* ]] || fail "context $OCP_CONTEXT points at $api, not OpenShift Local"
}

# require_crc_size <cpus> <memory-MiB>: the VM is configured at least this
# large. Sizing only takes effect while CRC is stopped (crc config set ...).
require_crc_size() {
    local want_cpu="$1" want_mem="$2" cpu mem
    cpu="$(crc config get cpus 2>/dev/null | awk '{print $NF}')"
    mem="$(crc config get memory 2>/dev/null | awk '{print $NF}')"
    [[ "$cpu" =~ ^[0-9]+$ && "$mem" =~ ^[0-9]+$ ]] || { warn "could not read crc cpus/memory; continuing"; return 0; }
    (( cpu >= want_cpu && mem >= want_mem )) \
        || fail "CRC is sized ${cpu} vCPU / ${mem} MiB; this needs ${want_cpu} / ${want_mem}: crc stop; crc config set cpus $want_cpu; crc config set memory $want_mem; crc start"
}

# wait_for <seconds> <description> <command...>: poll every 5 s until the
# command succeeds.
wait_for() {
    local timeout="$1" what="$2"; shift 2
    local waited=0
    until "$@" >/dev/null 2>&1; do
        (( waited >= timeout )) && fail "timed out after ${timeout}s waiting for $what"
        sleep 5; waited=$(( waited + 5 ))
    done
    ok "$what"
}

# install_operator <manifest> <namespace> <package> <csv>
# Applies an OLM manifest (Subscription, plus Namespace and OperatorGroup
# when the operator lives outside openshift-operators) whose Subscription
# pins <csv> with installPlanApproval: Manual and startingCSV, approves only
# the InstallPlan that lists <csv>, and waits for the CSV to succeed.
# Idempotent. Any other InstallPlan (an upgrade OLM proposes later) stays
# unapproved, so the version never moves without an edit here.
install_operator() {
    local manifest="$1" ns="$2" pkg="$3" csv="$4"
    _csv_ok() { [[ "$(oc get csv "$csv" -n "$ns" -o jsonpath='{.status.phase}' 2>/dev/null)" == Succeeded ]]; }
    _plan() {
        oc get installplan -n "$ns" -o json 2>/dev/null | jq -r --arg c "$csv" \
            '.items[] | select(.spec.clusterServiceVersionNames | index($c)) | .metadata.name' | head -1
    }
    _plan_proposed() { [[ -n "$(_plan)" ]]; }
    if _csv_ok; then ok "$csv already Succeeded"; return 0; fi
    # redhat-operators reports READY before it serves packages (about a
    # minute after crc start), so wait for the package itself.
    wait_for 300 "OperatorHub serves $pkg" oc get packagemanifest "$pkg" -n openshift-marketplace
    oc apply -f "$manifest" >/dev/null || fail "apply $manifest"
    wait_for 300 "InstallPlan for $csv proposed" _plan_proposed
    oc patch installplan "$(_plan)" -n "$ns" --type merge -p '{"spec":{"approved":true}}' >/dev/null \
        || fail "approve InstallPlan for $csv"
    wait_for 600 "$csv Succeeded" _csv_ok
}

# refuse_foreign_subscription <package> <expected-ns>/<expected-name> <csv>
# This CRC is dedicated to one project. A Subscription for the same package
# left by another project means the cluster was not cleaned up: stop.
refuse_foreign_subscription() {
    local pkg="$1" want="$2" csv="$3" existing
    existing="$(oc get subscriptions.operators.coreos.com -A -o json 2>/dev/null | jq -r --arg p "$pkg" \
        '.items[] | select(.spec.name == $p) | "\(.metadata.namespace)/\(.metadata.name) \(.status.installedCSV // "")"')"
    [[ -z "$existing" || "$existing" == "$want $csv" || "$existing" == "$want " ]] \
        || fail "a $pkg Subscription already exists ($existing); this CRC is dedicated to $PROJECT: run the other project's teardown first"
}

# helm_values_json: the release's user-supplied values, as JSON.
helm_values_json() { helm get values "$RELEASE" -n "$NS" -o json; }
