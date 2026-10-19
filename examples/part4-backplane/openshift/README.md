# part4-backplane — OpenShift Local (CRC) appendix

Ports the minikube topology (`../k8s/`) to OpenShift-native mechanisms: a
Helm chart for the four app instances + Redis (restricted-v2, edge-TLS
Routes, one `backplane: kafka|redis` value toggling `BACKPLANE_MODE` on all
four Deployments), Kafka from the AMQ Streams operator (OperatorHub, pinned),
and binary/Docker-strategy in-cluster image builds — no host container
engine, no exposed registry. See `../PROTOCOL.md` for the shared wire/
behavior contract both stacks implement identically, and the project's
`feedback_openshift_crc_appendix` / `feedback_headless_cluster_verification`
conventions for why this appendix exists and how it gets verified.

## Layout

```
openshift/
  infra/
    amq-streams-subscription.yaml   # AMQ Streams operator (DATED DRAFT pin — see TODO below)
    kafka.yaml                      # KafkaNodePool + Kafka CR (single-node KRaft)
  helm/part4-backplane/             # the four app instances + Redis + Routes
  lib.sh                            # shared helpers (require_crc, install_operator, ...)
  install-infra.sh                  # project + AMQ Streams operator + Kafka CR
  build-images.sh                   # Quarkus binary S2I + Python Docker-strategy build
  deploy.sh                         # helm upgrade --install + rollout wait
  verify-crc.sh                     # live proof: seed + idle-hold + Ch18, both stacks/backplanes
  capture-evidence.sh               # writes evidence/<date>/, runs verify-crc.sh, secret-scrubs
  teardown.sh                       # returns CRC to empty, then crc stop
  evidence/                         # capture-evidence.sh output, one dir per date
```

## Live run order

```bash
# Run one local cluster at a time.
minikube stop -p part4-backplane 2>/dev/null || true

crc config set cpus 6
crc config set memory 20480
crc start
eval "$(crc oc-env)"

./openshift/install-infra.sh     # project + AMQ Streams (pinned) + Kafka CR
./openshift/build-images.sh      # part4-backplane-quarkus + part4-backplane-python, in-cluster
./openshift/deploy.sh            # helm upgrade --install, waits for rollout
./openshift/verify-crc.sh        # live proof: seed + idle-hold + Ch18, kafka then redis
./openshift/capture-evidence.sh  # evidence/<date>/, re-runs verify-crc.sh, secret-scrubs

./openshift/teardown.sh          # project + Kafka + AMQ Streams removed, then crc stop
```

`verify-crc.sh` and `capture-evidence.sh` never start, stop, build, or
deploy anything — they only read a deployment `deploy.sh` already brought
up. The live cluster bring-up/teardown is always the operator's own call,
run by hand, never scripted into a CI step (see
`feedback_headless_cluster_verification`).

**This appendix's footer/status flips to `verified` only after
`verify-crc.sh` prints its `PASS` line on an actual live CRC run** — not on
the strength of `helm lint`/`helm template`/`bash -n` alone. Those checks
are necessary (they catch a broken chart or script before anyone wastes an
hour on a live run) but they are not sufficient: they never deploy to or
read from a real cluster.

## DRQ-031 headline: WebSocket upgrade over edge-TLS

The same claim the minikube/nginx path makes, carried to OpenShift's router:
an HTTP/1.1 `Upgrade: websocket` request survives edge termination cleanly.
The Route is `termination: edge`, `insecureEdgeTerminationPolicy: Redirect`
— TLS stops at the router, the backend Service gets plain HTTP, and the
router proxies the upgrade through without any WebSocket-specific
annotation (same as ingress-nginx: it auto-detects `Connection: Upgrade`).
The one thing that DOES need raising is the router's own idle-connection
timeout, via `haproxy.router.openshift.io/timeout: "3600s"` on each Route —
the HAProxy analogue of nginx's `proxy-read-timeout`/`proxy-send-timeout`
annotations on the minikube path.

## What broke / watch for

- **websocat + the cluster's own CA, not a public one.** OpenShift Local's
  router certificate is signed by the cluster's own ingress CA
  (`configmap/default-ingress-cert -n openshift-config-managed`), which is
  not in any public trust store. `verify-crc.sh` extracts that CA to a temp
  file and exports it as `SSL_CERT_FILE` before calling websocat — NEVER
  `-k`/`--insecure`. If websocat ever starts failing TLS verification after
  an OpenShift Local upgrade, check that this ConfigMap's key/shape hasn't
  changed, not that it's safe to add `-k`.
- **HAProxy's idle-timeout nuance.** HAProxy's own default tunnel timeout is
  already much longer than nginx's 60s default, so the 65s-idle-hold-then-
  late-frame check in `verify-crc.sh` is a WEAKER proof here than the same
  check on minikube/nginx — it demonstrates the socket survives and the
  `haproxy.router.openshift.io/timeout: "3600s"` annotation is present, not
  that the annotation moved the timeout close to an edge a real client would
  hit. Don't over-claim this one in the prose.
- **AMQ Streams / Kafka version pin is a DATED DRAFT, not yet live-surveyed.**
  `infra/amq-streams-subscription.yaml` pins `amq-streams-3.2.x` /
  `amqstreams.v3.2.1-14` (sourced from a 2026-10-09 survey, not this
  appendix's own authoring date) — that channel is only confirmed to ship
  Kafka 4.1.x/4.2.x, while `infra/kafka.yaml` pins Kafka 4.3.1 (to match
  `../compose.yaml` / `../k8s/strimzi/kafka.yaml`). Both files carry a
  `TODO(pin survey D0)` with the exact survey command
  (`oc get packagemanifest amq-streams -n openshift-marketplace -o jsonpath=...`).
  **Run that survey before the first live `install-infra.sh`**, and update
  the Subscription's `channel`/`startingCSV`, `install-infra.sh`'s `CSV`
  variable, and `kafka.yaml`'s `spec.kafka.version`/`metadataVersion`
  together — never let the three drift apart.
- **The Python build is heavy for an in-cluster Docker-strategy build.**
  `../python/Containerfile` compiles `aiokafka`'s C extension from source
  (gcc/make/zlib-devel, discarded after the build stage) and runs
  `datamodel-code-generator` to produce `app/models_generated.py` — expect
  it to be noticeably slower than the Quarkus S2I build. `build-images.sh`
  raises the BuildConfig's build-pod resources (1-2 CPU / 2-4 GiB) for this
  reason; if it still times out or OOMs on a smaller CRC VM, raise those
  further rather than trimming the Containerfile's build-time steps.
- **restricted-v2, no `runAsUser` anywhere.** Every container in
  `helm/part4-backplane/` (the two app images, Redis) tolerates an
  arbitrary namespace-range UID with GID 0 — never add a fixed `runAsUser`/
  `runAsGroup`/`fsGroup` to "fix" a permissions error; that's the known
  "pod rejected: UID not in range" failure mode the restricted-v2 SCC
  exists to prevent. If a pod won't start under its assigned UID, the image
  needs a writable-by-group-0 path, not a pinned UID.
