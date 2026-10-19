---
title: "Build & Iteration Plan"
layout: plan
render_with_liquid: false
---

# Build & Iteration Plan — API Patterns and Practices: WebSockets

Fourth and final per-style site in the series (REST → gRPC → GraphQL → WebSockets).
This document covers **r01 — bootstrap scaffold** only: site chrome, the locked
outline, and the plans ledger. No chapter prose, no runnable examples, and no
contract are written in r01.

Repo: `patterncatalyst/api-patterns-and-practices-websockets` (public, remote-first).
Mirrors the house style of the sibling sites: parts→chapters, a Part-card homepage,
numbered chapter pages, a `_plans` ledger that renders but isn't in nav, and a
`_docs/99-appendix-a-openshift-crc.md` non-numbered appendix.

## r01 scope (this iteration)

- Site chrome copied byte-for-byte from `api-patterns-and-practices-grpc`:
  layouts, includes, CSS, codetabs JS, `.gitignore`, `.gitattributes`, `Gemfile`,
  `LICENSE`, the Pages CI workflow.
- `_config.yml` and `index.html` adapted for identity only (title, description,
  emoji, repo name, baseurl, hero copy, stat tiles).
- The outline locked: 9 Parts (`_parts/`), 29 chapter/appendix stubs (`_docs/`),
  front matter only except Part 0 and Part 1, which carry section headings with
  no prose.
- `scripts/generate_diagram.py` copied and fixed for this site: WebSockets
  wording, and the `ink` emphasis-box palette corrected to light fill / dark
  text (DRQ-008) rather than the dark-fill box the gRPC copy used.
- Nav stub pages (`_example_pages/index.md`, `bibliography.md`) so the header
  and footer links resolve to a real, if empty, page.
- This plan, the decisions log, and a dated placeholder version matrix.

## Locked outline

**Part 0 — Prerequisites**: Ch0 Setup and the lab.
**Part 1 — Foundations**: Ch1 The real-time problem, Ch2 Choosing the right tool,
Ch3 How WebSockets work, Ch4 The shared domain.
**Part 2 — Contract-first for Sockets**: Ch5 AsyncAPI: giving a socket a contract,
Ch6 Message design, Ch7 Versioning and evolution.
**Part 3 — Building It**: Ch8 Quarkus WebSockets Next, Ch9 Python native
WebSockets, Ch10 Clients: reconnect and backpressure, Ch11 Polyglot: one
contract, two stacks.
**Part 4 — Production Concerns**: Ch12 Backpressure and flow control, Ch13 Error
handling, Ch14 Liveness and heartbeats, Ch15 Reconnect: stateless, Ch16
Reconnect: Kafka-backed, Ch17 Security, Ch18 Scale-out and fan-out.
**Part 5 — Performance & Optimization**: Ch19 Binary Protobuf over WebSockets,
Ch20 Optimizing throughput.
**Part 6 — Testing, Debugging & Observability**: Ch21 Testing WebSockets, Ch22
Debugging WebSockets, Ch23 Observability, Ch24 Anti-patterns.
**Part 7 — Runtime Progression**: Ch25 Docker Compose, Ch26 Kubernetes
(minikube), Appendix A OpenShift Local (CRC).
**Part 8 — The Bigger Picture**: Ch27 When you don't need a socket, Ch28 Final
project.

29 chapter/appendix files total (Ch0–Ch28 plus the appendix), clean and
gap-free, no scope cap.

## r02 scope (in progress)

Author full house-depth prose for **Parts 0–2** (Ch0–Ch7), author the **AsyncAPI
3 contract**, and add the **hub entry**. Examples remain deferred to r03.

- **Contract-first spine.** `contracts/asyncapi.yaml` (single file, AsyncAPI
  3.0.0) + `contracts/README.md` are written before the contract-bound chapters.
  The `handling-events` channel carries the DRQ-004 shipping/cargo handling
  events; one reused `HandlingEvent` message; Money-as-decimal-string;
  UN/LOCODE locations; enums with `*_UNSPECIFIED` zero value.
