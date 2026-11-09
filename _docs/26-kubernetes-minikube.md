---
title: "Kubernetes (minikube)"
order: 26
part: "Runtime Progression"
description: "Running the four-instance WebSocket backplane on minikube behind ingress-nginx, with a Strimzi-managed Kafka and no registry."
duration: "16 min read"
---

## Learning objectives

By the end of this chapter you can:

- Get an image into a single-node cluster with `docker build` plus `minikube image load`, and explain why `imagePullPolicy: Never` is required.
- Layer a kustomize base, an overlay and a component so one Deployment, Service and Ingress set serves both backplane modes.
- Gate app startup on an operator-managed Kafka reaching `Ready`, and explain what crashes if you don't.
- Configure ingress-nginx for long-lived sockets (`proxy-read-timeout`, `proxy-send-timeout`, `affinity: cookie`) and explain why no annotation names WebSocket.
- Confirm a cross-pod delivery from the receiving pod's own log with `kubectl logs`.

## Why this matters

A topology that works on one Docker daemon still has to survive a scheduler that restarts pods, an edge proxy with its own idle timeouts, and a Kafka cluster that an operator reconciles instead of a container that Compose starts. The deployment runs the same four-instance backplane (two stacks, two instances each, Kafka or Redis behind a mode flag) on minikube with the docker driver and containerd runtime. A live headless run on 2026-10-19 recorded the evidence under `examples/part4-backplane/k8s/evidence/`.

## The same instances, a different substrate

The protocol is unchanged: channel path, resume semantics, backplane modes, the inject endpoint, close codes, and the `INSTANCE_ID`-tagged delivery log line. Both environments run the same two images (`part4-backplane-quarkus`, `part4-backplane-python`) with the same `envFrom` configuration. What moves is everything around the app.

| Concern | Docker Compose | minikube |
| --- | --- | --- |
| Kafka | one `apache/kafka:4.3.1` container | the same release as a Strimzi custom resource |
| Edge | each instance's port published to the host | ingress-nginx in front of instance A only |
| Deploy | `docker compose up --build` | operator install, then `kubectl apply -k` |
| Instance B ports | distinct host ports (`8083`, `8084`/`8085`) | same container ports as A (`8080`, `8081`/`8082`), reachable by Service name |

Each pod has its own network namespace, so instance B needs no port of its own.

## One base, two overlays, one component

`k8s/base/` knows nothing about minikube: a Namespace, a ConfigMap (`backplane-config`, `BACKPLANE_MODE: kafka`), four Deployment and Service pairs (`quarkus-a`, `quarkus-b`, `python-a`, `python-b`), and an Ingress with placeholder hosts, so it deploys to any ingress-nginx cluster.

- `overlays/minikube` retags both images to `:minikube`, sets every `imagePullPolicy` to `Never`, and rewrites the Ingress hosts to `quarkus.part4-backplane.minikube.local` and `python.part4-backplane.minikube.local`.
- `components/redis-mode` is a Kustomize component, not an overlay. It patches one key, `ConfigMap.data.BACKPLANE_MODE`, from `kafka` to `redis`.
- `overlays/minikube-redis` takes `../minikube` as its base and adds that component, so the Redis leg is the minikube overlay plus one patch, not a second copy of four Deployments.

The Strimzi `Kafka` resource lives outside the kustomization in `strimzi/kafka.yaml`. Its CRDs must exist before `kubectl apply -k` can parse it.

{% include excalidraw.html file="26-minikube-deployment" alt="Inside the part4-backplane namespace, a websocat client using a nip.io host name reaches instance A through ingress-nginx, which carries the raised timeouts and cookie affinity and has rules for A only. Instance B has a Service but no Ingress rule and is reached by kubectl exec from A. Both instances publish to a Strimzi Kafka cluster, or to Redis when the redis-mode component is applied, read their mode from the backplane-config ConfigMap, and run images loaded with minikube image load and imagePullPolicy: Never." caption="Figure 26.1: the minikube deployment: one ingress edge, four instances and a Kafka or Redis backplane." %}

## No registry anywhere

The profile uses the docker driver with containerd; podman isn't supported here.

```bash
minikube start -p part4-backplane --driver=docker --container-runtime=containerd --kubernetes-version=v1.37.1
```

The live run reported `containerd://2.3.4`. minikube printed that 1.37.1 is newer than its newest supported version, found it in the GitHub version list, and still came up at exactly `v1.37.1`.

