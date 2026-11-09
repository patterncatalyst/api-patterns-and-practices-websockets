---
title: "Appendix A: OpenShift Local (CRC)"
order: 99
part: "Runtime Progression"
appendix: true
appendix_label: "A"
description: "Running the WebSocket services on OpenShift Local (CRC): operator install, in-cluster builds, restricted-v2, and edge-TLS Routes."
duration: "16 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why edge-TLS Route termination proxies a WebSocket `Upgrade` cleanly while the same termination fails an ALPN-negotiated gRPC handshake on the identical router.
- Install an operator from OperatorHub with `installPlanApproval: Manual` and a pinned `startingCSV`, and explain what approving only that one `InstallPlan` protects against.
- Build application images inside the cluster (binary S2I for Quarkus, a Docker-strategy `BuildConfig` for Python) instead of pushing a host-built image.
- Verify a `wss://` connection against the cluster's own ingress CA, and reach a second instance only via `oc exec`.
- Poll a Route with `wait_route_serving` instead of trusting `oc rollout status` alone, and explain the `503` window it closes.

## Why this matters

The minikube deployment showed the four-instance, Kafka-or-Redis topology survives a real scheduler. The question here is narrower and platform-specific: does the same topology survive OpenShift's mechanisms in place of minikube's? Routes replace Ingress. An operator installed through OperatorHub with a pinned CSV replaces Helm-installed upstream Strimzi. An image assembled inside the cluster under a UID the cluster picks replaces a host-built one.

`examples/part4-backplane/openshift/` is the third rung of the runtime ladder (compose, minikube, CRC). It was **verified live and headless on CRC 2.64.0 / OpenShift 4.22.14, 2026-10-19**, with evidence under `examples/part4-backplane/openshift/evidence/2026-10-19/`. `verify-crc.sh` printed `PASS` after a schema-valid seed frame, a 65-second idle hold, and the cross-pod fan-out, on both stacks, over both the AMQ Streams Kafka backplane and the Helm-toggled Redis backplane, entirely through edge-TLS Routes verified against the cluster's own ingress CA.

## Same chart, OpenShift-native plumbing

The chart keeps the minikube env contract: `BACKPLANE_MODE`, `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_TOPIC` and `REDIS_URL` are the same ConfigMap keys (`helm/part4-backplane/templates/config.yaml`), so application code never learns which cluster it runs on. Only the value of `KAFKA_BOOTSTRAP_SERVERS` differs: AMQ Streams names the Service `<cluster-name>-kafka-bootstrap` as Strimzi does, but the cluster here is `part4-backplane`, not `my-cluster`.

Everything downstream of the ConfigMap is OpenShift-specific. Four Deployment and Service pairs (`quarkus-a`, `quarkus-b`, `python-a`, `python-b`) follow the same split as every environment: instance A of each stack has a Route, instance B is reached only from inside the cluster. Redis ships in the same Helm release (`templates/redis.yaml`), as there is no operator for it on either cluster. Kafka comes from `infra/kafka.yaml` and the AMQ Streams Subscription, installed ahead of the chart by `install-infra.sh`.

## AMQ Streams, pinned, Manual approval

OpenShift ships no Kafka operator in the box. `infra/amq-streams-subscription.yaml` requests the `amq-streams-3.2.x` channel with `installPlanApproval: Manual` and `startingCSV: amqstreams.v3.2.1-14`. `install_operator` in `lib.sh` applies the Subscription, waits for OLM to propose an InstallPlan, and approves only the one naming the pinned CSV. Any later InstallPlan OLM proposes for a newer CSV stays unapproved until someone bumps the file. The reason is the same for every operator installed this way: a cluster that silently upgrades its Kafka operator between two runs is a cluster whose behavior nobody asked for.

