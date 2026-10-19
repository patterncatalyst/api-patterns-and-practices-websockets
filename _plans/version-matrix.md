---
title: "Version Matrix"
layout: plan
render_with_liquid: false
---

# Version Matrix

> Surveyed: TBD at authoring time (r01 placeholder, 2026-10-18); Python, k6,
> Kafka, Redis, and PyJWT reconciled against Ch0 in the r04 toolchain pass
> (DRQ-023, DRQ-024), surveyed 2026-10-18. Protobuf/buf toolchain (DRQ-025,
> Part 5) surveyed 2026-10-19 against each tool's own release page —
> `protobuf-java`/`protoc` share a minor.point release train (36.2) with
> Python's `protobuf` runtime on a different major (7.36.2) by the project's
> own numbering convention; Quarkus/JDK/Python rows below are carried over
> from the Ch0 pins (`_docs/00-setup-and-the-lab.md`) rather than re-surveyed
> here.

This is a placeholder laid down at r01 bootstrap. Every row below gets a real,
dated survey pass — checked against the vendor's own release notes, not
memory — before the chapter that depends on it is written. Nothing in this
table is authoritative yet, except the rows marked below as reconciled.

| Component | Version |
|---|---|
| Quarkus (LTS) | 3.40.0 — current stable minor on the 3.x track (Ch0 pin, `_docs/00-setup-and-the-lab.md`) |
| Quarkus WebSockets Next | ships with Quarkus 3.40.0 — not a separately versioned artifact |
| Python | 3.15.0 — current stable; matches Ch0 and every example's `requires-python` (DRQ-024) |
| FastAPI | TBD — confirm latest stable |
| websockets (library) | TBD — confirm latest stable |
| Kafka | 4.3.1 (KRaft mode, `apache/kafka` image) — current stable; 4.4.0 is RC-only as of this survey |
| Redis | 8.10.2-alpine — current stable |
| PyJWT | 2.15.1 — current stable; Ch17 JWT auth |
| k6 | 2.3.0 — current stable; load-testing tool, enters in **Part 4** (not Part 5 — DRQ-023) |
| Newman | 6.2.3 — current stable (npm); no `docker.io/postman/newman` image tag newer than `6.1.3` exists yet, so `examples/part6-testing/verify.sh` pins it via `npx newman@6.2.3` instead (DRQ-030, surveyed 2026-10-19) |
| JDK | 25.0.4 (Temurin) — current LTS line patch (Ch0 pin, `_docs/00-setup-and-the-lab.md`) |
| Node | 24.22.0 (LTS "Krypton") — current 24.x LTS patch; CI runtime for `npx newman` and any other JS tooling (`.github/workflows/contracts.yml` pins `actions/setup-node@v4` to `node-version: "24"`) |
| **Protobuf / buf (DRQ-025, Part 5)** | |
| `protobuf-java` | 4.36.2 — current stable (Maven Central); matches `protoc` 36.2's minor.point |
| Maven proto-generation plugin | `io.github.ascopes:protobuf-maven-plugin:5.1.11` — current stable; the maintained fork of `org.xolstice.maven.plugins:protobuf-maven-plugin`, which GitHub marks archived/read-only as of April 2025 |
| `protoc` | 36.2 (`protocolbuffers/protobuf` release) — current full stable release; v37.0 exists only as an RC as of this survey |
| Python `protobuf` runtime | 7.36.2 — current stable (PyPI); same 36.2 minor.point as `protoc`, different language-track major (the project's post-unification numbering: each language runtime shares the minor.point, Java's major is 4.x, Python's is 7.x) |
| `grpcio-tools` | 1.84.0 — current stable (PyPI); used only for its bundled `python -m grpc_tools.protoc` message-class generation — this site has no gRPC service, so nothing else in the package is exercised |
| `buf` | 1.74.0 — current stable (GitHub release); governs `contracts/buf.yaml` (`buf lint`/`buf build`/`buf breaking`) |

Protobuf/buf are new as of Part 5 (DRQ-025); `_docs/00-setup-and-the-lab.md`
(Ch0) does not yet list them; its toolchain-pins section should gain them
when Part 5's own chapter prose lands, carrying forward the versions pinned
above rather than re-surveying.

| **OpenTelemetry / Observability (DRQ-028, DRQ-029, Part 6)** | |
| `grafana/otel-lgtm` (Docker image) | `0.36.0` — pinned image tag (`examples/part6-observability/compose.yaml`); the same all-in-one Loki+Grafana+Tempo+Mimir+Collector image Ch0's lab (`_docs/00-setup-and-the-lab.md`) already names for the opt-in `observability` profile, and the one the gRPC/REST sibling sites use |
| `opentelemetry-distro` (Python, PyPI) | `>=0.66b1` — `examples/part6-observability/python/pyproject.toml`; zero-code auto-instrumentation entry point (`opentelemetry-instrument`), still pre-1.0/beta upstream |
| `opentelemetry-exporter-otlp-proto-grpc` (Python, PyPI) | `>=1.45.1` — `examples/part6-observability/python/pyproject.toml`; OTLP/gRPC exporter to the `lgtm` Collector on `:4317` |
| `opentelemetry-instrumentation-fastapi` (Python, PyPI) | `>=0.66b1` — `examples/part6-observability/python/pyproject.toml`; auto-instruments the FastAPI HTTP side (the WS connection span itself is hand-written — DRQ-028 finding: native `websockets` has no OTel auto-instrumentation) |
| OpenTelemetry SDK/API (Quarkus) | ships via `quarkus-opentelemetry` on the Quarkus 3.40.0 BOM (`examples/part6-observability/quarkus/pom.xml`) — not pinned separately; resolves to OTel SDK/API `1.62.0` + semconv `1.41.1` as of this survey (`mvn dependency:tree`) |
| `prometheus-client` (Python, PyPI) | `>=0.26.0` — `examples/part6-observability/python/pyproject.toml`; backs the Python stack's own `:8082/metrics` scrape (`handling_events_delivered_total`), independent of the OTel traces above |
| `quarkus-micrometer-registry-prometheus` | ships via the Quarkus 3.40.0 BOM (`examples/part6-observability/quarkus/pom.xml`) — not pinned separately; backs the Quarkus stack's `/q/metrics` scrape, parallel to the Python side's `prometheus-client` (no OTel-metrics bridge needed — each stack exports Prometheus directly) |

Observability is new as of Part 6 (DRQ-028/DRQ-029); `_docs/00-setup-and-the-lab.md`
(Ch0) already names `grafana/otel-lgtm` for the lab's opt-in `observability`
profile but does not pin the per-language OTel library versions above —
those stay app-level pins (`pyproject.toml`/the Quarkus BOM) surveyed here
rather than duplicated into Ch0.

## Dependency policy

Pin every dependency to the **upstream latest stable** release at the time
it's surveyed, exactly — never a floating major or a `latest` tag — and bump
it as a deliberate, reviewed change rather than a side effect of an unrelated
commit. Favor maintained, actively-developed open source; prefer CNCF or
otherwise vendor-neutral projects where a choice exists (Kafka over a
vendor-hosted broker, Redis over a vendor-hosted cache); no vendor-specific
cloud service is a dependency of any example in this site — everything here
runs on Docker Compose, minikube, or OpenShift Local.
