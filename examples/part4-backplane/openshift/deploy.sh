#!/usr/bin/env bash
#
# deploy.sh — install or upgrade the part4-backplane Helm chart on OpenShift
# Local and wait until every workload has rolled out.
#
#   ./openshift/deploy.sh
#   ./openshift/deploy.sh --set backplane=redis   # toggle to the Redis
#                                                  # backplane (verify-crc.sh
#                                                  # does this itself, plus
#                                                  # the rollout restart
#                                                  # envFrom needs)
#
# Values set earlier are kept (--reset-then-reuse-values), so a bare re-run
# does not reset backplane back to kafka.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_crc
command -v helm >/dev/null 2>&1 || fail "helm not on PATH"
if oc get crd kafkas.kafka.strimzi.io >/dev/null 2>&1 && oc get kafka "$PROJECT" -n "$NS" >/dev/null 2>&1; then
    oc wait "kafka/$PROJECT" -n "$NS" --for=condition=Ready --timeout=10s >/dev/null 2>&1 \
        || fail "Kafka $PROJECT not Ready: run ./openshift/install-infra.sh first"
fi
for svc in "${SERVICES[@]}"; do
    oc get istag "$svc:$IMAGE_TAG" -n "$NS" >/dev/null 2>&1 || fail "image $svc:$IMAGE_TAG missing: run ./openshift/build-images.sh"
done

step "helm upgrade --install $RELEASE"
helm upgrade --install "$RELEASE" "$CHART_DIR" \
    --namespace "$NS" --create-namespace --reset-then-reuse-values \
    --set imageTag="$IMAGE_TAG" "$@" >/dev/null \
    || fail "helm upgrade --install failed"
ok "release $RELEASE applied"

step "Waiting for workloads"
# rollout status, not condition=Available: on an upgrade the old ReplicaSet
# stays Available until the new pods are Ready, so Available passes early.
for d in $(oc get deployment -n "$NS" -l "app.kubernetes.io/part-of=$RELEASE" -o name); do
    oc rollout status "$d" -n "$NS" --timeout=300s >/dev/null || fail "$d did not roll out (oc get pods -n $NS)"
done
ok "all deployments rolled out"
oc get pods -n "$NS" -l "app.kubernetes.io/part-of=$RELEASE" --field-selector=status.phase=Running \
    -o custom-columns='POD:.metadata.name,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount,UID:.spec.containers[0].securityContext.runAsUser,SCC:.metadata.annotations.openshift\.io/scc'
oc get routes -n "$NS" -o custom-columns='ROUTE:.metadata.name,HOST:.spec.host'
