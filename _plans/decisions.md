---
title: "Decisions Log"
layout: plan
render_with_liquid: false
---

# Decisions Log — API Patterns and Practices: WebSockets

A running log of design-relevant decisions (DRQ = Decision Request/Question),
seeded at r01 bootstrap. Later iterations append; nothing here is renumbered
or deleted.

## DRQ-001 — Repo, license, and bootstrap posture

Public GitHub repo, MIT license, remote-first: create the GitHub repo first,
then branch, then work — off-device durability from the first commit. Matches
the other three sites in the series.

## DRQ-002 — Two stacks: Quarkus WebSockets Next and Python

Every hands-on chapter ships both a **Quarkus** implementation on
**WebSockets Next** (the current-generation Quarkus WebSocket extension, not
the legacy `quarkus-websockets`) and a **Python** implementation on
**FastAPI/Starlette plus the native `websockets` library** — not a
framework-bundled WebSocket shim — with a chapter-level note on when to reach
for the native library versus a framework's built-in support. Quarkus builds
on UBI 10; Python is managed by **Poetry**, matching this site's own
convention rather than copying `uv` from the gRPC/REST siblings without
re-justifying it for this stack.

## DRQ-003 — AsyncAPI 3 contract spine, CI gate deferred

The **AsyncAPI 3** specification is this site's contract language — the
WebSockets analog of the REST site's OpenAPI and the gRPC site's Protobuf —
authored before any chapter example and used to generate both stacks. A CI
contract-drift gate (the analog of the gRPC site's `buf breaking`) is planned
but **deferred past r01**: it ships once the contract itself exists.

## DRQ-004 — Shared domain: the live handling-event feed

The socket pushes the shipping/cargo domain's **handling events** — container
moves, customs holds, delivery confirmations — to a client watching a
booking. Continuous with the REST and gRPC sibling sites' shipping/cargo
domain and glossary (Booking, Cargo, Location/UN-LOCODE, Route, Leg,
Operation, Money-as-decimal-string); WebSockets is the layer that replaces
polling the REST booking service for a status that hasn't changed.

## DRQ-005 — Fan-out on both Kafka and Redis, contrasted

Scale-out fan-out (Ch18) is taught on **both** Kafka and Redis (pub/sub or
streams), deliberately contrasted rather than picking one — the chapter's
point is the trade-off between them (durability and replay vs. simplicity
and latency), not a single recommended answer.

## DRQ-006 — Load and functional test tooling

**k6** is the load-testing tool for WebSocket connections (Artillery and
Gatling noted as alternatives, not adopted). **Newman** covers any REST-side
assertions this site needs (e.g., the seam back to the REST booking service).

## DRQ-007 — Runtime tiers

Three tiers, same progression as every other site in the series: **Docker
Compose** first, then **minikube** (docker driver, containerd runtime — the
podman path is not supported), then a **separate**, non-numbered **OpenShift
Local (CRC) appendix**. CRC is never folded into the minikube chapter.

## DRQ-008 — Diagram convention

Every diagram ships as a paired SVG + `.excalidraw` source via
`scripts/generate_diagram.py`. Emphasis/ink boxes are **light fill, dark
text** (`#f1f5f9` fill, `#64748b` border) — never a dark-filled box — matching
the house diagram standard. The gRPC site's copy of this script used a dark
`ink` fill; this site's copy corrects it at r01 rather than carrying the bug
forward.

## DRQ-009 — The outline is not a scope cap

29 chapters/appendix is the **current** locked outline, not an upper limit.
Later iterations may add chapters if the material warrants it; the sibling
per-style sites are reference-only for pacing and depth, never a hard cap.

## DRQ-010 — CRC as a non-numbered appendix; clean, contiguous numbering

The OpenShift Local (CRC) chapter is `_docs/99-appendix-a-openshift-crc.md` —
an `appendix: true` page outside the main sequence — while the numbered
chapters run **0–28 with no gaps**. User-confirmed at r01 bootstrap.

## DRQ-011 — Ch5 end-to-end anchor is a validatable contract, not a running service (r02)

r02 ships prose + the AsyncAPI 3 contract; `examples/` stays deferred to r03.
The Ch5 "runs end-to-end" anchor is satisfied by a contract that **validates**
against AsyncAPI 3 and that both stacks will generate from — not by a running
Quarkus/Python service this iteration. User-confirmed at r02 planning.

## DRQ-012 — Validate-only AsyncAPI CI now; full drift gate still deferred (r02)

A lightweight CI step runs `asyncapi validate` (pinned CLI) on
`contracts/asyncapi.yaml` from r02 onward, catching a broken contract. The full
regenerate-both-stacks-and-fail-on-drift gate (the analog of the gRPC site's
`buf breaking`) remains deferred until the examples generate from the contract.

## DRQ-013 — Ch0 lab scripts referenced as forthcoming, not authored in r02

Ch0 prose describes the toolchain pins, the Docker Compose lab, `check-prereqs.sh`,
the version matrix, and teardown, and points at the scripts landing with the
examples iteration. The scripts themselves are not authored in r02.

## DRQ-014 — Single-file AsyncAPI contract

The contract is one `contracts/asyncapi.yaml` (plus `contracts/README.md`), the
common AsyncAPI layout — not split across channels/operations/components files.
Revisit only if the contract grows enough to warrant `$ref` splitting.

## DRQ-015 — ~2 paired diagrams per chapter

Each r02 chapter ships roughly two paired SVG+`.excalidraw` figures, matching
the gRPC sibling's pacing; the hard floor is one per chapter.

## DRQ-016 — Chapter length: prose-word target, 2k floor / 2.5k soft target

Chapter depth is measured in **prose words, excluding code blocks and diagrams**.
**2,000 words is a hard floor** (never ship below). **2,500 words is a target,
not a ceiling** — exceeding it is fine when the extra words carry value, not
padding; longer chapters should carry more explanatory diagrams. Do not trim a
chapter just to reach 2,500. This replaces the earlier byte-size heuristic
borrowed from the sibling sites.

## DRQ-017 — Companion decks: one 101 plus a 201 per language

The site ships **three** companion decks (deferred past r02, same posture as the
gRPC/REST siblings): a **101** concept-level deck (transport-agnostic real-time
and WebSockets fundamentals, the decision framework, the contract story), and
**two 201** decks — **one per language** (201 Quarkus WebSockets Next, 201 Python
native `websockets`) — each a hands-on build against the shared AsyncAPI
contract. Built with `lgtm-presentation` (pptxgenjs, site figures reused as PNGs,
notes==slides, 0 ban-tier), no docx.

Each deck **targets ~50 slides** in the main body; anything beyond that goes into
**appendices** rather than inflating the core narrative, so the main track stays
deliverable in a session while depth stays available on reference.
