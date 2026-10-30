# API Patterns and Practices: WebSockets

Designing WebSocket APIs well, with runnable examples in **Quarkus WebSockets Next**
and **Python** (FastAPI/Starlette plus the native `websockets` library) against one
AsyncAPI 3 contract. A chapter-based Jekyll site, in the `lgtm` house style.

Fourth and final per-style site in the *API Patterns & Practices* series (REST →
[gRPC](https://github.com/patterncatalyst/api-patterns-and-practices-grpc) →
[GraphQL](https://github.com/patterncatalyst/api-patterns-and-practices-graphql) →
WebSockets, after
[REST](https://github.com/patterncatalyst/api-patterns-and-practices-rest)). The
shipping/cargo domain is continuous across the series: here, the socket pushes a live
**handling-event feed** (container moves, customs holds, delivery confirmations) to
a client watching a booking, in place of polling the REST booking service for a status
that hasn't changed.

## What's here

- **29 chapters (Ch0–Ch28) plus an OpenShift Local (CRC) appendix:** from the real-time
  problem and the WebSocket decision framework through the protocol itself, AsyncAPI 3
  contract design and versioning, building the same feed in both stacks, backpressure,
  error handling, heartbeats, stateless and Kafka-backed reconnect, security, fan-out
  contrasted on Kafka and Redis, binary Protobuf framing, throughput tuning, testing and
  debugging a protocol you can't curl, observability, and a Final Project.
- **Both stacks, first-class:** every hands-on chapter ships a Quarkus (WebSockets Next,
  UBI 10) **and** a Python (FastAPI/Starlette + native `websockets`, Poetry) example
  against the **same** AsyncAPI 3 contract.
- **Contract-first:** AsyncAPI 3 is the single source of truth; both stacks generate
  from the same contract (contract + CI drift gate land in a later iteration).
- **Three tiers:** Docker Compose → minikube (docker driver, containerd runtime) →
  OpenShift Local (CRC), as a separate appendix.

This repository currently holds the bootstrap scaffold only: site chrome, the
locked outline, and the build plan. No chapter prose, no runnable examples, and no
contract yet.

## Domain

The canonical **shipping / cargo** domain used across patterncatalyst material:
`Booking`, `Cargo`, `Location` (UN/LOCODE), `Route`, `Operation`, and `Money` as a
decimal string. WebSockets here carries the live handling-event feed for a booking,
the same story as the REST and gRPC siblings, one tier down.

## Build locally

```bash
bundle install
bundle exec jekyll serve --baseurl ""
# → http://localhost:4000
```

## Layout

| Path | What |
|---|---|
| `_docs/` | The chapters + the CRC appendix (Markdown). |
| `_parts/` | The 9 Parts the chapters are grouped under. |
| `_plans/` | Build plan, decisions log, version matrix (rendered, not in nav). |
| `_example_pages/` | The examples index (stub until examples ship). |
| `scripts/` | Diagram generation (`generate_diagram.py`). |

## License

This project is dual-licensed to separate the code from the writing:

- **Code**: everything under `examples/`, plus build and helper scripts and
  inline code snippets, is licensed under the **Apache License 2.0**
  ([`LICENSE`](LICENSE)).
- **Content**: the tutorial and book prose (chapters under `_docs/`),
  diagrams and images under `assets/`, and the slide decks under
  `presentation/`, is licensed under **Creative Commons Attribution 4.0
  International (CC BY 4.0)** ([`LICENSE-docs.md`](LICENSE-docs.md)).

Copyright 2026 PatternCatalyst (Robert Sedor).

