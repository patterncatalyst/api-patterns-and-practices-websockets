---
title: "Final Project"
order: 28
part: "The Bigger Picture"
description: "Assemble every concern built in isolation into one deployed system, and verify it with the scripts that already prove each part."
duration: "20 min read"
---

## Learning objectives

By the end of this chapter you can:

- Assemble the `handlingEvents` feed on both stacks against `contracts/asyncapi.yaml` and `contracts/handling-event.proto`, starting from `examples/part3-handling-events` and layering each later concern on top.
- Explain what connection hardening, reconnect and backplane, binary encoding, and observability each add to the same channel, and where in the codebase each one lives.
- Deploy the assembled system to minikube and to OpenShift Local (CRC) with the assets in `examples/part4-backplane/k8s` and `examples/part4-backplane/openshift`.
- Verify every layered capability with the script that proves it, so a later layer cannot silently regress an earlier one.

## Why this matters

Each part of the `handlingEvents` channel was built in isolation. The `examples/part5-performance` images strip out the JWT and backpressure guards so a frame-size comparison is not confused by auth overhead. The observability example drops heartbeat and backpressure code so the trace being read carries no other concern. None of those directories is what a team ships. A team ships the same contract carrying every concern at once, deployed where it has to hold up under traffic.

This project needs no new example. It composes six directories that already exist and runs them against their own `verify.sh` scripts, because the proof that assembly breaks nothing has to be the proof each layer already trusts.

## The brief

Build in order:

1. `examples/part3-handling-events`: the contract-generated feed.
2. `examples/part4-connection`: JWT, error taxonomy, backpressure, heartbeats.
3. `examples/part4-backplane`: reconnect resume, Kafka or Redis fan-out.
4. `examples/part5-performance`: Protobuf alongside JSON.
5. `examples/part6-observability`: traces and metrics.
6. `examples/part6-testing`: the Newman functional-HTTP layer.

Deploy with `examples/part4-backplane/k8s` to minikube, and separately with `examples/part4-backplane/openshift` to OpenShift Local.

The contract (`operations.receiveHandlingEvent` on `/ws/v1/bookings/{bookingId}/handling-events`, `contracts/asyncapi.yaml` lines 76 to 105) and the shared fixture (`examples/part3-handling-events/fixtures/handling-events.json`, the three `RECEIVE`, `LOAD`, `CUSTOMS` events every stack replays in order) do not change across any layer. What changes is what sits around that one channel and that one fixture. The `part4-backplane` deploy assets are the furthest along: they already carry the backplane and are what the cluster scripts exercise. Treat the earlier examples as concerns layered onto that deployable shape, in the order they were introduced.

{% include excalidraw.html file="28-final-project-system" alt="One contract (asyncapi.yaml and handling-event.proto) and one fixture (RECEIVE, LOAD, CUSTOMS) feed the handlingEvents channel on both stacks, which layers connection hardening (close codes 1008 and 4400), the send path (backpressure 4290 and the heartbeat sweep), encoding, a stateless, Kafka or Redis backplane, and observability. A client connecting over wss with a token and an inject endpoint talk to it; it runs on minikube or OpenShift Local, each with a Redis toggle, and sends traces and metrics to the lgtm stack over OTLP." caption="Figure 28.1: the final project: one contract and one channel, with every concern layered on and two deploy targets." %}

## Stage 1: contract and feed

Both stacks derive their message types from one source. `scripts/extract-message-schema.py` inlines the `$ref`s of `components.schemas.HandlingEvent` (`HandlingEventType`, `Location`, `Money`) into a self-contained `build/handling-event.schema.json`, gitignored and regenerated on every build. Python feeds it to `datamodel-code-generator` to produce `app/models_generated.py`, a Pydantic v2 `HandlingEvent` that `app/feed.py` validates fixtures against and serializes with `model_dump_json(exclude_none=True)`, so an absent optional field never appears as `null` on the wire. Quarkus keeps its `HandlingEvent` record and `HandlingEventType` enum by hand, with the same field and member names, and validates every fixture-derived event against the extracted schema, including that the enum has exactly the contract's 8 members in order.

Neither stack looks up `{bookingId}` at this stage: any value replays the same fixed three-event sequence. What matters is that both push the identical sequence, in the identical order, with the identical optional-field omission. The check compares parsed JSON fields, not raw bytes, because Jackson and Pydantic order object keys differently.

