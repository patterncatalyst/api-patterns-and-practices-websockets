---
title: "Testing WebSockets"
order: 21
part: "Testing, Debugging & Observability"
description: "Five test layers for a protocol you can't curl: conformance, live integration, close-code probes, Newman and k6."
duration: "20 min read"
---

## Learning objectives

By the end of this chapter you can:

- Write conformance tests that validate a frame against `build/handling-event.schema.json` with no socket and no container.
- Drive live integration checks with the shared `lib.sh` helpers (`ws_first_frame`, `ws_connect_bg`, `assert_ws_rejected`, `wait_for_log_count`) against real `docker compose` containers.
- Read a close code that `websocat` can't see, using a Python `websockets` probe, and assert on values like 4400 and 4290.
- Scope Newman to the plain-HTTP seams around a WebSocket-only contract, and k6 to connection load split between a gated smoke check and a local benchmark.
- Keep every test layer pointed at one contract-derived schema with a CI drift gate.

## Why this matters

`curl` proves an HTTP endpoint exists with one request and one response, and most web test tooling assumes that shape. A WebSocket channel has an upgrade handshake, a sequence of pushed frames and a close code that may or may not carry meaning. Here it also has one contract implemented twice, in Quarkus and in Python, which has to agree with itself as much as with `contracts/asyncapi.yaml`.

Five kinds of test cover that shape:

| Layer | Opens a socket | Sees | Blind to |
|---|---|---|---|
| Unit and conformance | No | Schema shape, enum parity, Protobuf round trip and value parity, wire size | Anything over a live connection |
| Live integration (`verify.sh` and `lib.sh`) | Yes, via `websocat` | Frame contents, reconnect and resume, fan-out, idle behavior | Close codes |
| Close-code probe | Yes, via Python `websockets` | Exact close code, error envelope, frame count before close | Everything the other layers cover |
| Newman | HTTP only | Health and inject endpoints | The WebSocket channel |
| k6 | Yes | Connect success, frame shape, bytes per frame, negotiation | Field-level correctness |

{% include excalidraw.html file="21-test-pyramid" alt="A pyramid of four tiers, narrowest at the top: load (k6 smoke gated, benchmark local only), functional (Newman plus the Python close-code probe), live integration (verify.sh plus lib.sh on both stacks), and unit and conformance (no socket, no container, runs in milliseconds). Beneath it, the contract drift gate regenerates the schema and reruns every layer that reads it." caption="Figure 21.1: the WebSocket test pyramid, narrower and slower toward the top, all gated on the same contract-derived schema." %}

## Unit and conformance: the shape without a socket

The cheapest tests never touch a network. Every Python example ships `tests/test_contract.py`, and every Quarkus example ships `HandlingEventContractTest`: plain JUnit, not `@QuarkusTest`, because neither needs the endpoint running. Both load the same fixture (`fixtures/handling-events.json`) and validate every emitted frame against `build/handling-event.schema.json`, the self-contained JSON Schema that `scripts/extract-message-schema.py` extracts from `contracts/asyncapi.yaml`. Both also check that `HandlingEventType` carries exactly the contract's eight enum members, in order. A schema mismatch or a missing member fails at test time, not when someone notices a bad frame in production.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    @Test
    void fixtureEventsValidateAgainstContractSchema() {
        List<HandlingEvent> events = loadFixtureEvents();
        assertFalse(events.isEmpty(), "fixture must contain at least one event");

        for (HandlingEvent event : events) {
            JsonNode node = MAPPER.valueToTree(event);
            Set<ValidationMessage> errors = schema.validate(node);
            assertTrue(errors.isEmpty(),
                    () -> "schema violations for " + event.eventId() + ": " + errors);
        }
    }

    @Test
    void firstFixtureEventIsTheReceiveEvent() {
        HandlingEvent first = loadFixtureEvents().get(0);
        assertEquals(HandlingEventType.RECEIVE, first.eventType());
        assertEquals("evt_01HZY3M1V8X4D7Q6B2N9C0T5E8", first.eventId());
        assertEquals("bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A", first.bookingId());
    }
```
```python
def test_emitted_frames_validate_against_schema(validator: Draft202012Validator) -> None:
    frames = sequence_as_json()
    assert len(frames) == 3
    for frame in frames:
        doc = json.loads(frame)
        errors = list(validator.iter_errors(doc))
        assert not errors, f"{frame} failed schema validation: {errors}"


def test_first_frame_is_the_receive_event_matching_the_fixture() -> None:
    fixture = load_fixture()
    frames = sequence_as_json()
    first = json.loads(frames[0])
    assert first == fixture[0]
    assert first["eventType"] == "RECEIVE"