- **Chapters.** Ch0 Setup and the lab, Ch1 The real-time problem, Ch2 Choosing
  the right tool, Ch3 How WebSockets work, Ch4 The shared domain, Ch5 AsyncAPI:
  giving a socket a contract, Ch6 Message design, Ch7 Versioning and evolution.
  Each: lead paragraph → 4+ `## ` sections → ~2 paired SVG+Excalidraw diagrams
  → `## On the wire` box → `## Where this goes next` → closing **Decision**
  callout. Depth calibrated against the gRPC sibling site.
- **Ch5 anchor = validatable contract only** (DRQ-011): Ch5 references the real
  `contracts/asyncapi.yaml` and shows it validating; no runnable service yet.
- **CI.** Add a **validate-only** AsyncAPI CI step now (DRQ-012); the full
  regen/drift gate stays deferred until examples land.
- **Ch0** writes prose that references the lab scripts as forthcoming
  (DRQ-013); the scripts themselves land with the examples iteration.
- **Hub entry** in `patterncatalyst/workshops-tutorials-list`
  `_data/sites.yml`, after the graphql block, under `group: "API Design"`.

Build sequence: contract → Ch0–Ch3 (parallel) → Ch4–Ch7 (contract-bound) →
hub → CI step → `bundle exec jekyll build` + voice scan. Checkpoint commit per
chapter.

## r03 scope (in progress)

**Part 3 "Building It" (Ch8–11) + the first runnable examples + the full
contract-drift gate.** The first iteration with runnable code.

- **Per-Part example app** under `examples/part3-handling-events/`
  (`quarkus/` + `python/` + `clients/`, one `compose.yaml`, one `verify.sh`),
  both stacks serving the `contracts/asyncapi.yaml` handling-events feed, code
  grown **additively** across Ch8→11 so earlier codetabs stay valid. Harness
  copied/extended from the gRPC sibling's `examples/_lib/lib.sh`.
- **Generate-from-contract without committing generated code** (DRQ-018):
  `scripts/extract-message-schema.py` derives a JSON Schema from the contract;
  Python models generated at build time (`datamodel-code-generator`), Quarkus
  uses idiomatic hand-written records guarded by a schema-conformance test.
- **Full contract-drift gate** (DRQ-018, upgrades the r02 validate-only job):
  `asyncapi diff` vs `main` (breaking-change detector, the `buf breaking`
  analog) + a `drift` job that regenerates models and runs both stacks'
  conformance tests + an `examples` matrix running `verify.sh`.
- **Verification = live headless boot** (DRQ-019): `verify.sh` boots both stacks
  via `docker compose`, opens a real socket with pinned `websocat`, and asserts
  a live `HandlingEvent` frame validates against the extracted schema.
- **uv** throughout the Python stack (pinned `0.13.1`), not Poetry (DRQ-002
  amended). **k6 deferred to Part 4** (DRQ-006: k6 = load). Ch10 Quarkus client
  uses the WebSockets-Next `@WebSocketClient` API.
- Chapters Ch8–11 to the house standard (DRQ-016 word floor, DRQ-008/015
  diagrams, On-the-wire box, Decision callout), codetabs citing the real
  `examples/` code.

Build order: harness + extractor → scaffold both apps + pass `verify.sh` →
write Ch8–11 against the working code → wire the drift gate → build + voice +
checkpoint. Chapters follow working code so codetabs are real.

## r04 scope (in progress)

**All of Part 4 "Production Concerns" (Ch12–18) + two runnable example apps +
broker infra + CI extension.** The largest iteration.