This stage is the floor. A resume, a Protobuf frame, a trace span: none means anything if the two stacks disagree on what a `HandlingEvent` looks like on the wire.

## Stage 2: harden the connection

`examples/part4-connection` forks part 3, keeping the channel and fixture, and adds four concerns a long-lived connection needs: JWT authentication, an error taxonomy, outbound backpressure, and heartbeat liveness. Both stacks use the same close codes:

| Condition | Close | Notes |
|---|---|---|
| Missing, malformed, bad-signature or expired token | `1008` | One outcome for all four, so the close code does not reveal which check failed |
| Frame the server-to-client channel does not accept | `4400` | Preceded by an in-band `{"error":{"code":"BAD_REQUEST",...}}` envelope |
| Sustained outbound overrun | `4290` | The `CLOSE` backpressure policy's default; `DROP` also exists |
| Peer silent past the liveness window | `4408` on Quarkus, `1011` on Python | `1011` is the `websockets` library's own keepalive-failure code |

The two stacks agree on when a silent peer is closed, not on the numeral; `examples/part4-connection/README.md` states that one asymmetry. On Quarkus a dedicated `HeartbeatLivenessSweep` bean tracks `LAST_PONG_AT` and sweeps on its own schedule, because Vert.x's `http.idle-timeout` resets on the server's own outbound ping and never fires against a peer that is silent but being pinged.

A browser's `WebSocket` constructor cannot set an `Authorization` header on the handshake, so the token travels as `?token=`. The cost is a token in URLs and logs; a short TTL and `wss://` keep it tolerable.

## Stage 3: reconnect and the backplane

`examples/part4-backplane` drops the Stage 2 hardening to isolate two questions: what happens when a client disconnects and returns, and what happens when an event must reach a client connected to a different instance. Both turn on the `?afterEventId=<last seen>` resume parameter and on which of three interchangeable `Backplane` implementations is wired in.

- **`stateless`** (the default) has no queue and no log. `publish` fans out to current subscribers and forgets. A client that misses an event and reconnects with `?afterEventId=` gets nothing for that gap, because `replayFor` has nowhere to look.
- **`kafka`** replays the gap event from the shared topic on reconnect, deduped by `eventId`. A narrow documented timing window can deliver that event twice, once in the replay burst and once on the live tail, so a count of 1 or 2 is a pass.
- **`redis`** and `kafka` both answer the second question: an event injected through one instance's `POST /internal/bookings/{bookingId}/handling-events` reaches a client on a different instance. The check confirms the receiving instance's own log shows `delivered eventId=... instance=...`, so the server did the delivering.

Four instances stay up in every mode (`quarkus-a`, `quarkus-b`, `python-a`, `python-b`) because the fan-out check injects through one and observes on the other. This is the broadest single verification run in the project, and the deploy stage builds directly on it.

## Stage 4: encoding

`examples/part5-performance` strips the connection concerns back out so frame size is not confused by anything else on the wire. A client picks its encoding through the `Sec-WebSocket-Protocol` header: `handling-events.v1+json` or bare `handling-events.v1` for JSON text frames (opcode `0x1`), `handling-events.v1+protobuf` for Protobuf binary frames (opcode `0x2`). Both stacks use the same preference order, and JSON wins when nothing is offered, so the JSON-only default of the earlier examples stays the default.

`contracts/handling-event.proto` (package `shipping.handlingevents.v1`) is the binary encoding's source of truth; `contracts/asyncapi.yaml` stays the source of truth for meaning. Keeping them in sync by hand invites drift, so `scripts/check-proto-parity.py` compiles the `.proto` to a `FileDescriptorSet`, parses it with `google.protobuf`, and diffs field names (`lower_snake_case` normalized to `camelCase`), required or optional status, and the `HandlingEventType` membership and order against `build/handling-event.schema.json`. It exits 0 with a one-line summary on a match and exits 1 printing every mismatch otherwise. `buf lint` and `buf breaking` cannot replace it, because neither sees the JSON Schema side of the contract.

The check decodes the Protobuf frame into the same JSON-shaped dict and requires every field value to equal the `+json` frame: one message in two encodings, not two messages that both validate. Protobuf must also be strictly smaller, roughly 40% across all three fixture events (247 to 149 bytes on `RECEIVE`; the per-event table is in `examples/part5-performance/README.md`). A smaller frame that decodes to the wrong values would be a regression dressed as an optimization.

