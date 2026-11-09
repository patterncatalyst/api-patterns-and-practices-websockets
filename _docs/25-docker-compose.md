---
title: "Docker Compose"
order: 25
part: "Runtime Progression"
description: "Running the full stack locally with Docker Compose."
duration: "9 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain why every multi-stack example's Containerfile builds with `context: ../..` instead of a context scoped to `quarkus/` or `python/`, and what breaks if it isn't.
- Gate a broker-dependent service's startup on `healthcheck` plus `depends_on: condition: service_healthy`, instead of a bare `depends_on` that only waits for the container to start.
- Use `depends_on.required: false` to let one set of app services serve a profile-less, `--profile kafka`, and `--profile redis` run from a single `compose.yaml`.
- Distinguish what a Compose `profiles` flag controls (which containers start) from what `BACKPLANE_MODE` controls (which `Backplane` implementation a running instance wires up).
- Diagnose a `ConfigException: No resolvable bootstrap urls` crash at startup as distinct from the soft connection-retry warning an unreachable-but-resolvable broker host produces.

## Why this matters

Each example runs with a single `docker compose up` against its own disposable `compose.yaml`. There is no unified compose file for the whole site. `examples/part4-backplane/compose.yaml` has enough moving parts (four app instances, two swappable brokers, three scenarios) that the topology itself has to hold up as a runtime: build context, healthcheck gating, and the profile and environment split that picks a backplane.

## Build context at the repo root

Every service builds with `context: ../..` and a `dockerfile:` path back down to the stack directory (`examples/part4-backplane/quarkus/Containerfile` or the `python/` sibling). `part3-handling-events` and `part4-connection` do the same. Each Containerfile has to `COPY` `contracts/handling-event.proto` and `contracts/asyncapi.yaml` from the repo root, plus `examples/part3-handling-events/fixtures/handling-events.json`, the seed fixture both stacks replay in RECEIVE, LOAD, CUSTOMS order. A build context is a hard filesystem boundary: a context scoped to `quarkus/` or `python/` can't see any of them.

A root context gives both stacks the same contract files and fixture at the same relative path, which keeps "Quarkus and Python implement identical wire behavior against one contract" mechanically true. The cost is a slower build, since Docker walks and checksums the whole repo tree, so the root `.dockerignore` matters.

## Healthcheck-gated startup

Every service defines a `healthcheck`, and every app service's `depends_on` names each broker with `condition: service_healthy`. A bare `depends_on: [kafka]` waits only for the container to start. A `kafka` container exists the instant its process forks, but `apache/kafka:4.3.1` in single-node KRaft mode needs several seconds to run its startup script, elect itself leader of a one-voter quorum and open `9092`. A compose file that races an app's first connection against that boot fails on a cold machine and passes on a warm one, which looks like an application bug.

| Service | Check | Timing |
|---|---|---|
| `kafka` | `kafka-broker-api-versions.sh --bootstrap-server localhost:9092` | every 5 s, 30 retries, 20 s `start_period` |
| `redis` | `redis-cli ping` | every 3 s, 20 retries, 5 s `start_period` |
| `quarkus-a`, `quarkus-b` | `curl -s -o /dev/null http://127.0.0.1:8080/` | every 5 s, 30 retries, 20 s `start_period` |
| `python-a`, `python-b` | `curl -f http://127.0.0.1:8082/healthz` | every 5 s, 30 retries, 10 s `start_period` |

The Quarkus check omits `-f` because a plain `GET` against a WebSocket-only endpoint returns 404 or 426, and the question is only whether the HTTP server answers. The Python check hits a dedicated FastAPI health port and fails on any non-2xx. A service with `condition: service_healthy` doesn't start until the dependency reports healthy, which turns "probably up by the time the app connects" into "up before the app's first instruction." The app healthchecks also stop `docker compose up -d --build` from reporting done while a JVM is still in cold start. `examples/_lib/lib.sh` adds a second layer that polls the actual WebSocket upgrade path.