- **Two apps (DRQ-020):** `examples/part4-connection/` (Ch12 backpressure
  server-side, Ch13 error handling, Ch14 liveness/heartbeats, Ch17 security —
  no broker) and `examples/part4-backplane/` (Ch15 stateless reconnect, Ch16
  Kafka-backed reconnect, Ch18 scale-out fan-out — brokers behind compose
  profiles). Both fork the part3 convention, reuse the contract + fixture +
  `_lib/lib.sh`, stay drift-gated.
- **Centerpiece:** Ch15 (visible gap, no backplane) vs Ch16 (Kafka
  offsets/replay/dedup) in one profile-toggled codebase, with paired both-stack
  with/without-Kafka diagrams.
- **Auth (DRQ-021):** self-minted HS256 JWT at the upgrade, both stacks,
  Keycloak named not run.
- **Scale-out (DRQ-022):** fan-out proven live in CI on **both** Kafka and
  Redis, two instances, with a serving-instance id in each frame.
- **k6 (DRQ-023):** gated smoke load in CI; k6 enters in Part 4.
- **Infra:** Kafka (KRaft) + Redis via compose profiles, pinned; healthcheck-
  gated start to tame CI flakiness.
- **Reconcile (DRQ-024):** one Python version across Ch0 matrix, the version
  matrix, and all examples; fix the k6 "Part 5"→"Part 4" label.

Build order: version/ledger survey → extend harness → App A + verify → App B +
broker infra + verify → chapters against working code → CI drift/gate + k6 →
build + voice + checkpoint. Chapters follow working code.

## r05 scope (in progress)

**Part 5 "Performance & Optimization" (Ch19–20) + Protobuf binary encoding +
throughput benchmark.**

- **New app `examples/part5-performance/`** (both stacks) serves the shared
  fixture over the SAME channel in two encodings — JSON text vs Protobuf
  binary — selected per connection by **subprotocol** (DRQ-026).
- **`contracts/handling-event.proto`** mirrors the AsyncAPI `HandlingEvent`
  (RFC-3339 string timestamps for value parity); governed by **buf** +
  `scripts/check-proto-parity.py` (AsyncAPI↔proto field/enum parity) — DRQ-025.
- **verify.sh** decodes a real Protobuf binary frame matching the contract on
  both stacks, asserts JSON and Protobuf field values identical, and the binary
  frame smaller (DRQ-019).
- **Ch19** Binary Protobuf over WebSockets; **Ch20** Optimizing throughput
  (JSON vs Protobuf size, batching, permessage-deflate + CRIME caveat,
  connection/message limits, backpressure interplay).
- **CI**: `part5-performance` added to the drift gate + examples matrix; a
  buf-lint/parity step; **k6 smoke gated**, comparative benchmark local (DRQ-027).
- Generated stubs never committed.

Build order: version survey + proto/contract + parity gate → app both stacks +
verify green → Ch19/Ch20 against the working code → CI/k6 → build + voice.

## r06 scope (in progress)

**Part 6 "Testing, Debugging & Observability" (Ch21–24).** One new runnable
example (Ch23) + three prose chapters citing existing evidence + a Newman
functional example.

- **Ch21 Testing** — prose; documents the real corpus (four verify.sh, lib.sh
  helpers, pytest/@QuarkusTest conformance, k6 smoke, close-code probes) + the
  new **Newman** functional HTTP collection (DRQ-030).
- **Ch22 Debugging** — prose; websocat/devtools/tcpdump/close-codes with real
  captured output from the existing apps.
- **Ch23 Observability** — NEW `examples/part6-observability/` (both stacks):
  live OTel traces+metrics into LGTM (hard dep), the manual-span-for-native-
  websockets finding, verified HARD-logs+metric / SOFT-Tempo in the examples
  matrix (DRQ-028/029).
- **Ch24 Anti-patterns** — prose; each pitfall grounded in a real Part 3–5
  finding (idle-timeout trap, asyncio maxsize=0, stateless gap, auth-at-upgrade,
  proto field reuse, subprotocol-no-offer, …).

