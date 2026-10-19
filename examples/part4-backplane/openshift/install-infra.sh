#!/usr/bin/env bash
#
# install-infra.sh — the part4-backplane project on OpenShift Local (CRC),
# plus Kafka from the AMQ Streams operator (pinned, from OperatorHub). Redis
# ships in the Helm chart (openshift/helm/part4-backplane), not here — there
# is no operator managing it, so there is nothing to install ahead of time.
#
# Idempotent: re-running skips what already exists. Undo with teardown.sh.
# Never starts or stops the cluster itself.
#
#   eval "$(crc oc-env)"
#   ./openshift/install-infra.sh
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

# Surveyed live on CRC 2026-10-19: this is the current newest AMQ Streams CSV
# (stable / amq-streams-3.2.x). It supports Kafka 4.1.0/4.2.0 only, so
# infra/kafka.yaml pins 4.2.0 (recorded step-back from the 4.3.1 used on
# compose/minikube) — see that file and infra/amq-streams-subscription.yaml.
# Keep this var, the Subscription's startingCSV, and kafka.yaml's version in
# step whenever a newer AMQ Streams ships.
CSV="amqstreams.v3.2.1-14"

require_crc

step "1/3 Project $NS"
if oc get project "$NS" >/dev/null 2>&1; then
    ok "project $NS exists"
else
    oc new-project "$NS" --display-name="part4-backplane (WebSockets + Kafka/Redis backplane, OpenShift Local)" >/dev/null \
        || fail "oc new-project $NS"
    ok "project $NS created"
fi

step "2/3 AMQ Streams operator ($CSV)"
refuse_foreign_subscription amq-streams openshift-operators/amq-streams "$CSV"
install_operator "$OPENSHIFT_DIR/infra/amq-streams-subscription.yaml" openshift-operators amq-streams "$CSV"

step "3/3 Kafka cluster $PROJECT (KRaft, 1 dual-role node)"
oc apply -n "$NS" -f "$OPENSHIFT_DIR/infra/kafka.yaml" >/dev/null || fail "apply Kafka"
oc wait "kafka/$PROJECT" -n "$NS" --for=condition=Ready --timeout=900s >/dev/null \
    || fail "Kafka $PROJECT not Ready (oc get pods -n $NS; oc describe kafka $PROJECT -n $NS) — see infra/kafka.yaml's TODO(pin survey D0) if this is an unsupported-version error"
ok "Kafka $PROJECT Ready"
oc get kafka "$PROJECT" -n "$NS" -o jsonpath='    kafka {.status.kafkaVersion}, bootstrap {.status.listeners[0].bootstrapServers}{"\n"}'
printf '    next: ./openshift/build-images.sh, then ./openshift/deploy.sh\n'