## Stage 5: observability and tests

`examples/part6-observability` turns on what earlier parts leave inert: `quarkus.otel.sdk.disabled` flips to `false`, the Python `Containerfile` entrypoint becomes `opentelemetry-instrument ...`, and the `lgtm` Grafana stack becomes a hard dependency. `opentelemetry-instrumentation-fastapi` traces Python's HTTP side with no code, but there is no `opentelemetry-instrumentation-websockets` and the `websockets` library exposes no OTel hook, so `app/ws_server.py` opens a manual span, `tracer.start_as_current_span("ws.handling-events.connection")`. Quarkus auto-traces the upgrade, so `HandlingEventObservabilityWebSocket#onOpen` adds a `@WithSpan` child under it. Both stacks end up with a same-named span covering the same work, emit one structured log line per connection carrying `otel.trace_id=<32-hex>`, and increment `handling_events_delivered_total` once per event handed off: Micrometer on `/q/metrics` for Quarkus, `prometheus-client` on `:8082/metrics` for Python.

Checks split into HARD and SOFT:

| Kind | What | On failure |
|---|---|---|
| HARD | Trace id in the app's own log line; counter above zero on the app's metrics endpoint | Fails the build |
| SOFT | Poll Tempo's query API for the trace id, 10 attempts at 3 seconds | Logged, never fails the build |

HARD checks hit the app directly, with no external pipeline. SOFT covers a downstream pipeline whose cold-start ingest lag, especially right after `lgtm` starts, is not a fair reason to fail a build.

Two caveats. The Quarkus side has no dedicated health endpoint (no `quarkus-smallrye-health` dependency). And `handling_events_delivered_total` is absent from `/q/metrics` until a WebSocket connection has opened once, because the Micrometer counter lives in a per-connection WebSockets Next bean's `@PostConstruct`.

