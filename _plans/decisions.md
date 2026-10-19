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
on UBI 10; Python is managed by **`uv`** (uv-managed `pyproject.toml`,
`uv sync` / `uv run`, `uv.lock`), the long-standing house standard across the
REST/gRPC sibling API sites and the `lgtm-python` scaffold.

**Amended (r03 kickoff, 2026-10-18):** this originally specified Poetry. That
was an anomaly; the house standard is `uv`, and this site follows it. The r02
Ch0 toolchain/version-matrix/prereqs references to Poetry are corrected to `uv`
alongside this amendment.

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

**Decks are the LAST deliverable.** All chapters (Parts 0–8, Ch0–28 + the CRC
appendix) and all runnable examples/demos ship first; the three decks are built
only once the book and its code are complete. Decks are mined from finished
chapters, so writing them earlier would mean reworking them as chapters land.

## DRQ-018 — Generate-from-contract + drift-gate design (r03)

Generated artifacts are **never committed** (series norm). `scripts/extract-message-schema.py`
derives a standalone JSON Schema (Draft 2020-12) for `HandlingEvent` from
`contracts/asyncapi.yaml`. **Python** models are generated at build time with
`datamodel-code-generator` (gitignored). **Quarkus** uses idiomatic hand-written
Java records guarded by a build-time schema-conformance test
(`networknt/json-schema-validator`). The **full drift gate** is: (a) `asyncapi
validate`; (b) `asyncapi diff` vs `main` (the breaking-change detector, analog of
the gRPC site's `buf breaking`, with a first-introduction skip guard); (c) a
`drift` job that extracts the schema, regenerates the Python model, and runs both
stacks' conformance tests; (d) an `examples` matrix running each `verify.sh`.
Rejected: commit-generated-models + `git diff --exit-code` (commits generated
code, invites codetab/real-code drift). User-confirmed at r03 planning.

## DRQ-019 — Examples verified by live headless boot (r03)

Each example ships a `verify.sh` that boots both stacks via `docker compose`,
opens a real WebSocket with a pinned self-downloaded `websocat`, captures the
first server-pushed `HandlingEvent` frame, and validates it against the extracted
schema on both stacks — a genuine end-to-end run, not test-only assertions.
Matches the gRPC sibling and the house headless-verification posture. k6 stays
load-only and deferred to Part 4 (DRQ-006); Newman is not needed in Part 3 (no
REST seam).

## DRQ-020 — Part 4 ships two per-Part example apps (r04)

`examples/part4-connection/` holds the per-connection-lifecycle chapters (Ch12
backpressure, Ch13 error handling, Ch14 liveness/heartbeats, Ch17 security) —
no broker, so its verify stays fast. `examples/part4-backplane/` holds the
backplane chapters (Ch15 stateless reconnect on the default profile, Ch16
Kafka-backed reconnect on `--profile kafka`, Ch18 scale-out fan-out on
`--profile kafka` and `--profile redis`), keeping the stateless-vs-Kafka
reconnect **centerpiece** in one profile-toggled codebase. Rejected: one
monolithic app (couples light demos to broker bring-up) and seven per-chapter
apps (breaks the per-Part convention, multiplies drift surface).

## DRQ-021 — Ch17 auth: self-minted HS256 JWT at the upgrade; Keycloak named

The socket authenticates with a self-minted **HS256 JWT** carried in the
contract's `token` query param, validated at the WebSocket upgrade on both
stacks (Python in the `websockets` handshake hook with PyJWT; Quarkus at the
upgrade/`@OnOpen`), with runtime token minting so `exp` never goes stale.
**Keycloak/OIDC is named as the production, Red Hat-aligned path but not stood
up in CI** (heavyweight cold start + JWKS flakiness for a teaching example).
Matches the gRPC sibling's auth precedent.

## DRQ-022 — Ch18 scale-out fan-out runs live in CI on both Kafka and Redis

The multi-instance fan-out proof (a client on instance A receives an event
published through instance B) runs **live in CI on both Kafka and Redis**
(single broker, two instances, generous timeouts + the existing 3× matrix
retry), contrasted per DRQ-005. Each frame/log carries its serving instance id
so the A/B assertion can prove the event crossed instances.

## DRQ-023 — k6 is a gated smoke run in CI; k6 enters in Part 4

k6 WS load scripts ship under each Part 4 app and run a **small gated smoke
load in CI** (not merely opt-in). k6 formally enters the series in **Part 4**
(correcting the earlier "Part 5" label in Ch0 and the version matrix); it
remains the load tool, Newman the functional tool (DRQ-006).

## DRQ-024 — One Python version across docs and examples

Ch0's matrix, `_plans/version-matrix.md`, and every example pin the **same**
Python version. r02's Ch0 said 3.15 while the r03 examples run 3.14; r04
reconciles them to a single value — the newest stable the stack supports
(attempt 3.15 across the examples; hold at 3.14 only if an actual
incompatibility blocks it, recording the hold next to the pin).

**Resolved (r04 toolchain pass, 2026-10-18):** 3.15.0 — no hold needed. Every
dependency in `examples/part3-handling-events/python/pyproject.toml`
(FastAPI, `websockets`, uvicorn, opentelemetry-distro, pydantic/pydantic-core,
datamodel-code-generator, jsonschema, pytest) installs clean under CPython
3.15.0 via `uv sync`, `uv run pytest tests/test_contract.py` passes (5/5), and
`scripts/generate-models.sh` regenerates cleanly with
`--target-python-version 3.15`. `requires-python`, `.python-version`, and
`uv.lock` in both `examples/part3-handling-events/python/` and
`examples/part3-handling-events/clients/python/` now read `3.15`/`3.15.0`,
matching Ch0 and `_plans/version-matrix.md`.

One real sub-hold surfaced in the Containerfile, not the dependency set: UBI
10 has not published a `ubi10/python-315-minimal` image as of this survey
(`skopeo list-tags` on it returns repo-not-found; the Red Hat Catalog API
returns zero results), so the base image still ships only a 3.14 system
interpreter. Left alone, `uv sync` would silently fall back to downloading an
unpinned CPython build to satisfy the new `>=3.15` floor, and that downloaded
interpreter wouldn't survive the multi-stage `COPY --from=build` into the
runtime image (verified by building the unmodified Containerfile: the image
built, but the server failed at startup with `ModuleNotFoundError: No module
named 'uvicorn'` — the venv's `python3` symlink pointed outside what got
copied). Fixed by pinning the fallback explicitly (`uv python install
3.15.0` under `UV_PYTHON_INSTALL_DIR=/app/.uv-python`) and copying that
directory into the runtime stage alongside `.venv`. Rebuilt and verified live:
the image now starts cleanly on CPython 3.15.0 and serves both the WS and
HTTP ports. Revisit once Red Hat ships a `ubi10/python-315-minimal` image and
drop the uv-managed interpreter in favor of it.

## DRQ-025 — Protobuf as a parallel binary encoding; buf + AsyncAPI↔proto parity gate (r05)

Part 5 adds **Protobuf as a second wire encoding** of the same `HandlingEvent`,
alongside the JSON the AsyncAPI contract defines. A single hand-kept
`contracts/handling-event.proto` (proto3, `shipping.handlingevents.v1`, stable
field numbers, `HANDLING_EVENT_TYPE_UNSPECIFIED = 0`) mirrors the AsyncAPI
message. **Timestamps stay RFC-3339 `string` fields** (not
`google.protobuf.Timestamp`) so the Protobuf and JSON field VALUES are identical
and the two encodings can be asserted equal. Governed by **buf** (`contracts/buf.yaml`,
lint STANDARD + breaking FILE with a first-introduction skip, matching the gRPC
sibling) PLUS a custom `scripts/check-proto-parity.py` that diffs the proto's
field/enum set against `build/handling-event.schema.json` — buf cannot see the
AsyncAPI side, and proto-vs-JSON drift is the real failure mode. Generated proto
stubs are never committed (Java under `target/`, Python `*_pb2.*` gitignored).

## DRQ-026 — Encoding negotiation via subprotocol (r05)

A client selects JSON vs Protobuf through the WebSocket **subprotocol**
(`Sec-WebSocket-Protocol`): `handling-events.v1+json` (default) vs
`handling-events.v1+protobuf`, extending the contract's existing
`handling-events.v1`. The idiomatic WS content-type mechanism, tied to Ch3;
websocat (`--protocol`) and k6 can set it. The AsyncAPI contract is edited
**additively** to document the two subprotocols so the breaking gate stays green.

## DRQ-027 — k6: smoke gated, comparative benchmark local (r05)

The Part 5 k6 **smoke** run is gated in CI (both encodings stream on both
stacks). The comparative JSON-vs-Protobuf-vs-deflate **throughput benchmark**
(size + messages/sec into LGTM) is **local-only** — absolute throughput is
host-dependent and would make a flaky gate. Consistent with DRQ-023/DRQ-006.

## DRQ-028 — Part 6: new part6-observability example, verified in the examples matrix (r06)

Ch23 ships a new `examples/part6-observability/` (both stacks) that turns on live
OpenTelemetry over a WebSocket into the LGTM stack — today OTel is wired but
INERT (Quarkus `quarkus.otel.sdk.disabled=true`, Python entrypoint not wrapped in
`opentelemetry-instrument`, the `lgtm` compose service behind an unused profile),
so nothing lands in Tempo. The new app makes **`lgtm` a hard dependency** (not
profile-gated) and both stacks export. Verified HEADLESS, in the standard CI
`examples` matrix, with the gRPC-sibling split: **HARD** asserts (the connection's
trace id appears in the app's own structured log line + a WebSocket metric is
present via a synchronous Prometheus scrape) and a **SOFT** Tempo poll
(`:3200/api/traces/<id>`, bounded retry, warns on ingest lag, never fails). Key
WS finding: the native `websockets` library has no OTel auto-instrumentation, so
the Python connection/push span is created MANUALLY with the SDK tracer — vs
Quarkus auto-tracing the HTTP upgrade. Ch21/22/24 are prose citing existing
evidence; only Ch23 adds runnable code.

## DRQ-029 — Observability metrics shape (r06)

Quarkus exposes metrics via Micrometer→Prometheus (`quarkus-micrometer-registry-prometheus`,
scraped at `/q/metrics`); Python exposes a Prometheus endpoint (prometheus-client
or the OTel metrics exporter). `verify.sh` asserts a WebSocket metric is present
per stack (sum-all-labels > 0), mirroring the gRPC sibling's `assert_metric_present`.
Both stacks also export OTLP traces to LGTM.

## DRQ-030 — Newman functional HTTP testing in Part 6 (r06)

Part 6 ships a **full Newman example** (DRQ-006: Newman = functional): a runnable
Postman/Newman collection exercising the HTTP surfaces this site exposes —
health endpoints and the part4-backplane `POST /internal/.../handling-events`
inject endpoint (202 + schema-valid body) — run via a pinned Newman in a CI step
and cited by Ch21 as the functional-testing layer alongside the WS verify.sh/k6
corpus. (The contract itself is WS-only; Newman covers the HTTP seam around it.)
