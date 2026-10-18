---
title: "Version Matrix"
layout: plan
render_with_liquid: false
---

# Version Matrix

> Surveyed: TBD at authoring time (r01 placeholder, 2026-10-18)

This is a placeholder laid down at r01 bootstrap. Every row below gets a real,
dated survey pass — checked against the vendor's own release notes, not
memory — before the chapter that depends on it is written. Nothing in this
table is authoritative yet.

| Component | Version |
|---|---|
| Quarkus (LTS) | TBD — confirm latest stable |
| Quarkus WebSockets Next | TBD — confirm latest stable |
| Python | TBD — confirm latest stable |
| FastAPI | TBD — confirm latest stable |
| websockets (library) | TBD — confirm latest stable |
| Kafka | TBD — confirm latest stable |
| Redis | TBD — confirm latest stable |
| k6 | TBD — confirm latest stable |
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
