---
title: "Setup and the Lab"
order: 0
part: "Prerequisites"
description: "Toolchain pins, the Docker Compose lab with opt-in LGTM tracing, and the shipping/cargo domain this site's sockets share with the REST booking service."
---

Every hands-on chapter from here forward hands you a live socket in two languages, pushing the same shipping/cargo handling events over the same AsyncAPI contract. This chapter pins the toolchain each example builds against, lays out the Docker Compose lab that boots both stacks side by side with observability one flag away, and describes the two scripts — `check-prereqs.sh` and the teardown — that make the lab's state predictable before a single line of handler code exists. Nothing here touches message shapes or connection lifecycle; that starts in Part 1. This chapter makes sure the toolchain and the lab shape are settled facts before the real protocol work begins, so neither is ever the thing you're debugging once a chapter asks you to reason about a reconnect or a backpressure policy instead.

The lab itself — the running `compose.yaml`, the `check-prereqs.sh` and teardown scripts — ships with the examples iteration, not this one. What follows describes the toolchain those scripts will check, the Compose shape they will bring up, and the exact commands and output you'll see once they land, so the contract between this chapter's prose and the forthcoming example is unambiguous.

## Toolchain pins

This site pins to the current stable release of each tool as of this writing, not an older LTS floor, for the same reason the REST and gRPC sibling sites do: a reader installing the toolchain today should land close to what every example targets, not several minor versions behind it. Quarkus builds on **JDK 25** (the current LTS line, patch **25.0.4**) and targets **Quarkus 3.40**, the current stable minor on the 3.x track — Quarkus 4.0 is in beta as of this writing and isn't adopted here until it ships stable. **WebSockets Next** is the extension that matters for this site specifically: it's the current-generation Quarkus WebSocket API, built on Vert.x and Mutiny from the ground up for structured concurrency and per-connection state, and it ships inside the same Quarkus release train rather than as a separately versioned artifact. The legacy `quarkus-websockets` extension still exists and still works, but every Quarkus example in this site uses WebSockets Next exclusively; Chapter 8 is where that extension gets a full treatment and the legacy API gets its one explicit mention, as the thing this site doesn't teach.

The Python side pins to **Python 3.15**, the current stable release of the language, managed by **Poetry 2.5** rather than `pip` and a hand-rolled virtualenv, or `uv` the way the gRPC sibling does it — Poetry is this site's own convention, chosen for its `pyproject.toml`-first workflow and lockfile semantics rather than copied from a sibling site without re-justifying it for this stack (DRQ-002). Every Python example builds on **FastAPI** for HTTP routing and app lifecycle, paired with the native **`websockets`** library for the socket itself rather than a framework-bundled WebSocket shim: FastAPI's own `WebSocket` type is a thin wrapper over Starlette's ASGI-level primitive, fine for a single-process toy, but the native library exposes the connection state machine, ping/pong control frames, and close-code handling directly — the exact knobs Part 4's liveness and reconnect chapters need. Chapter 9 covers that choice, and when reaching for the framework's built-in support is the right call instead, in full.

Contract-first work needs one more tool before either service exists: the **AsyncAPI CLI**, which validates `contracts/asyncapi.yaml` against the AsyncAPI 3.0 meta-schema the same way `buf lint` validates a `.proto` file on the gRPC site. Chapter 5 is where that contract gets written and validated for the first time; this chapter's lab only needs the CLI installed and on `PATH` so `check-prereqs.sh` can confirm it. Two load and functional testing tools round out the list without being needed for this chapter's own checks: **k6** drives the sustained-connection load tests Part 5 builds against, and **Newman** runs any REST-side assertions this site needs at the seam back to the REST booking service (DRQ-006). Installing both now means Part 5 is never the first time you reach for either.

{% include codetabs.html langs="Quarkus|Python" %}

```bash
# Quarkus — SDKMAN manages the JDK and the Quarkus CLI
sdk install java 25.0.4-tem
sdk install quarkus 3.40.0
quarkus create app shipping:handling-events-ws \
  --extension=quarkus-websockets-next,quarkus-opentelemetry
```
```bash
# Python — pyenv manages the interpreter, Poetry manages the project
pyenv install 3.15.0 && pyenv local 3.15.0
pipx install poetry==2.5.1
poetry new handling-events-ws && cd handling-events-ws
poetry add fastapi websockets uvicorn[standard] opentelemetry-distro
```

A container engine with the **Compose plugin** — Docker Engine or Docker Desktop providing `docker compose` as a CLI subcommand, not the legacy standalone `docker-compose` binary — is the one tool every chapter assumes without exception. The plugin itself has moved past the `2.x` line it's still colloquially called "v2" after (it's at `5.6` as of this writing); the name stuck because it replaced the Python-based v1 tool, and the version number runs on its own track, kept clear of the Compose *file* format's own v2/v3 schema numbering — a different thing entirely. The last toolchain piece is the observability stack itself: `grafana/otel-lgtm`, an all-in-one image bundling Loki (logs), Grafana (dashboards), Tempo (traces), and Mimir (metrics) behind a single OpenTelemetry Collector — the same image the gRPC and REST sites use, so a reader working through more than one site in this series reuses one mental model of where a trace ends up.

