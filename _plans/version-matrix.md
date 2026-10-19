---
title: "Version Matrix"
layout: plan
render_with_liquid: false
---

# Version Matrix

> Surveyed: TBD at authoring time (r01 placeholder, 2026-10-18); Python, k6,
> Kafka, Redis, and PyJWT reconciled against Ch0 in the r04 toolchain pass
> (DRQ-023, DRQ-024), surveyed 2026-10-18.

This is a placeholder laid down at r01 bootstrap. Every row below gets a real,
dated survey pass — checked against the vendor's own release notes, not
memory — before the chapter that depends on it is written. Nothing in this
table is authoritative yet, except the rows marked below as reconciled.

| Component | Version |
|---|---|
| Quarkus (LTS) | TBD — confirm latest stable |
| Quarkus WebSockets Next | TBD — confirm latest stable |
| Python | 3.15.0 — current stable; matches Ch0 and every example's `requires-python` (DRQ-024) |
| FastAPI | TBD — confirm latest stable |
| websockets (library) | TBD — confirm latest stable |
| Kafka | 4.3.1 (KRaft mode, `apache/kafka` image) — current stable; 4.4.0 is RC-only as of this survey |
| Redis | 8.10.2-alpine — current stable |
| PyJWT | 2.15.1 — current stable; Ch17 JWT auth |
| k6 | 2.3.0 — current stable; load-testing tool, enters in **Part 4** (not Part 5 — DRQ-023) |
| Newman | TBD — confirm latest stable |
| JDK | TBD — confirm latest stable |
| Node | TBD — confirm latest stable |

## Dependency policy

Pin every dependency to the **upstream latest stable** release at the time
it's surveyed, exactly — never a floating major or a `latest` tag — and bump
it as a deliberate, reviewed change rather than a side effect of an unrelated
commit. Favor maintained, actively-developed open source; prefer CNCF or
otherwise vendor-neutral projects where a choice exists (Kafka over a
vendor-hosted broker, Redis over a vendor-hosted cache); no vendor-specific
cloud service is a dependency of any example in this site — everything here
runs on Docker Compose, minikube, or OpenShift Local.
