---
title: "Testing WebSockets"
order: 21
part: "Testing, Debugging & Observability"
description: "Testing a protocol you can't curl — connection lifecycle, message assertions, and both stacks' test harnesses."
duration: "20 min read"
---

## Learning objectives

By the end of this chapter you can:

- Write unit/conformance tests (`test_contract.py`, `HandlingEventContractTest`) that validate a frame against `build/handling-event.schema.json` with no socket and no container.
- Drive live integration checks with `examples/_lib/lib.sh`'s shared vocabulary (`ws_first_frame`, `ws_connect_bg`, `assert_ws_rejected`, `wait_for_log_count`) against real `docker compose` containers.
- Read a close code a `websocat`-based probe can't see, using the `ws_close_probe` Python helper's `ws.close_code`, and assert on values like `4400`/`4290`.
- Scope Newman to the plain-HTTP seams around a WebSocket-only contract and `k6` to connection load, per the DRQ-006 split between `smoke.js` (gated) and `benchmark.js` (local-only).
- Explain how the `drift` CI job and `scripts/check-proto-parity.py` keep every test layer pointed at the same contract-derived schema.

## Why this matters

Every chapter from Part 3 forward has ended the same way: a `verify.sh` runs, a schema validates, a PASS line prints. This chapter is where that recurring machinery finally gets named and explained as a system, rather than cited piecemeal chapter by chapter. The problem it solves is specific to this protocol: `curl` proves an HTTP endpoint exists by making one request and reading one response, and most test tooling built for the web assumes that shape. A WebSocket channel has no single request/response to curl — it has an upgrade handshake, a sequence of pushed frames, a close code that may or may not carry meaning, and in this site's case an identical contract implemented twice, in Quarkus and in Python, that has to agree with itself as much as with `contracts/asyncapi.yaml`. Five distinct kinds of test already exist in this repo to cover that shape: schema and proto conformance tests that never open a socket, `verify.sh`/`lib.sh` integration tests that open real sockets against real containers, a Python close-code probe for the one signal `websocat` can't read, a Newman collection for the plain HTTP seams sitting next to the WebSocket channel, and k6 for load — one gated, one not. None of this is new code; it is the existing corpus, finally walked end to end.

## Unit and conformance: proving the shape without a socket