## Optional dependencies with required: false

All four app services declare the same two optional dependencies:

```yaml
    depends_on:
      kafka:
        condition: service_healthy
        required: false
      redis:
        condition: service_healthy
        required: false
```

`required: false` lets one set of app services serve all three scenarios (default stateless, `--profile kafka`, `--profile redis`) without three compose files. Without it, naming `kafka:` under `depends_on` is a hard reference: in the profile-less run `kafka` is tagged `profiles: ["kafka"]` and isn't defined, so compose refuses to start, citing an undefined service. With it, compose waits for the dependency's health if it is part of this invocation and skips the wait if it isn't. That makes `docker compose up --build`, `docker compose --profile kafka up --build` and `docker compose --profile redis up --build` all valid against the same file.

## Profiles select infrastructure; BACKPLANE_MODE selects behavior

| Knob | Controls | Aware of the other? |
|---|---|---|
| `--profile kafka`, `--profile redis`, `--profile observability` | Which containers come up (profile-tagged services are skipped unless active) | No, compose doesn't know what runs inside a container |
| `BACKPLANE_MODE` | Which `Backplane` implementation (`StatelessBackplane`, `KafkaBackplane`, `RedisBackplane`) an instance wires up at runtime | No, compose only passes it through |

The two are independent. `docker compose --profile kafka up` with `BACKPLANE_MODE` left at `stateless` brings up a healthy Kafka broker that every app instance ignores, and the apps lose gap-era events exactly as in the no-broker case. "I started Kafka" reads as "the app uses Kafka," so this is a silent misconfiguration. Set both together: stateless with no profile, `kafka` with `--profile kafka`, `redis` with `--profile redis`.

The broker addresses default to hosts that are unreachable but resolvable whenever the matching broker isn't running: `KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}` and `REDIS_URL=${REDIS_URL:-redis://localhost:6379/0}`. Only a run that starts a broker overrides them with the real `kafka` or `redis` service hostname.

## An unresolvable bootstrap server crashes Quarkus at startup

`quarkus-messaging-kafka` wires its channel at build time regardless of `BACKPLANE_MODE`, so the Kafka consumer is constructed from `KAFKA_BOOTSTRAP_SERVERS` on every startup. The two failure classes differ:

| Bootstrap value | Failure | Effect |
|---|---|---|
| Resolves, nothing listening (`localhost:9092`) | Connection-refused warning, retried in the background | App serves traffic normally |
| Doesn't resolve (`kafka` when the `kafka` profile isn't active, so no such DNS entry exists) | `ConfigException: No resolvable bootstrap urls`, thrown during consumer construction | CDI startup aborts, app never starts |

`examples/part4-backplane/k8s/README.md` records the same exception on Kubernetes, so it comes from how the Kafka client resolves its bootstrap list, not from compose. An environment variable naming a service hostname that only sometimes exists on the network needs a resolvable fallback, not an empty string or the production hostname left in place on the assumption that it will just retry.

## Four instances, one contract

All four app services start in every profile, including the default with no broker: `quarkus-a` (8080), `quarkus-b` (8083), `python-a` (8081, health 8082) and `python-b` (8084, health 8085). Cross-instance fan-out needs a B for every A, so the topology stays uniform and one file serves the stateless-gap, Kafka-replay and both fan-out scenarios. The A and B instances share an image and differ only in `INSTANCE_ID` and host ports.

`INSTANCE_ID` is not cosmetic. Every instance logs it on connection accept and on each delivery (`delivered eventId=<id> bookingId=<id> instance=<INSTANCE_ID>`). That lets a check assert two things: instance A's client received an event injected through instance B, and instance A's own process did the delivering over the backplane.