`amqstreams.v3.2.1-14` was the newest AMQ Streams CSV on the live-run date, read from `oc get packagemanifest amq-streams -n openshift-marketplace` rather than assumed. `infra/kafka.yaml` defines a `KafkaNodePool` holding both `controller` and `broker` roles on one replica (KRaft; wire behavior, not durability) and a `Kafka` resource pinning `version: 4.2.0` and `metadataVersion: 4.2-IV0`. Redis stays at `8.10.2-alpine`, as on compose and minikube.

## Images built inside the cluster

Neither app image arrives from outside.

- **Quarkus** uses the `openshift` Maven profile (`-Popenshift`). The fast-jar is packaged on the host, then uploaded to a binary S2I `BuildConfig` that `quarkus-openshift` generates. The S2I builder image's `/usr/libexec/s2i/assemble` lays the jar into its final layout inside the cluster.
- **Python** has no S2I builder. `build-images.sh` assembles a throwaway build context mirroring the repo-root-relative paths that `python/Containerfile`'s `COPY` lines expect (pyproject, lockfile, `app/`, the AsyncAPI contract, the schema-extraction script, the part 3 fixture) and hands it to `oc start-build --from-dir` against a Docker-strategy `BuildConfig`.

Both builds push an `ImageStream` tag (`part4-backplane-quarkus:v1`, `part4-backplane-python:v1`) that the chart deploys by name. There are no registry credentials, no `docker push`, and no host container engine. `evidence/2026-10-19/01-cluster-builds.txt` records the digests.

## restricted-v2, no fixed UID

Every container, both app images and Redis, runs under the `restricted-v2` SCC with no `runAsUser`, `runAsGroup` or `fsGroup` anywhere in the chart. OpenShift assigns an arbitrary UID from the namespace range on admission; `evidence/2026-10-19/02-pods.txt` shows every pod on UID `1000650000` from the `1000650000/10000` range. A container that assumes it owns UID 1000, or writes where only that UID can, fails under this model. The fix is a group-0-writable path in the image, never a pinned UID added to make the pod start. No image here needed it: `ubi10/openjdk-25` and the Python base tolerate an arbitrary UID with GID 0.

## Edge-TLS Routes and the WebSocket upgrade

HTTP/2 and gRPC depend on ALPN negotiation inside the TLS handshake, so the router's termination type decides whether those protocols work at all. A WebSocket falls on the safe side of that line: terminate TLS at the router with an edge Route and the `Upgrade` passes as ordinary HTTP/1.1, because a WebSocket never needs ALPN.

`templates/routes.yaml` renders a `Route` only for `quarkus-a` and `python-a` (`values.yaml` `route: true`), each with `tls.termination: edge` and `insecureEdgeTerminationPolicy: Redirect`. TLS stops at the router and the Service gets plain HTTP, which is what an `Upgrade: websocket` request already is. The router detects the `Connection: Upgrade` header and proxies it with no WebSocket annotation, as ingress-nginx does. The one addition beyond the minikube Ingress is `haproxy.router.openshift.io/timeout: "3600s"`, HAProxy's analogue of nginx's `proxy-read-timeout` and `proxy-send-timeout`. Without it, a quiet long-lived socket risks the router's default idle timeout tearing it down regardless of the application.

The negative case is gRPC. Running the same experiment on the same CRC release, edge and reencrypt termination could not complete a native gRPC client's handshake. The router's generated HAProxy configuration showed `fe_sni`, the shared frontend that edge-terminated Routes dispatch through by SNI, binding with the literal option `no-alpn`, so a strict-ALPN client fails with `missing selected ALPN property` before any request byte is sent, and `curl --http2` reports `ALPN: server did not agree on a protocol`. Only `passthrough` worked, which forces the workload to terminate its own TLS and negotiate ALPN directly with the client.

Neither application stack has TLS code. Each Route forwards to a named Service port over plain HTTP: `http` (`8080`) on Quarkus, `ws` (`8081`) on Python. The platform owns termination, the chart owns the `Route`, and the same application image runs on minikube behind ingress-nginx.