The cheapest tests in this repo never touch a network. Every Python example ships a `tests/test_contract.py`, and every Quarkus example ships a `HandlingEventContractTest` — plain JUnit, not `@QuarkusTest`, because neither test needs the WebSocket endpoint running; both exercise serialization of the production model types directly. `test_fixture_is_three_events_in_order` and `test_emitted_frames_validate_against_schema` on the Python side, `fixtureEventsValidateAgainstContractSchema` and `firstFixtureEventIsTheReceiveEvent` on the Quarkus side, both load the same classpath fixture (`fixtures/handling-events.json`, copied onto Quarkus's test classpath by a Maven execution, imported directly by Python) and validate every emitted frame against `build/handling-event.schema.json` — the self-contained JSON Schema `scripts/extract-message-schema.py` extracts from `contracts/asyncapi.yaml`. Both also assert `HandlingEventType` carries exactly the contract's eight enum members, in order, on both stacks: a schema violation or a missing enum member fails the test the moment it happens, not the moment someone notices a frame looks wrong in production.

{% include codetabs.html langs="Quarkus|Python" %}

```java
// examples/part3-handling-events/quarkus/src/test/java/.../HandlingEventContractTest.java
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
# examples/part3-handling-events/python/tests/test_contract.py
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

The two tests read almost like a translation exercise, and that is the point: `loadFixtureEvents()`/`load_fixture()` read the identical classpath/package fixture, `schema.validate(node)`/`validator.iter_errors(doc)` both walk the identical extracted `build/handling-event.schema.json`, and both assert the identical fixture identifiers — `evt_01HZY3M1V8X4D7Q6B2N9C0T5E8`, `bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A` — on the first emitted event. A reviewer checking whether the two stacks still agree on "what a conformant frame looks like" does not need to run either suite to see the answer; the two method bodies say it side by side.

{% include excalidraw.html file="21-test-pyramid" alt="A pyramid of stacked tiers, narrowest at the top. Top tier: Load, k6, smoke.js gated, benchmark.js local-only. Second tier: Functional, two tools in one tier, Newman plus the python close-code probe, 12 assertions zero failed, the HTTP seam plus close codes websocat cannot read. Third, widest accent box: Live integration, verify.sh plus lib.sh, both stacks, real containers, ws_first_frame, ws_frames_n, ws_connect_bg, assert_ws_rejected, wait_for_log_count, docker compose up, assert, compose down. Fourth, widest box: Unit and conformance, pytest test_contract.py plus Quarkus HandlingEventContractTest, schema_validate against build slash handling-event.schema.json, proto round trip HandlingEventProtoRoundTripTest, no socket, no container, runs in milliseconds. Below the pyramid, a light ink emphasis box reads the contract-drift gate, regenerate the schema, re-run every layer that reads it, on every change to contracts slash asyncapi.yaml. A ghost caption notes Ch21, Ch22 and Ch24 are prose citing this existing corpus, only Ch23 adds new runnable code." caption="Figure 21.1 — the WebSocket test pyramid: five tools across four tiers, narrower and slower toward the top, all gated on the same contract-derived schema." %}

Part 5's fork of this test adds a second conformance pass without replacing the first. `examples/part5-performance/python/tests/test_contract.py`'s `test_proto_round_trip_matches_schema_and_json_values` and the Quarkus sibling `HandlingEventProtoRoundTripTest.everyFixtureEventRoundTripsThroughProtobufUnchanged` both drive the same fixture through Protobuf — model to proto, proto to bytes, bytes back to proto, proto back to a value — and assert two things a plain "it parsed" check would miss: the round-tripped value validates against the identical schema the JSON path validates against, and it equals the JSON path's value field-for-field, not merely "a valid shape." A third assertion, `protobufFrameIsSmallerThanTheEquivalentJsonFrame`/`test_proto_wire_bytes_are_smaller_than_the_equivalent_json_frame`, is the unit-level half of Chapter 19's headline claim — proven on every fixture event, in milliseconds, long before a k6 run ever touches the network to confirm it holds under load too.

{% include codetabs.html langs="Quarkus|Python" %}

```java
// examples/part5-performance/quarkus/src/test/java/.../HandlingEventProtoRoundTripTest.java
@Test
void everyFixtureEventRoundTripsThroughProtobufUnchanged() throws InvalidProtocolBufferException {
    List<HandlingEvent> events = HandlingEventContractTest.loadFixtureEvents();
    assertFalse(events.isEmpty(), "fixture must contain at least one event");

    for (HandlingEvent original : events) {
        byte[] protoBytes = HandlingEventProtoMapper.toProto(original).toByteArray();
        HandlingEventOuterClass.HandlingEvent parsed =
                HandlingEventOuterClass.HandlingEvent.parseFrom(protoBytes);
        HandlingEvent roundTripped = HandlingEventProtoMapper.fromProto(parsed);

        assertEquals(original, roundTripped,
                () -> "proto round trip changed " + original.eventId());
    }
}
```
```python
# examples/part5-performance/python/tests/test_contract.py
def test_proto_round_trip_matches_schema_and_json_values(
    validator: Draft202012Validator,
) -> None:
    for event in sequence():
        proto = to_proto(event)
        wire_bytes = proto.SerializeToString()

        decoded = HandlingEventProto()
        decoded.ParseFromString(wire_bytes)
        decoded_dict = proto_to_dict(decoded)

        errors = list(validator.iter_errors(decoded_dict))
        assert not errors, f"{decoded_dict} failed schema validation: {errors}"

        json_dict = json.loads(event.model_dump_json(exclude_none=True))
        assert decoded_dict == json_dict, (
            f"proto round-trip drift for {json_dict['eventId']}: "
            f"{decoded_dict} != {json_dict}"
        )
```

Later parts fork this suite further without losing the floor it sets. `part4-connection`'s `test_contract.py` adds pure-Python unit tests for `app/auth.py` (`test_validate_token_rejects_an_expired_token`, `test_validate_token_rejects_a_bad_signature`, no socket) and for the Ch13 error-envelope shape; `part4-backplane`'s adds unit tests for the `StatelessBackplane`'s in-process fan-out, run against `asyncio.Queue` directly rather than a live broker; `part6-observability`'s adds a regex-matched trace-id log-line assertion and a Prometheus counter increment check, both exercised with no OTLP collector running at all. Every fork keeps the same four schema-conformance tests at the top of the file — `test_fixture_is_three_events_in_order` through `test_sequence_events_validate_as_generated_model_instances` — because every one of these examples still replays the identical fixture against the identical contract; forking the test file is cheap, and losing that shared floor by accident is exactly the kind of drift this layer exists to catch first.

## Live integration: verify.sh and lib.sh against real containers

Unit tests prove the model serializes correctly; they say nothing about whether the thing listening on a port sends that model over a wire at all. `examples/_lib/lib.sh` is the shared harness every example's `verify.sh` sources to answer that question live, against containers `docker compose up --build` brings up fresh each run. Its vocabulary is narrow and specific: `wait_for_ws` polls a host:port/path until a real WebSocket upgrade succeeds; `ws_first_frame` and `ws_frames_n` connect, read exactly one or exactly N frames, and print them for the caller to assert on; `ws_connect_bg` opens a long-lived background connection and appends every frame it receives to a logfile, returning a PID the caller kills when done; `assert_ws_rejected` proves a connection attempt was refused; `ws_idle_hold` holds a connection open without sending anything, to observe heartbeat and idle-timeout behavior; `wait_for_log_pattern`/`wait_for_log_count` poll a file for a line to appear once, or a specific number of times. `schema_validate` and `json_field` round out the set — the same JSON Schema the unit tests validate against, now applied to frames that came off a live socket.

None of that vocabulary requires a CI runner to pre-install anything beyond Docker and Python. `lib.sh`'s `ensure_websocat` and `ensure_protoc` download a pinned binary (websocat 1.14.1, protoc 36.2 — the same Ch0 version-matrix pins every other chapter cites) into a cached `.bin` directory on first use, the identical philosophy `schema_validate` falls back to for `jsonschema` itself: prefer whatever is already on `PATH`, fall back to an ephemeral `uv run --with jsonschema` install, and only reach for a hand-rolled minimal validator — covering `type`, `required`, `enum`, and a handful of string/number constraints, explicitly not a full Draft 2020-12 implementation — if neither is available. A `verify.sh` that needs `websocat` to exist never requires a separate CI workflow step to install it; the first call to `wait_for_ws` or `ws_first_frame` provisions it, the same way the example apps' own Dockerfiles provision their runtimes.

Every `verify.sh` this corpus ships starts with the identical Step 0: `python3 -I scripts/extract-message-schema.py build/handling-event.schema.json`, the same extraction `test_contract.py` and `HandlingEventContractTest` both depend on, regenerated fresh before a single container comes up. That shared first step is what keeps the unit layer and the integration layer pointed at the same schema file rather than two copies that could drift apart without either side noticing — a `verify.sh` that skipped it would still pass today and start lying the moment the contract changed underneath it, with no fresh extraction left to catch the gap.

Four `verify.sh` scripts show how far that shared vocabulary stretches. `part3-handling-events/verify.sh` is the baseline: bring up both stacks, capture each one's first frame with `ws_first_frame`, schema-validate it, assert it matches the fixture's known `RECEIVE` event field-by-field, then cross-check the two stacks' frames against *each other* — not against a shared expectation twice, but against one another directly, because a schema permits a range of valid values and two independently correct implementations could still diverge inside that range. Its Step 4 goes further: it starts the real Python reference client (`uv run --project clients/python python -m app.client`) against the Python server, waits for `wait_for_log_pattern` to see "received CUSTOMS," forces a `docker compose restart python`, waits for a logged reconnect attempt, then uses `wait_for_log_count` — not `wait_for_log_pattern` again — to assert a *second* "received CUSTOMS" line, proving the client resumed receiving after the forced disconnect rather than merely retrying once and giving up.

`part4-connection/verify.sh` layers four connection concerns onto that baseline, each with its own determinism story. Auth (Ch17) mints a shared-secret JWT with `uv run --with pyjwt` once and reuses it against both stacks — valid, expired, bad-signature, and garbage-token cases, each asserted with `assert_ws_rejected`. Backpressure (Ch12) runs *one-off containers* with the threshold forced to the smallest value that trips deterministically on the very first fixture burst — `EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0` on Quarkus (0 pending trips before anything sends, confirmed in that guard's own Javadoc), `OUTBOUND_QUEUE_MAXSIZE=1` on Python, because Python's bounded queue treats `maxsize<=0` as *unbounded* — the opposite of the "0 is most deterministic" assumption a naive reading would make. Heartbeats (Ch14) run their own one-off containers with the detection window forced short — `EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT=5s`/`EXAMPLE_HEARTBEAT_SWEEP_INTERVAL=1s` on Quarkus, `WS_PING_TIMEOUT_S=3` on Python — and budget a generous 25-second wait for a detection path the script's own comment clocks at roughly 16 seconds observed live, comfortable margin for a slower CI host without the wait becoming a de facto timeout test.

`part4-backplane/verify.sh` is the richest harness in the corpus: it brings up four app instances every time (`quarkus-a`/`quarkus-b`/`python-a`/`python-b`) and runs three full compose lifecycles in sequence — default/stateless, `--profile kafka`, `--profile redis` — each stage generating its own fresh bookingId per scenario (`gen_id`) so that Kafka-replay and fan-out proofs never cross-contaminate on the one shared broker topic every instance reads. The broker stages reach for a helper the earlier scripts never need: `wait_for_tcp localhost 9092 90` for Kafka, `wait_for_tcp localhost 6379 60` for Redis, because neither broker speaks WebSocket or HTTP and `wait_for_ws` has nothing to poll. A `BG_PIDS` array tracks every `ws_connect_bg` background client this script opens across all three stages, so the single `cleanup_all` trap can kill and reap every one of them on the way out — a failure mid-scenario never leaks a background `websocat` process the way a per-scenario `kill` alone might if the script exited before reaching it. The three stages together prove Ch15's stateless mode drops a gap-era event with no record of it ever existing, Ch16's Kafka mode replays that event after reconnect (deduped by `eventId`, a documented benign at-most-2 replay/live race accepted as a known tradeoff rather than treated as a bug), and Ch18's fan-out crosses instances over both brokers, asserted both from the *client's* received frame and from instance A's own server log line naming itself as the deliverer.

## What websocat can't see: close codes and the python probe

`websocat` is the right tool for almost everything `lib.sh` does — it is what `wait_for_ws`, `ws_first_frame`, `ws_frames_n`, and `ws_connect_bg` all shell out to. It is the wrong tool for exactly one thing this chapter's error and backpressure tests both need: reading the WebSocket close *code* a server sent. `part4-connection/verify.sh`'s own comment on `ws_close_probe` is explicit about why a naive exit-code check would be a real, not theoretical, bug: a client that completes the 101 handshake and then receives a policy-violation close frame exits 0 — indistinguishable by exit code alone from a connection the server intends to keep open. `assert_ws_rejected` sidesteps this for the auth case by checking whether *any* frame arrived at all — it leaves out websocat's `-E`/exit-on-eof flag, because that flag would tear down the read side before a server-sent frame had a chance to arrive — but that trick only proves "nothing came through"; it can't name *which* numbered close code closed the connection, and Chapter 13's error taxonomy and Chapter 12's backpressure policy both hinge on specific numbers: 4400 for a malformed client frame, 4290 for a backpressure overrun, 1008 for a rejected auth attempt.

`ws_close_probe` closes that gap by reaching for a different client entirely: Python's `websockets` library, fetched into an ephemeral `uv run --with websockets` venv, connected directly rather than through websocat. `websockets` exposes `ws.close_code` as a first-class attribute after the connection closes — exactly the thing websocat has no equivalent flag for — so the probe sends one optional payload, drains every frame into a count, catches the library's own `ConnectionClosed` exception (needed because `websockets` 17.x raises it *out of* the `async for` loop rather than ending it quietly, which would otherwise lose `close_code` along with the exception), and prints one line of JSON: frame count, whether a `BAD_REQUEST` envelope was seen, and the numeric close code. `run_stack_auth_and_error_tests` reads that JSON straight into `assert_eq "4400" "$close_code"`; the Ch12 backpressure step reads the same shape for `4290`. A third probe, `raw_silent_client_close_wait`, goes one layer lower still for Chapter 14's heartbeat check: it hand-writes the WebSocket opening handshake over a bare `socket` — no WebSocket library at all, spec-compliant or otherwise — confirms the 101 response, and then sends *nothing* for the rest of its run, because both websocat and the `websockets` library answer ping frames automatically at the protocol level and can never manufacture a truly silent peer. Three tools, three tiers of protocol awareness, each chosen because it is the minimum client capable of observing the one signal that step needs: `websocat` for content, `websockets` for close codes, a bare socket for a peer that answers nothing at all.

{% include excalidraw.html file="21-layer-visibility" alt="Five boxes in a grid. Unit and conformance: no socket, sees schema shape, enum parity, proto JSON value parity, wire size assertion, blind to anything over a live connection. Live integration, accent box: websocat via lib.sh, sees frame contents, field semantics, reconnect and resume, fan-out, idle-hold, blind to close codes, exit code alone cannot tell rejected from accepted and still open. Functional close-code probe: python plus websockets library, sees exact close_code 4400, 4290, 1008, the BAD_REQUEST envelope, frame count before close, because the websockets library exposes ws.close_code and websocat has no equivalent. Functional HTTP, Newman: sees the HTTP seam around the socket, healthz, inject endpoint 202 400 422, 12 assertions zero failed, blind to the WebSocket channel itself since the contract is WS only. Load, k6 smoke gated: sees connect success, 3-frame shape, p95 session time, deterministic rate equals 1.0 threshold fails the PR. Load, k6 benchmark local-only: sees bytes per frame, connects per second, negotiation outcome, timing-sensitive, connects per second moves with host ephemeral-port state, never cited as a bare number. Below, a light ink emphasis box: deterministic across every run is schema validation, round-trips, close codes, frame field values, negotiation yes or no; timing-sensitive is idle-hold windows, heartbeat detection delay, raw connects per second, bounded, never asserted exactly. A ghost caption reads each layer's blind spot is why the next layer up exists, none of the five alone proves the channel correct." caption="Figure 21.2 — what each of the five test layers can and can't observe about a live WebSocket connection." %}

## Functional HTTP around the socket: Newman and the DRQ-006 split

`contracts/asyncapi.yaml` is WebSocket-only, but the example apps around it are not — `/healthz` liveness probes, and `part4-backplane`'s `POST /internal/bookings/{% raw %}{bookingId}{% endraw %}/handling-events` inject endpoint that every gap/replay/fan-out scenario above depends on, are plain HTTP, and plain HTTP has a mature, purpose-built functional-test tool that nothing in `lib.sh` needs to reinvent. DRQ-006 splits this site's test tooling by shape: k6 for sustained-connection load against the WebSocket channel, Newman — Postman's CLI runner — for functional assertions against REST-shaped HTTP seams. `examples/part6-testing` is that Newman example (DRQ-030), and it has no application of its own: `newman/collection.json` runs against `part4-backplane`'s already-existing compose stack, the richest HTTP surface in the repo.

The collection's six requests carry twelve assertions, captured in `newman/reports/newman-report.json` at `0` failed every time it has run: `GET /healthz` on both Python instances, asserted at status `200` with a body exactly `{"status":"ok"}`; `POST .../handling-events` with a schema-valid body against Quarkus, asserted `202`; the same against Quarkus with a malformed `eventType` enum value, asserted `400` — the Java `HandlingEvent` record carries no bean validation of its own, so only Jackson's enum deserialization, surfaced through RESTEasy Reactive's default unreadable-entity mapper, rejects it; the schema-valid case against Python, asserted `202` with the response body echoing back `status`/`eventId`/`bookingId`; and the malformed case against Python — a bad `bookingId` pattern *and* a bad `eventType` together — asserted `422`, with the response's `detail[]` array checked for entries naming *both* offending fields, because Pydantic v2 validates the pattern and the enum independently and a test that only checked the status code would miss a regression that dropped one of the two violations without failing anything. `part6-testing/verify.sh` runs this with a pinned `npx newman@6.2.3` rather than the `docker.io/postman/newman` image, because no image tag newer than `6.1.3` exists yet and this project's standing policy is to upgrade the tool rather than downgrade the pin.

This example's own README draws a scope line worth keeping, because it is the same discipline the whole five-layer structure depends on: `part6-observability`'s HTTP surface — `/q/metrics` on Quarkus, a Prometheus endpoint on Python — is explicitly out of this collection, not because it is unimportant but because proving it live needs a WebSocket connection opened first. Its `handling_events_delivered_total` Micrometer counter is registered in a `@PostConstruct` on a *per-connection* WebSockets Next bean, so it is absent from `/q/metrics` entirely until at least one connection has opened once — a Newman request against that endpoint before any socket ever connects would prove nothing about whether the metric works, only that it hasn't been touched yet. Chapter 23's own `verify.sh` already owns driving that connection and scraping the result; folding the same proof into this Newman collection would blur "functional HTTP" into "functional HTTP plus WebSocket plus the observability stack," exactly the boundary DRQ-006 draws between tools by keeping them split by shape instead of by chapter.

## Load, and the drift gate that ties every layer back to the contract

Chapter 20 already walked the measurement discipline inside k6's own split — `smoke.js` gated and deterministic, `benchmark.js` local-only because absolute throughput is host-dependent (DRQ-027) — so this chapter's job is placing that split inside the five-layer picture rather than re-deriving it. `smoke.js` exists for `part4-connection`, `part4-backplane`, and `part5-performance`, and the `k6-smoke` CI job runs it against every one of them in a single workflow: `part4-connection`'s Quarkus and Python instances each get their own invocation on `:8080`/`:8081` against a freshly minted shared-secret token, `part4-backplane`'s default-profile `quarkus-a`/`python-a` get a no-auth smoke pass, and `part5-performance`'s both stacks get a pass over *both* negotiated subprotocols — `handling-events.v1+json` and `handling-events.v1+protobuf` — in the same iteration, checking that JSON frames arrive as `message` events and Protobuf frames arrive as `binaryMessage` events without decoding either payload (that decode belongs to `verify.sh`, against a real generated stub). Its `thresholds: { checks: ["rate==1.0"] }` is the one assertion in this whole corpus that fails a PR the instant a single check fails, anywhere, which is exactly the "deterministic, not timing-sensitive" property every layer below it also aims for, enforced here at the k6-runner level instead of a bash `assert_eq`. `benchmark.js`'s connects/sec and bytes/frame numbers are the opposite case: cited in prose (Chapter 20's table), never asserted as a CI gate, because the same script measured 100% connect success on a freshly restarted container and as low as single digits after the host's ephemeral TCP range filled up from prior runs — a true number about that host at that moment, not a property of the framework under test.

What keeps five independently-runnable layers pointed at the same contract is a sixth piece of CI, the `drift` job. It loops over `DRIFT_APPS` — `part3-handling-events part4-connection part4-backplane part5-performance` — and for each one: regenerates `build/handling-event.schema.json` from `contracts/asyncapi.yaml`, regenerates that app's Python model (plus, where present, its Protobuf stub via `generate-proto.sh`), runs `uv run pytest tests/test_contract.py -v`, then runs the Quarkus side's `HandlingEventContractTest` (and `HandlingEventProtoRoundTripTest` where it exists) against the same freshly-extracted schema. A change to the contract that breaks any app's model regeneration, or any app's conformance assumptions, fails this job on every affected app in one pass without needing a human to notice first — DRY, so a Part 6+ app only needs adding to one list, not four near-duplicate step blocks. The `examples` matrix job sits one layer up from that: it discovers every `examples/*/verify.sh` automatically via a `discover-examples` job, runs each with up to three retries inside a 45-minute per-job cap sized for `part4-backplane`'s three-stage broker lifecycle, `fail-fast: false` so one example's failure doesn't cancel the rest of the matrix mid-run, and gates the whole PR on every one of them passing, alongside the separate, always-gated `k6-smoke` job. Five layers, one contract, one schema file they all read — the drift gate is what makes "both stacks agree" a property CI checks on every change, not a claim a chapter makes once and hopes stays true.

A separate job, `buf lint/build/breaking + AsyncAPI<->proto parity`, closes one more gap the app-level `drift` job can't reach: nothing in that loop ever looks at `contracts/handling-event.proto` in isolation, so a field renamed or dropped on only one side of the two contract halves — the AsyncAPI JSON schema and the Protobuf schema Chapter 19 introduced — would pass every app's conformance test as long as each app only checks itself against its own half. `scripts/check-proto-parity.py` is the gate for exactly that case: it diffs the compiled proto descriptor against the same freshly-extracted `build/handling-event.schema.json` every other layer reads, always run in this job regardless of whether `buf breaking` finds a baseline to diff against yet. It sits conceptually one level below the `HandlingEventProtoRoundTripTest`/`test_proto_round_trip_matches_schema_and_json_values` pair from the first section of this chapter — those two prove one app's generated proto code round-trips correctly against its own schema; `check-proto-parity.py` proves the two *contract source files* never drifted apart from each other in the first place, before any app-level code generation even runs.

## On the wire

A real `verify.sh` PASS line, from `part4-connection` after every auth, error-taxonomy, backpressure, and heartbeat assertion above has run against both stacks:

```
PASS — Part 4 connection-concerns: Quarkus and Python both implement
identical Ch17 auth (accept + 4 reject modes), Ch13 error taxonomy
(BAD_REQUEST envelope + 4400 close), Ch12 backpressure (4290 close),
and Ch14 heartbeat liveness detection of a silent peer (proven live
on both stacks within a short, env-configured window) against the
SAME shared JWT secret.
```

`part4-backplane`'s, after all three compose stages — stateless, kafka, redis:

```
PASS — Part 4 backplane: Quarkus and Python both implement the SAME
reconnect + scale-out behavior (PROTOCOL.md) — Ch15 stateless mode
loses a gap-era event, Ch16 kafka mode replays it after reconnect
(dedup by eventId, no more than the documented benign duplicate),
and Ch18 an event injected through instance B reaches a client
connected to instance A over BOTH the Kafka and the Redis backplane,
with instance A's own log confirming it did the delivering.
```

Run the Newman collection the same way CI does, from the repo root:

```bash
cd examples/part6-testing
./verify.sh
```

Its captured JSON report (`newman/reports/newman-report.json`, regenerated every run) is the exact per-run tally this chapter's functional-HTTP section cites:

```json
{
  "items":      { "total": 6,  "failed": 0 },
  "requests":   { "total": 6,  "failed": 0 },
  "tests":      { "total": 6,  "failed": 0 },
  "assertions": { "total": 12, "failed": 0 }
}
```

Six requests, twelve `pm.test` assertions across them, zero failures — `/healthz` on both Python instances, the inject endpoint's `202`/`400`/`422` cases on both stacks. A passing `k6/smoke.js` run was confirmed live against both stacks on this project's own CI runner (2026-10-19, same capture Chapter 20 cites): 54/54 checks on Quarkus `:8090`, 54/54 on Python `:8091`, both JSON-as-TEXT and Protobuf-as-BINARY, gated on every PR via the `k6-smoke` job.

## Where this goes next

This chapter named five layers that already existed scattered across twenty chapters of examples and gave them one shared vocabulary: unit/conformance tests that never touch a socket, `verify.sh`/`lib.sh` integration tests that open real ones against real containers, a Python close-code probe for the one signal `websocat` can't read, Newman for the plain-HTTP seams sitting next to the contract, and k6 split cleanly between a gated smoke check and a local-only comparative benchmark. The thread running through all five is the same one Chapter 20 ended on: a deterministic assertion — a schema pass, a close code, an assertion count, a `rate==1.0` threshold — belongs in a gate; a timing-sensitive number — a heartbeat detection window, an idle-hold duration, a raw connects/sec figure — gets a generous bound or stays in prose, never a tight CI assertion. The `drift` job is what keeps all five pointed at the one artifact they ultimately read: `contracts/asyncapi.yaml`, by way of the schema it extracts to.

Chapter 22 picks up where this one's blind spots end: when a live connection misbehaves in a way none of these five layers caught — a client stuck mid-handshake, a frame that never arrived, a close code a probe wasn't watching for — what debugging it looks like, with the same tools this chapter inventoried turned toward diagnosis instead of a pass/fail gate. Chapter 23 is where the one piece of new code in this part lands: live OpenTelemetry over a WebSocket connection, verified headless the same way every `verify.sh` in this chapter has been. Chapter 24 closes Part 6 by naming the anti-patterns a team reaches for when it skips straight to shipping without any of this five-layer structure underneath it.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Treat WebSocket testing as five layers, not one suite: unit/conformance (<code>test_contract.py</code>, <code>HandlingEventContractTest</code>/<code>HandlingEventProtoRoundTripTest</code>) validates shape and round-trip values with no socket and no container, in milliseconds. Live integration (<code>verify.sh</code>/<code>lib.sh</code>, both stacks, real <code>docker compose</code> containers) proves frame contents, reconnect/resume, and cross-instance fan-out that a unit test structurally cannot reach. A dedicated close-code probe (Python's <code>websockets</code> library, not <code>websocat</code>) exists because <code>ws.close_code</code> is the one signal this project's primary WebSocket client can't read — checking exit code alone cannot distinguish a rejected connection from one the server still intends to hold open. Newman covers the plain-HTTP seams around the WS-only contract (DRQ-006/DRQ-030) — 12 assertions, 0 failed, against <code>/healthz</code> and the inject endpoint's 202/400/422 cases. k6 splits cleanly between <code>smoke.js</code> (gated, <code>rate==1.0</code>, fails the PR on any failed check) and <code>benchmark.js</code> (local-only, because absolute throughput is host-dependent). One CI job, <code>drift</code>, ties every layer back to the same contract-derived schema on every change to <code>contracts/asyncapi.yaml</code> — the property that makes "both stacks agree" something CI checks continuously, not a claim a chapter makes once.</p></div>

## For deeper coverage

- Sam Newman, *Building Microservices*, 2nd ed. (O'Reilly, 2021) — testing strategy across independently-deployable services, the same shape this chapter applies to two independently-built stacks implementing one contract.
- *Cloud Native Design Patterns* — "API Testing with Newman" chapter — the Newman-collection pattern this chapter scopes to the plain-HTTP seams around a WebSocket-only contract.
- *Cloud Native Design Patterns* — "Anti-Patterns" chapter — the companion catalogue of testing and operational anti-patterns Chapter 24 draws on for this site's own list.
- [Python `websockets` library documentation](https://websockets.readthedocs.io/en/stable/) — the `close_code` attribute and connection API this chapter's `ws_close_probe` and proto-round-trip tests depend on.
- [Quarkus — Testing Your Application](https://quarkus.io/guides/getting-started-testing) — the JUnit-based testing model behind `HandlingEventContractTest` and `HandlingEventProtoRoundTripTest`.
