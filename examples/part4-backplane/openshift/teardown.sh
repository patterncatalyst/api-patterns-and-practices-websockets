#!/usr/bin/env bash
#
# teardown.sh — return OpenShift Local to a clean state, then stop it.
#
# This CRC is dedicated to part4-backplane while it runs, and is cleaned
# after every use, so teardown removes everything the openshift/ scripts
# added: the Helm release (four app Deployments/Services, Redis, the two
# Routes, the ConfigMap), the Kafka cluster and the part4-backplane project
# (BuildConfigs, ImageStreams, builds), and the AMQ Streams operator
# (Subscription, CSV, InstallPlans, the CRDs it owns). Operands go while
# their operator still runs, so no finalizer is left waiting on an operator
# that is already gone (KafkaTopic/KafkaUser finalizers in particular —
# known-issue #20 in the lgtm-crc skill this was adapted from).
#
#   ./openshift/teardown.sh                 # clean up, then crc stop
#   ./openshift/teardown.sh --keep-running  # clean up, leave CRC running
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

KEEP_RUNNING=false
[[ "${1:-}" == "--keep-running" ]] && KEEP_RUNNING=true

require_crc
gone() { ! oc get "$@" >/dev/null 2>&1; }
has_crd() { oc get crd "$1" >/dev/null 2>&1; }
# A label selector with no matches still exits 0, so test for empty output.
kafka_pods_gone() { [[ -z "$(oc get pod -n "$NS" -l "strimzi.io/cluster=$PROJECT" -o name 2>/dev/null)" ]]; }

PLATFORM_CRDS='\.strimzi\.io$'

step "1/5 Helm release + Kafka operands"
if helm status "$RELEASE" -n "$NS" >/dev/null 2>&1; then
    # While AMQ Streams still runs (its own CRDs/webhooks are still present).
    helm uninstall "$RELEASE" -n "$NS" --wait >/dev/null || fail "helm uninstall"
    ok "release $RELEASE uninstalled"
else
    ok "no release $RELEASE"
fi
if has_crd kafkas.kafka.strimzi.io && oc get project "$NS" >/dev/null 2>&1; then
    # KafkaTopics/KafkaUsers first: their strimzi.io/topic-operator finalizer
    # would hang the namespace in Terminating once the operator is gone.
    oc delete kafkatopics.kafka.strimzi.io,kafkausers.kafka.strimzi.io --all -n "$NS" --wait=true --timeout=120s >/dev/null 2>&1
    oc delete kafka,kafkanodepool --all -n "$NS" --wait=true --timeout=300s >/dev/null || fail "delete Kafka"
    wait_for 300 "Kafka pods gone" kafka_pods_gone
fi
ok "release and Kafka operands removed"

step "2/5 Project $NS"
if oc get project "$NS" >/dev/null 2>&1; then
    oc delete project "$NS" --wait=false >/dev/null || fail "delete project"
    wait_for 600 "project $NS deleted" gone namespace "$NS"
else
    ok "no project"
fi

step "3/5 AMQ Streams operator"
if oc get subscriptions.operators.coreos.com amq-streams -n openshift-operators >/dev/null 2>&1; then
    csv="$(oc get subscriptions.operators.coreos.com amq-streams -n openshift-operators -o jsonpath='{.status.installedCSV}' 2>/dev/null)"
    oc delete subscriptions.operators.coreos.com amq-streams -n openshift-operators --ignore-not-found >/dev/null
    if [[ -n "$csv" ]]; then
        owned="$(oc get csv "$csv" -n openshift-operators -o jsonpath='{range .spec.customresourcedefinitions.owned[*]}{.name}{"\n"}{end}' 2>/dev/null)"
        oc delete csv "$csv" -n openshift-operators --wait=true >/dev/null 2>&1
        for ip in $(oc get installplan -n openshift-operators -o json 2>/dev/null | jq -r --arg c "$csv" '.items[] | select(.spec.clusterServiceVersionNames | index($c)) | .metadata.name'); do
            oc delete installplan "$ip" -n openshift-operators >/dev/null 2>&1
        done
        # shellcheck disable=SC2086
        [[ -n "$owned" ]] && oc delete crd $owned --ignore-not-found --wait=true >/dev/null 2>&1
        ok "$csv removed with $(wc -w <<<"$owned") CRD(s)"
    fi
else
    ok "no amq-streams Subscription"
fi

step "4/5 Remaining Kafka CRDs"
crds="$(oc get crd -o name | grep -E "$PLATFORM_CRDS")"
# shellcheck disable=SC2086
[[ -n "$crds" ]] && oc delete $crds --wait=true >/dev/null 2>&1
ok "no kafka.strimzi.io CRDs left"

step "5/5 Leftover inventory"
leftover="$(
    oc get subscriptions.operators.coreos.com -A --no-headers 2>/dev/null
    oc get csv -n openshift-operators --no-headers 2>/dev/null | grep -v -E '^packageserver'
    oc get ns --no-headers -o name | grep -v -E '^namespace/(openshift|kube-|default$|hostpath-provisioner$)'
    oc get crd -o name | grep -E "$PLATFORM_CRDS"
)"
if [[ -z "$leftover" ]]; then
    ok "CRC is clean"
else
    printf '    note: still present (flag it; remove only with approval if another project left it):\n%s\n' "$leftover"
fi

if [[ "$KEEP_RUNNING" == false ]]; then
    step "crc stop"
    crc stop >/dev/null 2>&1 && ok "OpenShift Local stopped" || fail "crc stop"
fi