{% include excalidraw.html file="99-openshift-deployment" alt="Inside the part4-backplane project, running under restricted-v2 with no fixed UID, a websocat client verifies the cluster CA and connects over wss through an edge-TLS Route with a 3600s timeout, which exists for the A instances only. Instance B is reached by oc exec from A. Both instances publish to an AMQ Streams Kafka 4.2.0 cluster or to Redis, with the mode set by the Helm-driven backplane-config ConfigMap. The AMQ Streams operator, installed from OperatorHub with Manual approval, and the in-cluster builds (binary S2I for Quarkus, Docker strategy for Python) sit beside the project." caption="Figure A.1: the same chart on OpenShift Local: an edge-TLS Route, AMQ Streams Kafka and in-cluster builds." %}

## CA-verified wss://, instance B by exec

`verify-crc.sh` reaches instance A only through its Route over `wss://`, verified against the cluster's ingress CA, never `-k`. The router certificate is signed by an ingress CA absent from public trust stores, so the script extracts it from `configmap/default-ingress-cert -n openshift-config-managed` and points `websocat`'s `SSL_CERT_FILE` at it. Instance B has no Route. Every call into it goes through `oc exec` against instance A's pod, curling B's cluster-DNS Service name over plain HTTP (`http://quarkus-b:8080`, `http://python-b:8082`). No port-forward, NodePort or tunnel appears anywhere in the script.

## Requirements only a live run exposes

Four platform requirements are invisible to `helm lint`, `helm template` or `bash -n`, which is why the status flips to verified only after `verify-crc.sh` prints `PASS` on a live cluster.

| Requirement | Cause | Fix |
|---|---|---|
| Quarkus S2I needs the full `ubi10/openjdk-25`, not `-runtime` | S2I runs the builder's own `/usr/libexec/s2i/assemble`; only the full image ships it and `run-java.sh` | Keep `quarkus.openshift.base-jvm-image` on the full image; reserve `-runtime` for a multistage Containerfile `FROM` |
| `SSL_CERT_FILE` must hold the system trust store plus the ingress CA | The variable is inherited by child processes, including the schema-validation step that fetches `jsonschema` metadata from pypi.org, whose chain an ingress-CA-only bundle lacks | Export a combined bundle: the system store (`/etc/ssl/certs/ca-certificates.crt` or equivalent) with the ingress CA appended |
| The router answers `503` briefly after a rollout | `oc rollout status` returns once pods are Ready; HAProxy swaps the Route's endpoints slightly later, seen on the first `wss://` connect after the Redis toggle | `wait_route_serving` polls the Route with a CA-verified `curl` until it returns anything but `503` or a connection failure (a WebSocket-only path answers `404` or `426` once a backend is reachable); run it after the initial deploy and after the Redis rollout |
| AMQ Streams supports Kafka 4.1.0 and 4.2.0 only | The Red Hat-built operator lags upstream Strimzi 1.3.0, which runs 4.3.1 on minikube | Pin 4.2.0 in `infra/kafka.yaml` |

The Kafka version was read from the cluster-operator pod's own `kafka-images` annotation. Replay and fan-out behave identically on 4.2 and 4.3, so the step-back is a version floor, not a functional gap. When `amqstreams.v3.2.1-14` is superseded, the Subscription's `channel` and `startingCSV`, `install-infra.sh`'s `CSV` variable, and `kafka.yaml`'s `version` and `metadataVersion` move together in one commit. Letting any one drift ahead of the others is its own failure mode.

The 65-second idle hold passes, but it proves less here than on minikube. HAProxy's default tunnel timeout already exceeds nginx's 60-second default by a wide margin, so a quiet socket surviving 65 seconds shows only that the connection is not torn down and that the `3600s` annotation is present on the Route. It does not show that the annotation moved a timeout a real client would otherwise hit.

