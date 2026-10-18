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
- The companion deck(s) for this site.
- `_example_pages/index.md` and `bibliography.md` filled in with real content
  (currently nav stubs only).

## Release cadence

Iterations ship by Part, never by stack, so the two implementations never
diverge. Each iteration ends on a clean `bundle exec jekyll build` with this
plan's scope section updated. The earliest "it runs and is traced end to end"
moment targets the Ch5 AsyncAPI contract anchor, mirroring the gRPC site's
Ch5 unary anchor and the REST site's contract-first anchor — not the last
iteration.