`docker build` produces `part4-backplane-quarkus:minikube` and `part4-backplane-python:minikube` from the repo root, and `minikube image load` copies each into the profile's containerd store. `imagePullPolicy: Never` keeps it there. Without it the kubelet tries a registry pull for an image that exists only in that one cluster and the Deployment sits in `ImagePullBackOff`. The `:minikube` tag in the overlay must match the tag the script builds and loads.

## The ingress edge: longer clocks, no WebSocket annotation

`minikube addons enable ingress -p part4-backplane` installs ingress-nginx. `base/ingress.yaml` carries three annotations:

| Annotation | Value | Why |
| --- | --- | --- |
| `proxy-read-timeout` | `"3600"` | nginx's 60-second default kills an upgraded connection that goes quiet for a minute |
| `proxy-send-timeout` | `"3600"` | same, for the send direction |
| `affinity` | `"cookie"`, cookie name `part4-backplane-affinity` | a reconnecting client lands on the same pod |

Affinity is moot with one replica per instance, but it is the shape a multi-replica deployment needs. No annotation names WebSocket because ingress-nginx detects `Connection: Upgrade` and `Upgrade: websocket` on its own and proxies the upgrade. A socket needs a longer clock from the ingress controller, not a different code path.

## Strimzi: Kafka Ready before any app pod

Strimzi 1.3.0 is installed by Helm from `oci://quay.io/strimzi-helm/strimzi-kafka-operator` into the app namespace. It serves only `kafka.strimzi.io/v1`; `v1beta2`, `v1beta1` and `v1alpha1` are gone, so a Kafka resource written for an older API version is rejected. `strimzi/kafka.yaml` defines a single-node KRaft cluster: one `KafkaNodePool` with both `controller` and `broker` roles, ephemeral `emptyDir` storage, every replication factor `1`. Kafka runs at `4.3.1` with `metadataVersion: 4.3-IV0`, the Strimzi default and the same release Compose pins. It proves wire behavior and doesn't survive a pod restart.

`scripts/install-strimzi.sh` runs in a fixed order:

1. Install the operator and wait for its Deployment to roll out.
2. Wait for the `kafkas.kafka.strimzi.io` and `kafkanodepools.kafka.strimzi.io` CRDs to report `Established`.
3. Apply the Kafka resource and Redis.
4. Block on `kubectl wait kafka/my-cluster --for=condition=Ready --timeout=480s`.

Only then does `verify-minikube.sh` apply the app overlay. The order is required because the Quarkus side's `quarkus-messaging-kafka` channels are wired unconditionally, in every mode. An unresolvable bootstrap hostname at startup is not a retry loop. It fails CDI at boot with `ConfigException: No resolvable bootstrap urls`. The `my-cluster-kafka-bootstrap` Service exists only after Strimzi reconciles, so applying the apps early crash-loops every Quarkus pod, in Kafka and Redis mode alike.

## A resolvable Host header without tunnels

The ingress routes on the `Host` header, which websocat 1.14.1 derives from the URL authority and does not override with `-H`. Instead of `/etc/hosts` edits or `minikube tunnel`, the script uses nip.io, a public wildcard DNS service that resolves `<anything>.<ip>.nip.io` to `<ip>`. With `minikube ip` returning `192.168.49.2`, the WebSocket URLs use `quarkus.192.168.49.2.nip.io` and `python.192.168.49.2.nip.io`, which are real DNS names and also the Ingress routing keys. The only added dependency is outbound DNS to nip.io; nothing in the cluster uses it.

Those names exist only after the cluster is up, so `patch_ingress_hosts_and_wait` patches the Ingress hosts with `kubectl patch ingress --type=json`, then waits for proof that the patch took effect. ingress-nginx reloads asynchronously, and meanwhile its default backend answers an unmatched host with a 404 that looks like a completed response. The first post-patch probe in the live run hit exactly that, and the WebSocket check after it failed. The `affinity: cookie` annotation gives a deterministic signal: the cookie is set only on a response that traversed this Ingress's own rule, so grepping response headers for it replaces a guessed sleep. The live run confirmed routing in `4s` and `0s`.

## Flipping the backplane on a running cluster

`kubectl apply -k overlays/minikube-redis` changes the ConfigMap, but `envFrom` is read once at process start, so running pods keep `BACKPLANE_MODE=kafka`. The script follows the apply with `kubectl rollout restart` on all four Deployments so new pods read the updated value.

The same apply also re-applies `base/ingress.yaml` with its placeholder hosts, overwriting the live nip.io patch. Kustomize converges the cluster to the file, not to the file plus whatever ran after it. The script calls `patch_ingress_hosts_and_wait` a second time after the rollout, and skipping it reproduces the default-backend 404. The Kafka cluster is untouched by the flip; it stays Ready in both modes.