> **Decision**
>
> Use this shape whenever the target is OpenShift rather than generic Kubernetes: AMQ Streams from OperatorHub with `Manual` approval and a pinned `startingCSV`, in-cluster S2I and Docker-strategy builds, `restricted-v2` with no fixed UID, and edge-TLS Routes with the HAProxy timeout raised. Trust edge termination for a WebSocket Route; the `Upgrade` happens after the handshake the router already finished. Never treat `oc rollout status` as proof that traffic reaches a workload; poll the Route until it answers something other than `503`. Pin the Subscription, the Kafka resource and the install script together and move them together.

## Build, run, observe

Run one local cluster at a time: stop the minikube profile first, size CRC, and start it:

```bash
minikube stop -p part4-backplane 2>/dev/null || true

crc config set cpus 6
crc config set memory 20480
crc start
eval "$(crc oc-env)"
```

Then run from `examples/part4-backplane/`:

```bash
./openshift/install-infra.sh      # project, AMQ Streams (pinned), Kafka CR
./openshift/build-images.sh       # in-cluster builds: binary S2I and Docker-strategy BuildConfig
./openshift/deploy.sh             # helm upgrade --install, waits for rollout
./openshift/verify-crc.sh         # live proof; prints PASS
./openshift/capture-evidence.sh   # evidence/<date>/, secret-scrubbed
```

`verify-crc.sh` only reads a deployment that `deploy.sh` already brought up. It connects over `wss://` through the Route to receive the three seed frames, holds the socket idle for 65 seconds, injects a late event by `oc exec` into the same pod, and checks that the frame arrives on the still-open socket, not a reconnect. It then repeats the cross-pod fan-out check on both stacks, over the Kafka backplane and again after the Helm toggle to Redis. Server-side delivery is recorded in `evidence/2026-10-19/05-delivered-logs.txt` as `delivered eventId=... instance=quarkus-a` and `instance=python-a`.

Experiments from the recorded run:

- Point the Quarkus S2I build at the `-runtime` base image: the build has no `assemble` script.
- Set `SSL_CERT_FILE` to the ingress CA alone: the schema-validation step cannot reach pypi.org.
- Connect right after the Redis rollout without `wait_route_serving`: the first `wss://` attempt meets a router `503`.

Tear down with `teardown.sh`. It removes the Helm release (Deployments, Services, Redis, both Routes, the ConfigMap), the Kafka resources and `KafkaNodePool` ahead of the namespace, the namespace, then the Subscription, CSV, InstallPlans and the CRDs they own, in that order. A `KafkaTopic` or `KafkaUser` finalizer left after its operator is gone hangs the namespace in `Terminating`. It inventories what remains and calls `crc stop` last, unless `--keep-running` is passed.

## For deeper coverage

- Bilgin Ibryam & Roland Huß, *Kubernetes Patterns*, 2nd ed. (O'Reilly, 2023): the operator pattern and the readiness-gate discipline behind pinning AMQ Streams to a `startingCSV` and waiting on it before any app pod starts.
- Brendan Burns, Joe Beda, Kelsey Hightower & Lachlan Evenson, *Kubernetes: Up and Running*, 3rd ed. (O'Reilly, 2022): the admission and scheduling model behind `restricted-v2`'s arbitrary-UID assignment.
- *Cloud Native Design Patterns*, "Running Example 05 on OpenShift Local" chapter: the same AMQ Streams/OLM, `restricted-v2`, edge-TLS-Route shape, run against a different example.
- *Cloud Native Design Patterns*, "L7 Routing & Traffic Management" chapter: the edge, gateway, mesh and in-app layering that explains why an edge-terminated Route proxies a WebSocket `Upgrade` but cannot complete a strict-ALPN gRPC handshake.
- [Red Hat OpenShift Local overview](https://developers.redhat.com/products/openshift-local/overview): what CRC is and the single-node, local-only constraints behind the sizing and teardown choices.