`examples/part6-testing` covers the other test shape: functional assertions against the HTTP surfaces around the channel. It has no app of its own. Its Newman collection runs against the running `part4-backplane` compose stack, calling both Python instances' `GET /healthz` and both stacks' inject endpoint with valid and malformed bodies. Quarkus returns `202` or `400` (RESTEasy Reactive's default unreadable-entity mapper rejects a bad enum value; the `HandlingEvent` record has no bean validation), and Python returns `202` or `422` (Pydantic v2 names both offending fields in `detail[]`). It is not in CI yet, so it runs by hand.

## Stage 6: deploy

`examples/part4-backplane/k8s` is the deploy target this project reuses: the same four-instance topology behind an ingress-nginx edge, Strimzi managing Kafka, and a Kustomize component (`components/redis-mode`) that flips the `BACKPLANE_MODE` ConfigMap key to Redis.

- **Kafka before the apps.** Quarkus's `quarkus-messaging-kafka` channel is wired unconditionally, and an unresolvable bootstrap hostname is a hard CDI failure at startup. `scripts/install-strimzi.sh` installs the operator, applies the Kafka CR, and blocks on `kubectl wait kafka/my-cluster --for=condition=Ready` before returning.
- **Ingress timeouts.** `proxy-read-timeout` and `proxy-send-timeout` are raised past nginx's 60-second default so an idle socket survives. A 65-second idle hold followed by a late frame proves it.
- **Instance B is not behind the Ingress.** Its inject endpoint is internal, so cross-pod checks use `kubectl exec` into instance A's pod and curl B's cluster-DNS Service name, never `kubectl port-forward`.

The OpenShift Local path carries the same topology through OpenShift mechanisms:

| Concern | minikube | OpenShift Local |
|---|---|---|
| Packaging | Kustomize | Helm chart built for `restricted-v2` (no `runAsUser`; any namespace-range UID with GID 0) |
| Kafka | Upstream Strimzi 1.3.0, Kafka 4.3.1 | AMQ Streams operator, Kafka **4.2.0** |
| Edge | Ingress | Edge-TLS Routes |
| Idle timeout | nginx `proxy-*-timeout` | `haproxy.router.openshift.io/timeout: "3600s"` |

AMQ Streams lags upstream Strimzi: the current channel supports only Kafka 4.1.0 and 4.2.0, so `infra/kafka.yaml` pins 4.2.0. Replay and fan-out behave the same on both minor versions, but the skew is real. The idle-hold check is also weaker on this path: HAProxy's default tunnel timeout is already far longer than nginx's, so the pass confirms the `3600s` annotation is present and the socket survives, not that the annotation moved a real edge. The OpenShift README says this directly.

## Build, run, observe

Run each layer's script from the repository root. Each prints `PASS` on success:

```bash
bash examples/part3-handling-events/verify.sh
bash examples/part4-connection/verify.sh
bash examples/part4-backplane/verify.sh
bash examples/part5-performance/verify.sh
python3 scripts/check-proto-parity.py
bash examples/part6-observability/verify.sh
bash examples/part6-testing/verify.sh
bash examples/part4-backplane/k8s/verify-minikube.sh
bash examples/part4-backplane/openshift/verify-crc.sh
```

Run the two cluster scripts separately, one cluster at a time; minikube and CRC each get their own independent headless proof. Each layer's README documents its prerequisites and ports.

| Capability | Covered in | Example path | Script |
|---|---|---|---|
| Contract-generated feed, both stacks agree field by field | How WebSockets work, the shared domain, AsyncAPI contract | `examples/part3-handling-events` | `verify.sh` |
| JWT auth, error taxonomy, backpressure, heartbeat liveness | Backpressure and flow control, error handling, liveness and heartbeats, security | `examples/part4-connection` | `verify.sh` (plus `k6/smoke.js`, gated in CI) |
| Reconnect resume: stateless gap, Kafka replay, cross-instance fan-out | Reconnect (stateless), reconnect (Kafka-backed), scale-out and fan-out | `examples/part4-backplane` | `verify.sh` |
| Protobuf alongside JSON, parity-gated | Binary Protobuf over WebSockets, optimizing throughput | `examples/part5-performance` | `verify.sh` and `scripts/check-proto-parity.py` |
| Traces, trace id in logs, delivery counter | Observability | `examples/part6-observability` | `verify.sh` |
| Functional HTTP assertions (inject endpoint, health) | Testing WebSockets | `examples/part6-testing` | `verify.sh` (Newman, not yet in CI) |
| Deploy to minikube: Kafka-ready gate, raised ingress timeout, fan-out | Docker Compose, Kubernetes (minikube) | `examples/part4-backplane/k8s` | `verify-minikube.sh` |
| Deploy to OpenShift Local: AMQ Streams, restricted-v2, edge-TLS Routes | OpenShift Local (CRC) appendix | `examples/part4-backplane/openshift` | `verify-crc.sh` |

Notes on what to watch:

- A failed SOFT Tempo check or an unwired Newman run is not a failed stage; a failed HARD check is.
- Stage 3 in `stateless` mode loses the gap event on resume by design; switch to `kafka` and the same reconnect replays it.

> **Decision**
>
> The `handlingEvents` feed is one system, not six. Every isolated concern is a layer on the same channel and the same fixture. Prove assembly with the same `verify.sh` corpus each layer already trusts, run in order, because nothing above Stage 1 changes what Stage 1 guarantees. Carry the same habits to the next feed: start from a contract, gate both stacks against it mechanically (as `scripts/check-proto-parity.py` does) rather than by review, justify the push before paying for reconnect, a backplane and binary framing, and prove each cluster target with a live run, because only a live CRC run surfaces the combined-CA bundle and the router's early pod-ready report.

## For deeper coverage

- *Building Microservices*, 2nd edition, Sam Newman (O'Reilly, 2021): the service-boundary and ownership questions behind where `handlingEvents` lives relative to the booking service it describes.
- *Kubernetes Patterns*, Bilgin Ibryam, Roland Huß (O'Reilly, 2023): the deployment and configuration patterns behind the Kustomize overlays and Helm chart.
- *Cloud Native Design Patterns*, Appendix C, "WebSockets at Scale": the pub/sub backplane and resume-don't-restart posture that `examples/part4-backplane` implements once per stack.
- AsyncAPI 3.0 specification, `asyncapi.com/docs/reference/specification/v3.0.0`: the document shape `contracts/asyncapi.yaml` is written against.
- RFC 6455, The WebSocket Protocol, `datatracker.ietf.org/doc/html/rfc6455`: the opcode, close-code, and handshake mechanics every stage verifies against.
