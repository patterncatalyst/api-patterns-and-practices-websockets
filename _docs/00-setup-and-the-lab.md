---
title: "Setup and the Lab"
order: 0
part: "Prerequisites"
description: "Toolchain pins, the Docker Compose lab with opt-in LGTM tracing, and the shipping and cargo domain the sockets share with the REST booking service."
duration: "10 min read"
---

## Learning objectives

By the end of this chapter you can:

- Install the pinned toolchain the examples build against: JDK 25 and Quarkus with `quarkus-websockets-next`, Python 3.15 managed by `uv`, the AsyncAPI CLI, and the Docker Compose plugin.
- Bring up an example's Docker Compose lab with `docker compose up --build`, and turn on tracing with `docker compose --profile observability up --build`.
- Tear the lab down cleanly with `docker compose down --volumes --remove-orphans`, and say why `--volumes` matters.
- Name the three runtime tiers the examples climb (Docker Compose, minikube, OpenShift Local) and what changes between them.

## Why this matters

Every hands-on chapter gives you a live socket in two languages, pushing the same shipping and cargo handling events under one AsyncAPI contract. A pinned toolchain and a lab with a predictable shape mean the thing you debug is the socket, not the setup. Pins are exact so builds reproduce; nothing else here touches message shapes or connection lifecycle.

## Toolchain pins

The pins track the current stable release of each tool, not an older LTS floor, so a reader installing today lands close to what every example targets.

**Quarkus** builds on JDK 25 (the current LTS line) and Quarkus 3.40, the current stable minor. Quarkus 4.0 is in beta and is not adopted until it ships stable. **WebSockets Next** (`quarkus-websockets-next`) is the current-generation Quarkus WebSocket API, built on Vert.x and Mutiny, with per-connection state and no separately versioned artifact. The legacy `quarkus-websockets` extension still works; every Quarkus example here uses WebSockets Next only.

**Python** pins to 3.15, managed by `uv`: it installs the interpreter, resolves and locks dependencies from `pyproject.toml`, and runs the project. FastAPI handles HTTP routing and app lifecycle, and the native `websockets` library handles the socket. FastAPI's own `WebSocket` type is a thin wrapper over Starlette's ASGI primitive, fine for a single-process toy, but the native library exposes the connection state machine, ping/pong control frames and close-code handling that liveness and reconnect work need.

The **AsyncAPI CLI** validates `contracts/asyncapi.yaml` against the AsyncAPI 3.0 meta-schema, the way `buf lint` validates a `.proto` file. **k6** drives the sustained-connection load tests and **Newman** runs REST-side assertions at the seam back to the booking service.

{% include codetabs.html langs="Quarkus|Python" %}

```bash
# Quarkus: SDKMAN manages the JDK and the Quarkus CLI
sdk install java 25.0.4-tem
sdk install quarkus 3.40.0
quarkus create app shipping:handling-events-ws \
  --extension=quarkus-websockets-next,quarkus-opentelemetry
```
```bash
# Python: uv manages both the interpreter and the project
uv python install 3.15.0
uv init handling-events-ws && cd handling-events-ws
uv python pin 3.15.0
uv add fastapi websockets "uvicorn[standard]" opentelemetry-distro
```

A container engine with the **Compose plugin** (Docker Engine providing `docker compose`, not the legacy standalone `docker-compose` binary) is the one tool every chapter assumes. The plugin is still called "Compose v2" because it replaced the Python-based v1 tool, but its version runs on its own track (5.6 in the matrix below) and has nothing to do with the Compose *file* format's old v2/v3 schema numbers. The labs need a plugin new enough for `profiles` and `depends_on` health conditions. The observability stack is `grafana/otel-lgtm`, an all-in-one image bundling Loki (logs), Grafana (dashboards), Tempo (traces) and Mimir (metrics) behind one OpenTelemetry Collector, the same image the REST and gRPC siblings use.

## The lab (Compose and LGTM)

Each example directory that runs services has its own `compose.yaml` with two services: `quarkus` on host port 8080, and `python` with its WebSocket server on host port 8081 and its HTTP side (`/healthz`) on 8082. The performance example shifts the same pair to 8090, 8091 and 8092. Both services are built against the same `contracts/asyncapi.yaml`, and each example's `README.md` lists its ports and endpoints. A third service, `lgtm`, sits behind a Compose `profiles: ["observability"]` entry, so a plain `docker compose up` never starts it:

```bash
docker compose up --build                            # lab only: quarkus, python
docker compose --profile observability up --build     # + Grafana LGTM on :3000
```