Build order: survey/pin OTel+Newman → part6-observability app both stacks +
verify green → Newman collection + CI → Ch23 then Ch21/22/24 → CI drift/matrix +
version matrix → build + voice. Code before prose.

## r07 scope (COMPLETE — both clusters verified live, chapters + CI done)

**Part 7 "Runtime Progression" (Ch25 Compose, Ch26 minikube, Appendix A CRC).**
Deploy part4-backplane (both stacks) across the three runtime tiers (DRQ-031).

**DONE:** minikube manifests + `verify-minikube.sh` VERIFIED LIVE HEADLESS
(4237f1d); CRC `openshift/` appendix VERIFIED LIVE HEADLESS on CRC 2.64.0 /
OCP 4.22.14 (5fadafc, evidence 2026-10-19); all three chapters written to the
house depth standard (Ch25 2704w, Ch26 2996w, AppA 2497w — no spine, 0
ban-tier voice); `scripts/wordcount.sh` (warning-only gate, from the gRPC
sibling); static `k8s-manifests` kubeconform CI job in `contracts.yml` (no
cluster in CI). Kafka pinned 4.2.0 on CRC (operator floor; recorded step-back
from 4.3.1 on compose/minikube). Four CRC live-run fixes captured in
`openshift/README.md` "What broke". Remaining: PR → squash-merge to main.

- **Ch25 Docker Compose** — prose over the existing per-example composes
  (build-context-repo-root, healthcheck-gated, profiles, the 4-instance backplane,
  the verify.sh/_lib harness). No unified monolith compose.
- **Ch26 Kubernetes (minikube)** — kustomize base+overlay, ingress-nginx WS
  upgrade + sticky + idle-timeout, Strimzi Kafka + Redis in-cluster, image-load
  (docker+containerd; podman unsupported), the cross-pod fan-out-through-ingress
  proof. Verified LIVE headless.
- **Appendix A OpenShift Local (CRC)** — restricted-v2 Helm + edge-TLS Routes +
  AMQ Streams, in-cluster builds (Quarkus S2I, Python Docker-strategy), the
  edge-carries-WS contrast, teardown. Verified LIVE headless.
- **CI**: add a static `k8s-manifests` (kubeconform) job; NO cluster in CI;
  cluster verify scripts in subdirs (not matched by the examples matrix glob).

Build order: pins/ledger → minikube manifests + verify LIVE → CRC helm/scripts +
verify LIVE → Ch25/26/AppA against captured evidence → CI + build + voice. Code
(manifests, verified on a real cluster) before prose.

## Deferred to later iterations (r02+)

- Chapter prose for all 29 chapters, to the house depth standard (paired
  SVG+Excalidraw diagrams, the "On the wire"-equivalent box, a closing
  "Decision" callout).
- Runnable examples under `examples/`, one per hands-on chapter, Quarkus +
  Python, each with its own `verify.sh`.
- The AsyncAPI 3 contract itself under `contracts/`, plus the CI
  contract-drift gate that regenerates both stacks and fails the build on
  drift (the WebSockets analog of the gRPC site's `buf breaking` gate).
- The hub entry: `patterncatalyst/workshops-tutorials-list` `_data/sites.yml`
  gets this site added once there is real content to point at.
- The companion decks for this site: a 101 concept deck plus a 201 per language
  (201 Quarkus, 201 Python), each targeting ~50 slides with overflow in
  appendices (DRQ-017).
- `_example_pages/index.md` and `bibliography.md` filled in with real content
  (currently nav stubs only).

## Release cadence

Iterations ship by Part, never by stack, so the two implementations never
diverge. Each iteration ends on a clean `bundle exec jekyll build` with this
plan's scope section updated. The earliest "it runs and is traced end to end"
moment targets the Ch5 AsyncAPI contract anchor, mirroring the gRPC site's
Ch5 unary anchor and the REST site's contract-first anchor — not the last
iteration.