{% include excalidraw.html file="25-compose-topology" alt="The four app services with their host ports sit behind a healthcheck-gated depends_on that treats a missing profile as skipped. Kafka and Redis start only under their own profiles, and the lgtm stack is opt-in." caption="Figure 25.1: the Compose topology: four app instances, two profile-gated brokers and an opt-in observability stack." %}

## Pinned single-node brokers

The profile-gated brokers are `apache/kafka:4.3.1` in single-node KRaft mode (`KAFKA_PROCESS_ROLES=broker,controller` on one node) and `redis:8.10.2-alpine`. The same versions carry onto the minikube path, where Strimzi's default resolves to Kafka 4.3.1 (`4.3-IV0`). AMQ Streams on OpenShift Local steps back to 4.2.0 because the installed operator build supports nothing newer.

KRaft needs no ZooKeeper container, which keeps the broker to one container. `CLUSTER_ID` is a fixed arbitrary base64 UUID that the image's `configure` script requires at startup. `KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092` tells Kafka what address to return during the metadata handshake, and it must be the service name `kafka`: `localhost` inside the broker's container isn't the `localhost` a client container resolves.

## Observability stays opt-in

`lgtm` (`grafana/otel-lgtm:0.36.0`) carries `profiles: ["observability"]` and is left out of every scenario. It is the heaviest container in the file, with a 30 s `start_period`, and CI and a first local boot should stay fast. `docker compose --profile observability up --build` layers it onto any of the three scenarios. `part3-handling-events` and `part4-connection` use the same opt-in for the same image.

> **Decision**
>
> Compose is the first rung because its mechanisms carry forward: a healthcheck gates startup as a Kubernetes readiness probe will, a profile selects optional infrastructure as an opt-in overlay will, and the `BACKPLANE_MODE` and broker-hostname environment contract is reused unchanged on the cluster paths. Set the mode and the profile together, and give any broker hostname that only sometimes exists a resolvable fallback.

## Build, run, observe

```bash
bash examples/part4-backplane/verify.sh
```

The script runs three sequential `docker compose up` and `down` cycles against the one file, so no stage's broker state leaks into the next: no profile with `BACKPLANE_MODE=stateless`, `--profile kafka` with `kafka`, and `--profile redis` with `redis`. It sets the mode and profile together each time. It prints `PASS: ` when all three scenarios hold on both stacks. Ports: Quarkus on `8080` and `8083`, Python on `8081` and `8084` with health on `8082` and `8085`, Kafka on `9092`, Redis on `6379`.

- Stateless stage: an event injected while a client is disconnected never appears after it reconnects with `?afterEventId=<last seen>`. The inject call returns `202 Accepted` regardless.
- Kafka stage: the same sequence delivers the injected event within 40 seconds, as one or two raw frames (two is the documented benign replay-versus-live race, so clients dedupe by `eventId`).
- Fan-out stages (Kafka and Redis): an event injected through instance B reaches a client on instance A, and A's own log shows `instance=<A>` on the delivery.
- To see the startup crash, point `KAFKA_BOOTSTRAP_SERVERS` at `kafka:9092` in a run without the `kafka` profile: Quarkus never starts and the stack trace names the value.

## For deeper coverage

- Liz Rice, *Container Security*, 2nd ed. (O'Reilly, 2025): the container-boundary assumptions (build context scope, image provenance, what a `COPY` can reach) behind building from the repo root.
- *Cloud Native Design Patterns*, "Graceful Shutdown" chapter: the readiness-signal asymmetry on the shutdown side of a pod's life, the one `condition: service_healthy` closes on the startup side.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: why an unresolvable `KAFKA_BOOTSTRAP_SERVERS` crashes Quarkus at startup while a merely unreachable host degrades to a retry.
- [Docker Compose documentation](https://docs.docker.com/compose/): `depends_on` conditions, `profiles`, and the `healthcheck` block.
- [Compose Specification](https://compose-spec.io/): the schema `compose.yaml` conforms to, including the `required: false` dependency form.
