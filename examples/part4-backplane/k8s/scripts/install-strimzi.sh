#!/usr/bin/env bash
# examples/part4-backplane/k8s/scripts/install-strimzi.sh
#
# Installs the Strimzi Kafka operator (Helm, pinned) into the app namespace,
# waits for it to be Available, then applies the Kafka CR
# (../strimzi/kafka.yaml) and Redis (../strimzi/redis.yaml) and waits for
# BOTH to be Ready — this ordering is the whole point of this script: the
# Quarkus app's Kafka consumer is ALWAYS wired (see
# quarkus/application.properties's note), and handing it an unresolvable
# bootstrap hostname crashes it at startup with
# `ConfigException: No resolvable bootstrap urls` — a hard CDI failure, not
# the soft "unreachable but resolvable" case. Running this script to
# completion BEFORE `kubectl apply -k overlays/minikube` guarantees the
# `my-cluster-kafka-bootstrap` Service (and therefore its DNS name) exists
# and the Kafka cluster behind it is Ready before any app Pod starts.
#
# Idempotent: Helm upgrade --install + kubectl apply + kubectl wait, so
# re-running resumes safely.
#
# Pins (see ../../../_plans/version-matrix.md "Kubernetes / minikube
# (Part 7)"):
#   Strimzi operator  1.3.0  (Helm chart oci://quay.io/strimzi-helm/strimzi-kafka-operator)
#   Kafka             4.3.1  (Strimzi 1.3.0's own default; matches compose.yaml)
#   Redis             8.10.2-alpine (matches compose.yaml; applied here too)
#
# Usage: PROFILE=part4-backplane NAMESPACE=part4-backplane ./install-strimzi.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PROFILE="${PROFILE:-part4-backplane}"
NAMESPACE="${NAMESPACE:-part4-backplane}"
STRIMZI_VERSION="${STRIMZI_VERSION:-1.3.0}"

# Every kubectl/helm call targets the profile's context explicitly —
# kubectl's current-context is never read or changed (house convention; see
# modernizing-enterprise-applications/deploy/k8s/scripts/lib.sh and the
# lgtm-minikube-stack skill's templates).
kubectl() { command kubectl --context "$PROFILE" "$@"; }
helm()    { command helm --kube-context "$PROFILE" "$@"; }

step() { printf '\n==> %s\n' "$*"; }

step "Namespace $NAMESPACE"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f - >/dev/null

step "Strimzi cluster operator $STRIMZI_VERSION (Helm, into $NAMESPACE)"
helm upgrade --install strimzi-cluster-operator \
  oci://quay.io/strimzi-helm/strimzi-kafka-operator \
  --version "$STRIMZI_VERSION" \
  --namespace "$NAMESPACE" --create-namespace

step "Waiting for the Strimzi operator to be Available"
kubectl rollout status deployment/strimzi-cluster-operator -n "$NAMESPACE" --timeout=180s

step "Waiting for Strimzi CRDs to be Established"
for crd in kafkas.kafka.strimzi.io kafkanodepools.kafka.strimzi.io; do
  kubectl wait --for=condition=Established "crd/$crd" --timeout=60s
done

step "Applying the Kafka CR (KafkaNodePool + Kafka, single-node KRaft, ephemeral)"
kubectl apply -n "$NAMESPACE" -f "$K8S_DIR/strimzi/kafka.yaml"

step "Applying Redis (Deployment + Service)"
kubectl apply -n "$NAMESPACE" -f "$K8S_DIR/strimzi/redis.yaml"

step "Waiting for Kafka cluster 'my-cluster' to be Ready (this is the slow step — can take several minutes on a cold pull)"
kubectl wait "kafka/my-cluster" -n "$NAMESPACE" --for=condition=Ready --timeout=480s

step "Waiting for Redis to be available"
kubectl rollout status deployment/redis -n "$NAMESPACE" --timeout=120s

step "Strimzi + Kafka + Redis ready in namespace $NAMESPACE"
kubectl get kafka,kafkanodepool -n "$NAMESPACE"
kubectl get deployment/redis -n "$NAMESPACE"