## The lab (compose + LGTM)

The Ch0 example's `compose.yaml` — landing with the examples iteration — brings up two services by default: `quarkus` on host port 8080 and `python` on host port 8081. Both expose a single upgrade path, `/events`, and both are generated against the exact same `contracts/asyncapi.yaml`. Neither pushes a real handling event yet — Chapter 5 is where the contract itself gets written, and the examples iteration after it is where a server first answers on the wire — but the Compose shape standing here now is the one every later chapter's lab reuses without re-explaining it: two services, one contract, one assertable connection.

A third service, `lgtm`, sits behind a Compose `profiles: ["observability"]` entry, exactly as it does on the REST and gRPC sites, which means a plain `docker compose up` never starts it:

```bash
docker compose up --build                            # lab only: quarkus, python
docker compose --profile observability up --build     # + Grafana LGTM on :3000
```

Both applications are wired for OTLP export unconditionally — the collector endpoint is an environment variable, nothing more — but neither one requires a collector to be listening to start cleanly. An OTLP exporter with no live endpoint fails in the background on its own schedule; it never blocks an upgrade handshake or the server's startup. At this stage there's nothing worth tracing beyond "a client connected," so four extra containers on every reader's first boot would slow the inner loop down for no signal. The profile exists so observability is one flag away the moment a chapter's content makes a trace worth looking at — starting with Part 6, where that trace is the whole point of the chapter — and every later chapter's lab keeps this same shape: fast by default, tracing opt-in.

{% include excalidraw.html file="00-lab-topology" alt="The Compose lab topology: a wscat or browser dev console opening a WebSocket upgrade against a Quarkus WebSockets Next container on host port 8080 and a Python FastAPI-plus-websockets container on host port 8081, both generated from the same contracts/asyncapi.yaml, with an optional LGTM observability stack reachable only when the observability profile is active." caption="Figure 0.1 — The lab: one contract, two servers, OTel off by default." %}

## check-prereqs.sh

`check-prereqs.sh` is the first thing every chapter's `verify.sh` calls, and the first thing a reader runs before touching Compose at all. It doesn't install anything — it only checks what's already on `PATH` against the pins in the previous section, and fails loud with the exact install command to fix whatever's missing, rather than letting a vague Compose build error be the first symptom of a missing toolchain. The script is deferred to the examples iteration (DRQ-013), but its shape is fixed now, because every later chapter's own prerequisite checks follow it: one `require` function per tool, a version comparison against a pinned minimum, and a single non-zero exit the moment the first check fails, so CI and a reader's terminal report the same failure the same way.

Each check follows the same three-step shape: locate the binary, parse its reported version, compare it against the pin. For a tool like `quarkus` that embeds its own version in `--version` output, that's a direct string compare; for `docker compose version`, it's a `>=` comparison against the plugin's minimum, since the exact patch rarely matters as long as the plugin architecture is new enough to support `profiles` and `depends_on` health conditions — both of which this chapter's lab uses. A missing tool prints its install command verbatim, copied from the toolchain pins above, so fixing a failed check never means leaving this chapter to go find the right flag.

## Version matrix

| Component | Pinned version | Why this one |
|---|---|---|
| JDK | 25.0.4 (LTS) | current LTS patch; every Quarkus Containerfile in this site builds on it |
| Quarkus | 3.40.0 | current stable minor; 4.0 is beta as of this writing |
| Quarkus WebSockets Next | ships with Quarkus 3.40.0 | no separate version — part of the core extension set |
| Python | 3.15.0 | current stable language release |
| Poetry | 2.5.1 | current stable; added official Python 3.15 support in 2.5.0 |
| FastAPI | 0.143.2 | current stable; routing and app lifecycle only, not the socket itself |
| websockets (library) | 17.1 | current stable; the native library both stacks' Python side builds on |
| AsyncAPI CLI | 6.1.0 | validates `contracts/asyncapi.yaml` from Chapter 5 onward |
| Docker Compose (plugin) | 5.6.0 | the `docker compose` subcommand, not the legacy `docker-compose` v1 binary |
| k6 | 2.3.0 | load-testing tool for Part 5; installed now, used later |
| Newman | 6.2.3 | REST-side assertions at the booking-service seam |

Every row is pinned to an exact version, never a floating major or a `latest` tag, and bumped as a reviewed change when the next survey pass finds a newer stable release — never as a side effect of an unrelated commit. The canonical copy of this table lives in `_plans/version-matrix.md`; this chapter's copy is the one `check-prereqs.sh` enforces at build time, so the two are kept in lockstep by the same review that bumps either one.

## Teardown

A lab that only knows how to start isn't one you can trust to start cleanly the next time. Tearing down this chapter's stack is one command:

```bash
docker compose down --volumes --remove-orphans
```

`--volumes` matters here specifically because the `lgtm` service, once started under the observability profile, persists Tempo and Mimir data to a named volume between runs; leaving it in place across chapters means the first trace you capture later in the book might not be the first trace Tempo holds. `--remove-orphans` catches the case where an earlier chapter's `compose.yaml` left a container running under a service name this chapter's file no longer defines — a stale container from an interrupted run, not a bug in the file itself. Every later chapter's `verify.sh` runs this exact teardown in a shell `trap` on exit, success or failure, which is what makes "run the lab, see it fail, fix the handler, run it again" a loop that never accumulates state between attempts.

This chapter's tier is the first of three this site climbs through, and the only one this chapter's lab stands up. Docker Compose is the fast inner loop every chapter's example targets first; Chapter 26 brings the identical two services up on **minikube**, using the docker driver and the containerd runtime rather than Podman, to show the same contract surviving a real scheduler, Services, and readiness probes. Appendix A repeats that exercise a third time on **OpenShift Local (CRC)**, as a separate, non-numbered track rather than folded into the minikube chapter, because the two platforms solve different problems — a free local cluster for iterating versus a faithful single-node OpenShift for routes, security context constraints, and an Operator-managed Kafka. None of the three tiers changes what either service does; each one only changes how a client reaches it and how the platform keeps it running.

{% include excalidraw.html file="00-tier-progression" alt="Three runtime tiers in sequence: Docker Compose, used in this chapter, as the fastest inner loop; minikube with the docker driver and containerd runtime in Chapter 26; and OpenShift Local (CRC) as a separate appendix. An arrow connects each tier to the next, labeled 'same contract, same services.'" caption="Figure 0.2 — Three tiers, one contract: Compose now, minikube and CRC later." %}

## On the wire

Once the examples iteration lands, running `check-prereqs.sh` against a fully-provisioned machine looks like this:

```text
$ ./scripts/check-prereqs.sh
checking java................. 25.0.4 (>= 25.0.0)        OK
checking quarkus............... 3.40.0 (>= 3.33.0)        OK
checking python................ 3.15.0 (>= 3.14.0)        OK
checking poetry................ 2.5.1 (>= 2.4.0)          OK
checking asyncapi.............. 6.1.0 (>= 5.0.0)          OK
checking docker................ 29.1.2                    OK
checking docker compose........ 5.6.0 (>= 2.20.0)         OK
checking k6..................... 2.3.0 (>= 1.0.0)          OK
checking newman................. 6.2.3 (>= 6.0.0)          OK
all checks passed — run: docker compose up --build
```

A missing or under-pinned tool fails exactly one line and stops the script there rather than listing every subsequent check as a cascading failure:

```text
checking poetry................ not found
missing dependency: poetry >= 2.4.0
  install: pipx install poetry==2.5.1
```

| Check | Pinned minimum | What it gates |
|---|---|---|
| `java` | 25.0.0 | Quarkus build and dev mode |
| `quarkus` | 3.33.0 | WebSockets Next extension availability |
| `python` | 3.14.0 | native `websockets` library's minimum interpreter |
| `poetry` | 2.4.0 | lockfile format this site's `pyproject.toml` files use |
| `asyncapi` | 5.0.0 | AsyncAPI 3.0 validation support |
| `docker compose` | 2.20.0 | `profiles` and `depends_on` health conditions |

The minimums in this table are looser than the exact pins in the Version Matrix above by design: a reader two patch releases behind the current pin still passes every check and runs every example correctly, because nothing in this site's examples depends on a feature introduced after the minimum. The exact pins exist so the book's own CI and container builds are reproducible; the minimums exist so a reader isn't forced into a same-day toolchain upgrade to start Chapter 0.

## Where this goes next

Chapter 1 steps back from the lab to the problem this site's first part spends its time justifying: why polling a REST endpoint stops working once "almost real-time" isn't good enough, and what a persistent connection buys over it instead. Chapter 3 gives WebSockets itself a full treatment — the HTTP Upgrade handshake, frame anatomy, control versus data frames, and the close-code vocabulary every later error-handling chapter refers back to. Chapter 5 is where `contracts/asyncapi.yaml` is written and validated for the first time, which is also the first chapter this site's CI gate enforces. Everything this chapter fixed — the toolchain pins, the Compose shape, the three-tier runtime progression, `check-prereqs.sh` as the thing every chapter runs first — stays constant from here forward; only what's behind each upgrade handshake gets more real.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>This site pins JDK 25 / Quarkus 3.40, Python 3.15 / Poetry 2.5, and the Compose plugin as the toolchain every example builds against, surveyed to current stable rather than an older LTS floor, with the lab running entirely through Docker Compose and LGTM gated behind an opt-in profile; <code>check-prereqs.sh</code> and the Compose lab itself ship with the examples iteration, but the pins, the Compose shape, and the three-tier runtime progression they target are fixed as of this chapter.</p></div>