```

The two stacks assert the same things side by side: the same fixture, the same extracted schema, the same first-event identifiers. A reviewer can see whether they still agree on "what a conformant frame looks like" without running either.

The Protobuf example adds a second pass. It drives each fixture event through Protobuf (model to proto, to bytes, back to proto, back to a value) and checks that the result validates against the same schema the JSON path uses and equals the JSON value field for field, not merely "a valid shape". It also checks that the Protobuf frame is smaller than the JSON frame, the unit-level half of the wire-size claim, proven in milliseconds before any load run.

Later examples fork the conformance tests without losing that floor. The connection example adds socket-free unit tests for token validation and the error-envelope shape. The backplane example tests the stateless backplane's in-process fan-out against `asyncio.Queue` directly, with no broker. The observability example checks a trace-id log line and a Prometheus counter increment with no collector running. Every fork keeps the schema-conformance tests at the top, because every example replays the same fixture against the same contract.

## Live integration: verify.sh and lib.sh

Unit tests prove the model serializes. They say nothing about whether the process on the port sends it over a wire. `examples/_lib/lib.sh` is the shared harness that every `verify.sh` sources to answer that against containers `docker compose up --build` starts fresh each run.

| Helper | Does |
|---|---|
| `wait_for_ws` | Polls until a real WebSocket upgrade succeeds |
| `wait_for_tcp` | Polls a port for brokers that speak neither WebSocket nor HTTP |
| `ws_first_frame`, `ws_frames_n` | Connect, read exactly one or N frames, print them |
| `ws_connect_bg` | Hold a background connection, append every frame to a logfile, return a PID |
| `assert_ws_rejected` | Prove a connection attempt was refused |
| `ws_idle_hold` | Hold a connection open without sending, to observe heartbeat and idle timeouts |
| `wait_for_log_pattern`, `wait_for_log_count` | Poll a file for a line once, or a specific number of times |
| `schema_validate`, `json_field` | Apply the same JSON Schema to frames that came off a live socket |

The harness needs only Docker and Python. `ensure_websocat` and `ensure_protoc` download pinned binaries into a cached `.bin` directory on first use. `schema_validate` prefers a `jsonschema` already on `PATH`, falls back to an ephemeral `uv run --with jsonschema`, and uses a minimal hand-rolled validator (not full Draft 2020-12) only if neither is available.

Every `verify.sh` starts with the same Step 0: `python3 -I scripts/extract-message-schema.py build/handling-event.schema.json`. That keeps the unit and integration layers reading the same schema file instead of two copies that can drift. A script that skipped it would still pass today and return stale results the moment the contract changed.

Three scripts show how far the vocabulary stretches:

- **Baseline (handling events).** Bring up both stacks, capture each first frame with `ws_first_frame`, schema-validate it and compare it to the fixture's `RECEIVE` event field by field. Then compare the two stacks against each other, because a schema permits a range of valid values and two correct implementations can still diverge inside it. A reconnect step starts the Python reference client, forces `docker compose restart python`, and uses `wait_for_log_count`, not `wait_for_log_pattern` again, to assert a second "received CUSTOMS" line, which proves the client resumed rather than retrying once and giving up.
- **Connection concerns.** Auth mints one shared-secret JWT and replays it against both stacks: valid, expired, bad signature and garbage, each asserted with `assert_ws_rejected`. Backpressure runs one-off containers with the threshold forced to trip on the first fixture burst: `EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0` on Quarkus and `OUTBOUND_QUEUE_MAXSIZE=1` on Python, because Python's bounded queue treats `maxsize<=0` as unbounded. Heartbeat containers force a short detection window (`EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT=5s` and `EXAMPLE_HEARTBEAT_SWEEP_INTERVAL=1s` on Quarkus, `WS_PING_TIMEOUT_S=3` on Python) and wait up to 25 seconds for a detection path that takes about 16, a margin for a slow CI host that doesn't turn the wait into a timeout test.
- **Backplane.** Four app instances (`quarkus-a`, `quarkus-b`, `python-a`, `python-b`) run through three compose lifecycles: default stateless, `--profile kafka` and `--profile redis`. Each scenario generates a fresh booking id with `gen_id`, so replay and fan-out checks never cross-contaminate on the shared topic. A `BG_PIDS` array and one `cleanup_all` trap kill every background client on exit, so a mid-scenario failure leaks no `websocat` process. The stages show that stateless mode loses a gap-era event, Kafka mode replays it after reconnect (deduplicated by `eventId`; a rare duplicate from the replay and live race is the accepted cost of at-least-once delivery), and a scale-out event crosses instances over both brokers. The fan-out is asserted from the client's received frame and from instance A's own log line naming itself as the deliverer.

## What websocat can't see: close codes

`websocat` is the right tool for nearly everything in `lib.sh`. It can't read the close code a server sent. A client that completes the 101 handshake and then receives a policy-violation close exits 0, which an exit code alone can't tell from a connection the server means to keep open. `assert_ws_rejected` sidesteps this for auth by checking whether any frame arrived (it omits websocat's exit-on-EOF flag, which would tear down the read side before a server-sent frame could arrive). That proves only that nothing came through. It can't name the code, and the error taxonomy and backpressure policy depend on specific numbers: 4400 for a malformed client frame, 4290 for a backpressure overrun, 1008 for rejected auth.

`ws_close_probe` uses Python's `websockets` library instead, fetched into an ephemeral `uv run --with websockets` environment. The library exposes `ws.close_code` after the connection closes. The probe sends one optional payload, counts the frames it drains, catches `ConnectionClosed` (which `websockets` 17 raises out of the `async for` loop and would otherwise lose the code with it) and prints one line of JSON: frame count, whether a `BAD_REQUEST` envelope arrived, and the numeric code. The error step asserts 4400 from it, and the backpressure step asserts 4290.

A third probe goes lower still for heartbeat liveness. It hand-writes the opening handshake over a bare socket, confirms the 101, then sends nothing. Both websocat and `websockets` answer pings automatically at the protocol level and can never manufacture a silent peer. Each tool is the minimum client that can observe its signal: `websocat` for content, `websockets` for close codes, a bare socket for a peer that answers nothing.

{% include excalidraw.html file="21-layer-visibility" alt="Five boxes show what each test layer can and can't observe. Unit and conformance sees schema shape and value parity but nothing over a live connection. Live integration via websocat sees frame contents, reconnect and fan-out but not close codes. The Python close-code probe sees exact close codes and the error envelope. Newman sees the HTTP seam but not the WebSocket channel. k6 sees connect success and bytes per frame, with the smoke check gated and the benchmark local only." caption="Figure 21.2: what each of the five test layers can and can't observe about a live WebSocket connection." %}

## Functional HTTP around the socket: Newman

The contract is WebSocket-only, but the apps around it are not. `/healthz` probes and the backplane example's `POST /internal/bookings/{bookingId}/handling-events` inject endpoint, which the gap, replay and fan-out scenarios depend on, are plain HTTP, and plain HTTP has a mature functional-test tool. The split is by shape: k6 for sustained-connection load against the WebSocket channel, Newman (Postman's CLI runner) for REST-shaped seams. The Newman example has no application of its own; its collection runs against the backplane example's compose stack, the richest HTTP surface in the repo.

The six requests carry twelve assertions:

| Request | Target | Expected |
|---|---|---|
| `GET /healthz` | Both Python instances | `200`, body exactly `{"status":"ok"}` |
| Inject, schema-valid body | Quarkus | `202` |
| Inject, malformed `eventType` | Quarkus | `400` |
| Inject, schema-valid body | Python | `202`, body echoes `status`, `eventId`, `bookingId` |
| Inject, bad `bookingId` pattern and bad `eventType` | Python | `422`, `detail[]` names both fields |

The Quarkus record has no bean validation, so only Jackson's enum deserialization, surfaced through RESTEasy Reactive's unreadable-entity mapper, rejects the malformed body. Pydantic v2 validates the pattern and the enum independently, so the collection checks both offending fields rather than the status alone; a regression that dropped one violation would otherwise pass. The runner is a pinned `npx newman@6.2.3` rather than the `docker.io/postman/newman` image, because no image tag newer than 6.1.3 exists and the project upgrades the tool instead of downgrading the pin.

The observability example's HTTP surface (`/q/metrics` on Quarkus, a Prometheus endpoint on Python) is outside this collection. The `handling_events_delivered_total` counter is registered in a `@PostConstruct` on a per-connection WebSockets Next bean, so it is absent from `/q/metrics` until a connection has opened once. A Newman request before any socket connects would prove nothing about the metric. That example's own `verify.sh` drives the connection and scrapes the result, which keeps "functional HTTP" from blurring into "HTTP plus WebSocket plus the observability stack".

## Load and the drift gate

k6 splits two ways. `smoke.js` exists for the connection, backplane and performance examples, and the `k6-smoke` CI job runs it against all of them: the connection example's two stacks each on their own port with a freshly minted token, the backplane's default-profile `quarkus-a` and `python-a` with no auth, and both performance stacks over both negotiated subprotocols in one iteration. It checks that JSON frames arrive as `message` events and Protobuf frames as `binaryMessage` events without decoding either; decoding belongs to `verify.sh` against a generated stub. Its `thresholds: { checks: ["rate==1.0"] }` fails the PR on any failed check. `benchmark.js` is cited in prose and never asserted, because one script measured 100% connect success on a fresh container and single digits after the host's ephemeral port range filled.

A deterministic assertion (schema pass, close code, assertion count, `rate==1.0`) belongs in a gate. A timing-sensitive number (heartbeat detection window, idle-hold duration, raw connects per second) gets a generous bound or stays in prose.

Two CI jobs keep the layers on one contract:

- **`drift`** loops over `DRIFT_APPS` (the handling-events, connection, backplane and performance examples). For each it regenerates `build/handling-event.schema.json` from `contracts/asyncapi.yaml`, regenerates the Python model and, where present, the Protobuf stub, runs `pytest tests/test_contract.py`, and runs the Quarkus conformance tests against the fresh schema. A contract change that breaks any app's model or assumptions fails every affected app in one pass. A new app is added to one list, not four near-duplicate step blocks.
- **`buf lint/build/breaking` plus AsyncAPI-to-proto parity** covers what `drift` can't: nothing there looks at `contracts/handling-event.proto` in isolation, so a field renamed on only one half of the contract would pass every app's tests as long as each app checks only its own half. `scripts/check-proto-parity.py` diffs the compiled proto descriptor against the same extracted schema, and it always runs, even when `buf breaking` has no baseline yet. It sits one level below the round-trip tests: those prove one app's generated code round-trips against its schema, and this proves the two contract source files never drifted apart before any code generation ran.

The `examples` matrix job discovers every `examples/*/verify.sh`, runs each with up to three retries under a 45-minute cap sized for the backplane's three stages, sets `fail-fast: false` so one failure doesn't cancel the rest, and gates the PR on all of them, alongside the always-gated `k6-smoke` job.

> **Decision**
>
> Test a WebSocket channel in five layers. Conformance tests validate shape and round-trip values with no socket. `verify.sh` with `lib.sh` proves frame contents, reconnect and fan-out against real containers. A `websockets` probe reads the close codes `websocat` can't. Newman covers the HTTP seams, and k6 splits into a gated `smoke.js` and a local `benchmark.js`. Gate only deterministic assertions, and let the `drift` job tie every layer to the schema extracted from `contracts/asyncapi.yaml`.

> **🤖 Explore with your agent**
>
> "In `examples/part4-connection/verify.sh`, the auth checks use `assert_ws_rejected`, which proves only that no frame arrived. Add a `ws_close_probe` call that sends an expired token to the Quarkus (`:8080`) and Python (`:8081`) channels and asserts close code 1008, the same way the error-taxonomy step asserts 4400. Then sort every existing assertion in the script into one of the five layers (conformance, `lib.sh`, close-code probe, Newman, k6) and name any timing-sensitive one that should get a generous bound instead of a gate."
>
> Check: `./verify.sh` still prints `PASS`, and the new step prints the numeric close code 1008 for each stack.

## Build, run, observe

```bash
cd examples/part6-testing
./verify.sh
```

`verify.sh` brings up the backplane example's default-profile compose stack (no Kafka or Redis needed), waits for the Python `:8082` health endpoint and the Quarkus `:8080` listener, runs the Newman collection and tears the stack down. It prints `PASS` when Newman exits 0. A JSON run report lands in `newman/reports/` (gitignored, regenerated every run) with the tally: 6 requests, 12 assertions, 0 failed.

To run the collection against a stack you started by hand, skipping the compose lifecycle:

```bash
npx newman@6.2.3 run newman/collection.json -e newman/environment.json
```

Experiment: remove Step 0 from a `verify.sh`. It still passes today, then returns stale results as soon as the contract changes underneath it.

## For deeper coverage

- Sam Newman, *Building Microservices*, 2nd ed. (O'Reilly, 2021): testing strategy across independently-deployable services, the same shape as two independently built stacks implementing one contract.
- *Cloud Native Design Patterns*, "API Testing with Newman" chapter: the Newman-collection pattern, scoped here to the plain-HTTP seams around a WebSocket-only contract.
- *Cloud Native Design Patterns*, "Anti-Patterns" chapter: the companion catalogue of testing and operational anti-patterns.
- [Python `websockets` library documentation](https://websockets.readthedocs.io/en/stable/): the `close_code` attribute and connection API the close-code probe depends on.
- [Quarkus: Testing Your Application](https://quarkus.io/guides/getting-started-testing): the JUnit-based testing model behind the plain-JUnit conformance tests.