## Instance B stays off the Ingress

`base/ingress.yaml` has rules for `quarkus-a` and `python-a` only. Instance B stands in for some other pod in the fleet, and its `POST /internal/bookings/{id}/handling-events` inject endpoint is internal and demo-only, so it is not reachable from outside the cluster. The script reaches it with `kubectl exec` into instance A's pod, calling `http://quarkus-b:8080/...` or `http://python-b:8082/...` by Service name, and reads delivery confirmation with `kubectl logs`. Only the WebSocket client crosses the cluster boundary, through the Ingress to instance A. `kubectl port-forward` is not used: it bypasses the ingress path under test.

## Two checks that need a live cluster

A Kafka-mode client connects through the Ingress, receives its three seed frames, holds idle for 65 seconds (five past nginx's default), and then still receives a frame injected after the hold. That proves the raised timeouts.

The cross-pod check is confirmed from the receiving pod, not only the client. The redis-mode leg from `quarkus-a-delivered-2026-10-19.log`:

```
2026-10-19 18:19:50,531 INFO  [...LocalDelivery] (vert.x-eventloop-thread-0) delivered eventId=evt_3b5479dba9fe461e8d3ba3e2ec bookingId=bkg_2be1ce99d8334e90a77816dfd3 instance=quarkus-a
```

The event was injected through `quarkus-b`'s in-cluster Service and delivered to a client connected through the Ingress to `quarkus-a`. A client-side assertion can't distinguish that from local delivery; the pod's own log can.

Nothing in the protocol changed on this rung: no close code, no message shape. The same images are rebuilt for a different tag and distribution path. The OpenShift Local appendix runs the same question behind a Route with AMQ Streams instead of Strimzi.

> **Decision**
>
> Each addition answers a question Compose never asked. Images: `minikube image load` plus `imagePullPolicy: Never`; skipping either leaves `ImagePullBackOff`. Edge: raise `proxy-read-timeout` and `proxy-send-timeout` past nginx's 60 seconds. Kafka: wait for `kafka/my-cluster` Ready before the apps, or the always-wired consumer crash-loops. Redeploys: re-patch any field a live process set, because `kubectl apply -k` overwrites it.

## Build, run, observe

```bash
examples/part4-backplane/k8s/verify-minikube.sh --keep
```

`--keep` leaves the profile running for inspection with `kubectl`; without it the script tears the profile down on exit, pass or fail. Expect ten to twenty minutes: cluster bring-up, two image builds, the Strimzi install and three `kubectl apply -k` rollouts. Output markers print as `ok, ` and `FAIL, `, and a passing run ends in `PASS: `. It checks the Kafka-mode idle hold, cross-pod delivery in both modes, and the Ingress re-patch after the flip.

Experiments, each from the behavior described above:

- Remove `imagePullPolicy: Never` from the overlay: Deployments go to `ImagePullBackOff`.
- Apply the app overlay before the Kafka wait finishes: Quarkus pods crash with `No resolvable bootstrap urls`.
- Drop the two timeout annotations: the idle connection closes at nginx's 60-second default instead of surviving the 65-second hold.
- Skip the second `patch_ingress_hosts_and_wait` after the Redis apply: probes hit the default backend's 404.

## For deeper coverage

- Bilgin Ibryam & Roland Huß, *Kubernetes Patterns*, 2nd ed. (O'Reilly, 2023): the Deployment/Service/ConfigMap vocabulary and the readiness-gate pattern behind `install-strimzi.sh`'s ordering.
- Brendan Burns, Joe Beda, Kelsey Hightower & Lachlan Evenson, *Kubernetes: Up and Running*, 3rd ed. (O'Reilly, 2022): the scheduler and in-cluster networking model the ingress edge and pod-to-pod Service DNS depend on.
- *Cloud Native Design Patterns*, "Running Example 05 on minikube" chapter: the same docker-driver/containerd, Strimzi-managed Kafka, kustomize-overlay shape applied, run against a different example.
- *Cloud Native Design Patterns*, "WebSockets at Scale" chapter: the pub/sub-backplane-plus-resume posture `part4-backplane` implements, and why long-lived sockets fight stateless scaling on Kubernetes in the first place.
- [ingress-nginx WebSocket documentation](https://kubernetes.github.io/ingress-nginx/user-guide/miscellaneous/#websockets): confirms the automatic `Connection: Upgrade` detection the Ingress relies on, with no WebSocket-specific annotation required.
