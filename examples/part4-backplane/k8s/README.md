# part4-backplane: minikube deploy

Deploys the same four-instance topology `../compose.yaml` runs locally
(`quarkus-a`/`quarkus-b`, `python-a`/`python-b`) to a real Kubernetes cluster
(minikube, docker driver + containerd runtime; podman is **not**
supported) behind an ingress-nginx edge, with the backplane now a
Strimzi-managed Kafka cluster (primary mode) or Redis (a toggle overlay),
instead of compose's single-container brokers. See `../PROTOCOL.md` for the
wire/behavior contract both stacks implement identically: nothing about
*that* contract changes here, only where it runs.

## Layout

```
base/                   Namespace, ConfigMap, the four app Deployments+Services,
                         the ingress-nginx Ingress (routes to instance A only)
overlays/minikube/      retags images to :minikube, imagePullPolicy: Never,
                         rewrites the Ingress hosts
overlays/minikube-redis/  ../minikube + the redis-mode component (BACKPLANE_MODE: redis)
components/redis-mode/  Kustomize Component — flips the ConfigMap's
                         BACKPLANE_MODE from kafka to redis; nothing else changes
strimzi/                KafkaNodePool + Kafka CR (single-node KRaft, ephemeral)
                         and the Redis Deployment+Service — cluster infra,
                         applied separately from the app kustomization (see
                         scripts/install-strimzi.sh) because the Strimzi CRDs
                         have to exist first
scripts/install-strimzi.sh   installs the Strimzi operator (Helm), waits for
                         it, applies strimzi/*.yaml, waits for Kafka Ready —
                         MUST complete before the apps roll out (see below)
verify-minikube.sh       the live, headless proof (see "Running it")
evidence/                captured output from a real run, for the chapter to cite
```

## Why Kafka has to be Ready before the apps roll out

The Quarkus side's `quarkus-messaging-kafka` channels are wired
unconditionally (see `../quarkus/application.properties`'s note): handing
that always-on consumer an **unresolvable** bootstrap hostname crashes the
app at startup with `ConfigException: No resolvable bootstrap urls` (a hard
CDI failure), not the soft "unreachable but resolvable" case Quarkus's own
docs describe. `scripts/install-strimzi.sh` installs the operator, applies
the Kafka CR, and blocks on `kubectl wait kafka/my-cluster --for=condition=Ready`
before returning. Run it (or `verify-minikube.sh`, which calls it) before
`kubectl apply -k overlays/minikube`, never after.

## The Kafka/Redis toggle

`base/configmap.yaml` ships `BACKPLANE_MODE: kafka`: the primary mode for
this deploy (replay + fan-out). `components/redis-mode` is a
Kustomize Component that patches just that one ConfigMap key to `redis`;
`overlays/minikube-redis/kustomization.yaml` composes it on top of
`overlays/minikube`. Switching modes on an already-running cluster:

```sh
kubectl --context part4-backplane apply -k overlays/minikube-redis
# envFrom/configMapRef does NOT hot-reload into running Pods — force it:
kubectl --context part4-backplane rollout restart \
  deployment/quarkus-a deployment/quarkus-b deployment/python-a deployment/python-b \
  -n part4-backplane
```

The Strimzi Kafka cluster stays installed either way: `strimzi/kafka.yaml`
is applied once by `install-strimzi.sh` regardless of which backplane mode
the apps are currently routed through (Kafka's always-wired consumer channel
needs it resolvable even in redis mode; see above).

## Why instance B is never behind the Ingress

The Ingress (`base/ingress.yaml`) only has rules for `quarkus-a` and
`python-a`. Instance B represents the "other pod in the fleet" for the
cross-pod fan-out proof. `POST /internal/bookings/{id}/handling-events` is
explicitly documented (`../PROTOCOL.md` "Inject endpoint") as internal/demo,
not part of the public contract, so it is reached only from inside the
cluster: `kubectl exec` into instance A's own Pod and curl instance B's
Service by its cluster-DNS name (`http://quarkus-b:8080/...`,
`http://python-b:8082/...`). Nothing in this example's verification ever
uses `kubectl port-forward`: every in-cluster check is `kubectl exec` (to
reach a Service) or `kubectl logs` (to read a Pod's own log); the only thing
that crosses the cluster boundary from the host machine is the WebSocket
client itself, through the Ingress.

## Running it

```sh
./verify-minikube.sh            # full run; tears the minikube profile down at the end
./verify-minikube.sh --keep     # leave the profile running afterward (inspect with kubectl)
```

This is slow: cluster bring-up, two image builds, the Strimzi operator,
three `kubectl apply -k` rollouts (kafka, then redis). Expect 10-20 minutes
depending on image pull/build cache state. It proves, live:

1. A schema-valid `HandlingEvent` seed frame through the Ingress, both stacks.
2. The raised `proxy-read-timeout`/`proxy-send-timeout` annotations keep an
   idle WebSocket connection open **past** ingress-nginx's 60s default:
   holds the socket 65s with no traffic, then asserts a late frame still
   arrives.
3. The cross-pod fan-out proof (client on instance A via the Ingress,
   inject through instance B in-cluster, instance A's own pod log confirms
   delivery), once over Kafka, once over Redis (the toggle above).

Named `verify-minikube.sh`, not `verify.sh`, and placed in this
`k8s/` subdirectory: the repo's `examples` CI matrix glob only picks up
`examples/*/verify.sh` (compose-based, no minikube available in that job),
so this script is never swept into it.

## Manual steps (if you don't want the full scripted run)

```sh
PROFILE=part4-backplane
minikube start -p "$PROFILE" --driver=docker --container-runtime=containerd --kubernetes-version=v1.37.1
minikube addons enable ingress -p "$PROFILE"

docker build -f ../quarkus/Containerfile -t part4-backplane-quarkus:minikube ../../..
docker build -f ../python/Containerfile  -t part4-backplane-python:minikube  ../../..
minikube image load part4-backplane-quarkus:minikube -p "$PROFILE"
minikube image load part4-backplane-python:minikube  -p "$PROFILE"

PROFILE="$PROFILE" NAMESPACE=part4-backplane ./scripts/install-strimzi.sh
kubectl --context "$PROFILE" apply -k overlays/minikube

MINIKUBE_IP="$(minikube ip -p "$PROFILE")"
curl -H "Host: quarkus.part4-backplane.minikube.local" "http://$MINIKUBE_IP/"
```

Pinned versions: see the version matrix.