Both applications are wired for OTLP export, with the collector endpoint set by an environment variable, but neither needs a collector to start. An OTLP exporter with no live endpoint fails in the background and never blocks an upgrade handshake or startup. Extra containers on every first boot would slow the inner loop for no signal, so tracing is opt-in and every example keeps this shape: fast by default, observability one flag away.

{% include excalidraw.html file="00-lab-topology" alt="The Compose lab: a wscat or browser client opening a WebSocket upgrade against a Quarkus container on host port 8080 and a Python container on host port 8081, both generated from the same AsyncAPI contract, with an optional LGTM stack reachable only when the observability profile is active." caption="Figure 0.1: The lab: one contract, two servers, OTel off by default." %}

## Version matrix

| Component | Pinned version | Why this one |
|---|---|---|
| JDK | 25.0.4 (LTS) | current LTS patch; every Quarkus Containerfile builds on it |
| Quarkus | 3.40.0 | current stable minor; 4.0 is beta as of this writing |
| Quarkus WebSockets Next | ships with Quarkus 3.40.0 | no separate version, part of the core extension set |
| Python | 3.15.0 | current stable language release |
| uv | 0.13.1 | current stable; installs the interpreter, resolves/locks deps, runs the project |
| FastAPI | 0.143.2 | current stable; routing and app lifecycle only, not the socket itself |
| websockets (library) | 17.1 | current stable; the native library both stacks' Python side builds on |
| AsyncAPI CLI | 6.2.1 | validates `contracts/asyncapi.yaml` once it exists |
| Docker Compose (plugin) | 5.6.0 | the `docker compose` subcommand, not the legacy `docker-compose` v1 binary |
| k6 | 2.3.0 | load-testing tool for sustained-connection tests |
| Newman | 6.2.3 | REST-side assertions at the booking-service seam |
| Kafka | 4.3.1 (KRaft mode, `apache/kafka` image) | current stable; backs the Kafka-backed reconnect design and the scale-out fan-out, ZooKeeper-free |
| Redis | 8.10.2-alpine | current stable; the other scale-out backplane, run alongside Kafka for cross-instance fan-out |
| PyJWT | 2.15.1 | current stable; validates the self-minted HS256 JWT at the upgrade handshake |

Every row is an exact version, never a floating major or `latest`, and bumped as a reviewed change when a survey finds a newer stable release. Nothing in the examples depends on a feature newer than the minimum the tool needs, so a reader a patch or two behind still runs them.

## Teardown

```bash
docker compose down --volumes --remove-orphans
```

`--volumes` matters because the `lgtm` service persists Tempo and Mimir data to a named volume between runs; leaving it means the first trace you capture may not be the first trace Tempo holds. `--remove-orphans` removes containers left under a service name the current `compose.yaml` no longer defines, such as a stale container from an interrupted run. Every example's `verify.sh` runs this teardown in a shell `trap`, so "run, see it fail, fix, run again" never accumulates state.

## Three runtime tiers

Docker Compose is the fast inner loop every example targets first. The same two services then come up on **minikube**, using the docker driver and the containerd runtime, to show the contract surviving a real scheduler, Services and readiness probes. Appendix A repeats the exercise on **OpenShift Local (CRC)** as a separate track, for routes, security context constraints and an Operator-managed Kafka. None of the tiers changes what either service does; each changes how a client reaches it and how the platform keeps it running.

{% include excalidraw.html file="00-tier-progression" alt="Three runtime tiers in sequence: Docker Compose, then minikube with the docker driver and containerd runtime, then OpenShift Local (CRC) as an appendix, joined by arrows labeled same contract, same services." caption="Figure 0.2: Three tiers, one contract: Compose, then minikube, then CRC." %}

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Pin exact current-stable versions (JDK 25 and Quarkus 3.40, Python 3.15 and uv, the Compose plugin), run every example through Docker Compose with LGTM behind an opt-in profile, and move to minikube and OpenShift Local only to change how the same services are reached and kept running.</p></div>

## For deeper coverage

- Gough, J. & Bryant, D. & Auburn, M., *Mastering API Architecture* (O'Reilly, 2022): the architectural decisions behind picking a toolchain and a runtime posture before a single endpoint exists.
- *Cloud Native Design Patterns*, "Communications" chapter: the interaction-style landscape the lab exercises one corner of.
- [Quarkus WebSockets Next guide](https://quarkus.io/guides/websockets-next): the extension every Quarkus example builds on.
- [Python `websockets` documentation](https://websockets.readthedocs.io/): the native library the Python stack uses for the socket itself.
- [Docker Compose documentation](https://docs.docker.com/compose/): `profiles`, `depends_on` health conditions, and the plugin version the lab depends on.
