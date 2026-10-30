---
title: "Python Native WebSockets"
order: 9
part: "Building It"
description: "Implementing the same feed in Python with FastAPI/Starlette and the native websockets library."
duration: "20 min read"
---

## Learning objectives

By the end of this chapter you can:

- Decide between the native `websockets` library and FastAPI/Starlette's bundled `WebSocket` based on whether the app needs to reason about the connection as a state machine.
- Implement a `websockets.asyncio.server.serve` handler that matches a channel path by regex, pushes a fixture sequence, and closes an unmatched path with an RFC 6455 close code.
- Run a native `websockets` server and a FastAPI app as two coroutines on one `asyncio` event loop via `asyncio.gather`, without either one blocking the other.
- Generate a Pydantic v2 model from `contracts/asyncapi.yaml` with `datamodel-codegen` instead of hand-writing one, and explain what `exclude_none=True` and `sort_keys=True` each protect against.
- Write a conformance test that both schema-validates emitted frames and round-trips fixture values exactly, catching silent reformatting that schema validation alone would miss.

## Why this matters

Quarkus WebSockets Next already built `handlingEvents`. This chapter builds the identical channel (`/ws/v1/bookings/{bookingId}/handling-events`, the same three-event fixture, the same `HandlingEvent` schema) in Python, and the first decision is not "which framework" but "which WebSocket." The house stack doesn't just say "Python"; it specifies FastAPI/Starlette for HTTP, plus the native `websockets` library for the socket itself, not Starlette's bundled `WebSocket` type. That's a deliberate split, not an oversight, and this chapter exists to show why: what the native library exposes that a framework shim hides, how two listeners (one `websockets` server, one FastAPI app) share a single Python process without stepping on each other, how the contract's Pydantic model gets generated at build time instead of hand-written, and when, despite all of that, reaching for the framework's own WebSocket support is still the right call.

## Why not FastAPI's bundled WebSocket

FastAPI's `WebSocket` type is not FastAPI's own code. It is a thin convenience wrapper over Starlette's ASGI-level `WebSocket` class, which itself sits on top of whatever ASGI server (uvicorn, by default) is running the app. That wrapper is convenient for the common case: `await websocket.accept()`, `await websocket.receive_text()`, `await websocket.send_json(...)`, all inside a route function that looks like every other FastAPI handler, with dependency injection and the rest of the framework's machinery included. It is also a simplification, and not an accidental one. It collapses the WebSocket connection down to "a thing you can send text or JSON to and receive text or JSON from," because that covers most of what most apps need, and hides everything about how the connection got into that state or what happens when it leaves it.

What it hides is exactly what this chapter names: the connection's state machine, the ping/pong control frames that keep an idle connection alive and detectable, and the close-code vocabulary the WebSocket protocol defines for saying *why* a connection ended. Starlette's ASGI WebSocket interface has no first-class way to send an application-level ping with a payload you choose and inspect the pong that comes back, no way to close with an arbitrary RFC 6455 code without routing it through an ASGI message dict, and no exception type that distinguishes "the client closed normally" from "the network died." The native `websockets` library makes all three first-class: `websocket.ping()` returns an awaitable you can wait on for the matching pong, `websocket.close(code=..., reason=...)` takes the numeric close code directly, and catching `websockets.exceptions.ConnectionClosed` (or its two subclasses, `ConnectionClosedOK` and `ConnectionClosedError`) tells a handler which kind of ending it just saw. This chapter's example only needs the close-code path, in `app/ws_server.py`:

```python
async def handler(websocket: ServerConnection) -> None:
    path = websocket.request.path
    match = _CHANNEL_PATH.match(path)
    if match is None:
        logger.warning("rejecting connection on unknown path: %s", path)
        await websocket.close(code=1008, reason="unknown channel path")
        return
```

`1008` is RFC 6455's "Policy Violation" close code: not `1000` (normal closure), not a vague exception, but a specific, protocol-defined reason a well-behaved client can branch on. A framework-level WebSocket wrapper would let you *send* a close frame with a code, typically by constructing a raw ASGI message yourself, but it wouldn't make inspecting ping/pong round-trip latency, or reacting differently to `ConnectionClosedOK` versus `ConnectionClosedError`, as direct as calling a method and catching a type. Part 4's liveness and reconnect chapters (heartbeats, reconnect-with-backoff, distinguishing a clean disconnect from a dropped network) are built on exactly this vocabulary, which is why it exists here rather than being bolted on later over a framework abstraction that was never designed to expose it.

## One handler, one channel: the websockets server

`websockets.asyncio.server.serve` is the entry point: give it a coroutine function and a host/port, and it runs an accept loop that spawns one invocation of that coroutine per accepted connection, handing it a `ServerConnection` object. The whole endpoint for this chapter's channel is one `handler` function and one factory that wraps `serve`:

```python
_CHANNEL_PATH = re.compile(r"^/ws/v1/bookings/(?P<bookingId>[^/]+)/handling-events$")


async def handler(websocket: ServerConnection) -> None:
    path = websocket.request.path
    match = _CHANNEL_PATH.match(path)
    if match is None:
        logger.warning("rejecting connection on unknown path: %s", path)
        await websocket.close(code=1008, reason="unknown channel path")
        return

    booking_id = match.group("bookingId")
    logger.info("handling-events: opening feed for bookingId=%s", booking_id)

    try:
        for frame in sequence_as_json():
            await websocket.send(frame)
        await websocket.wait_closed()
    except ConnectionClosed:
        logger.info("handling-events: client disconnected bookingId=%s", booking_id)


def create_server(host: str, port: int):
    return serve(handler, host, port)
```

Three things are worth reading closely here, because each one is a decision rather than a default. First, routing. `serve()` has no built-in concept of a path-based router the way an HTTP framework does (it hands every accepted connection, regardless of path, to the same `handler` coroutine), so `_CHANNEL_PATH` does the job a router would do in a bigger app: match the upgrade request's path against the one channel this server knows about, and reject (with a real close code, not a dropped connection) anything else. This is a single-channel server; a multi-channel Python WebSocket service would need to either dispatch on this match inside one handler or run multiple `serve()` instances on different paths, and the regex-and-reject pattern here is the smallest version of that dispatch that still behaves correctly for an unmatched path. Second, the push itself. `for frame in sequence_as_json(): await websocket.send(frame)` sends the fixture's three pre-serialized JSON frames back to back, as soon as the connection opens, matching the contract's `receiveHandlingEvent` operation, which is server-to-client push with no expected client message. A real backend swaps the finite `for` loop for an open-ended one reading from wherever new handling events arrive (a queue, a database change feed, a Kafka consumer); the shape (iterate, `send`, keep the connection open) doesn't change. Third, `wait_closed()`. After the fixture is exhausted, the handler doesn't return: returning would let `serve()` tear the connection down, ending the socket the moment the last fixture frame lands, which doesn't match "one WebSocket connection per booking" staying open for a real feed's lifetime. `wait_closed()` blocks the coroutine until the client disconnects, and `ConnectionClosed` is what that wait raises when it does, which the handler catches and logs rather than letting propagate as an unhandled exception in the accept loop.

{% include excalidraw.html file="09-two-listeners-one-loop" alt="A banded diagram of app/main.py: an ink-colored box at the top reads await asyncio.gather(_run_ws(), _run_http()), with two arrows labeled task 1 and task 2 going down to two boxes. The left box, accent-colored, reads _run_ws(): app/ws_server.py, websockets.asyncio.server.serve(handler, ...), WS_HOST:WS_PORT 0.0.0.0:8081, one handler() coroutine per connection, with an arrow down to a dashed box reading WS client, ws://.../ws/v1/bookings/{bookingId}/handling-events, labeled pushes 3 frames then idles. The right box, blue-colored, reads _run_http(): app/http_app.py, uvicorn.Server(Config(http_app, ...)), HTTP_HOST:HTTP_PORT 0.0.0.0:8082, FastAPI: GET /healthz, GET /, with a dashed arrow down to a dashed box reading HTTP client / k8s probe, GET /healthz, labeled liveness/readiness only. A caption at the bottom reads: neither listener blocks the other, both are coroutines on the same loop, not separate processes or threads." caption="Figure 9.1: app/main.py runs the websockets server and FastAPI side by side as two coroutines on one asyncio event loop." %}

The docstring on `create_server` flags a fourth decision to call out before moving past this file: the contract's `local` server binding names a `handling-events.v1` subprotocol and a `token` query parameter, and this handler enforces neither. Passing `subprotocols=["handling-events.v1"]` into `serve()` would make the library reject, with a `400` before the upgrade even completes, any client that doesn't offer that subprotocol, which would break plain clients (websocat, a browser without the subprotocol wired into its own `new WebSocket(url, protocols)` call) for a guarantee this example doesn't implement any behavior on. That enforcement is deferred to the security chapter, where token validation gets built and tested rather than added as a half-implemented gate here; until then, this endpoint accepts any upgrade to the channel path, which the chapter's own `verify.sh` relies on when it connects with plain `websocat`.

## Two listeners, one event loop

A WebSocket connection and an HTTP health check are different enough traffic that it would be reasonable to assume they need different processes. `app/main.py` says otherwise: both run as coroutines on the one `asyncio` event loop `asyncio.run(main())` starts, scheduled together by a single `asyncio.gather` call.

```python
WS_HOST = os.environ.get("WS_HOST", "0.0.0.0")
WS_PORT = int(os.environ.get("WS_PORT", "8081"))
HTTP_HOST = os.environ.get("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("HTTP_PORT", "8082"))


async def _run_http() -> None:
    config = uvicorn.Config(http_app, host=HTTP_HOST, port=HTTP_PORT, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def _run_ws() -> None:
    async with create_server(WS_HOST, WS_PORT):
        logger.info(
            "handling-events-python: ws://%s:%s/ws/v1/bookings/{bookingId}/handling-events",
            WS_HOST,
            WS_PORT,
        )
        await asyncio.get_running_loop().create_future()  # run forever

async def main() -> None:
    await asyncio.gather(_run_ws(), _run_http())
```

`_run_ws()` opens `create_server(...)`'s `async with` block (which starts the `websockets` accept loop and keeps it running for as long as the block is entered) and then awaits a `Future` that never resolves, which is the idiomatic `asyncio` way to say "hold this coroutine open forever without busy-waiting." `_run_http()` builds a `uvicorn.Server` around the FastAPI `app` and awaits `server.serve()`, which does the same thing on uvicorn's terms: run until the process is told to stop. `asyncio.gather(_run_ws(), _run_http())` schedules both as top-level tasks on the one loop `asyncio.run(main())` created, and from there the Python interpreter's cooperative scheduling is what keeps them from blocking each other: neither coroutine does blocking I/O (both `websockets` and uvicorn's ASGI loop are themselves `asyncio`-native), so the loop interleaves the WebSocket accept loop's work and uvicorn's HTTP request handling freely, on one thread, in one process.

This is the point `app/http_app.py`'s own docstring makes explicit: FastAPI's job here is **HTTP and app lifecycle only** (a `GET /healthz` a Kubernetes liveness/readiness probe can poll, and a `GET /` describing the channel), by design not where the WebSocket endpoint lives, because that would be exactly the bundled-`WebSocket` approach the previous section explained this chapter is contrasting against. Two ports (`8081` for the socket, `8082` for HTTP; `8080` stays free for the Quarkus sibling in the same Compose file) means a load balancer, a readiness probe, and a WebSocket client are each hitting a surface built for what they're doing: the probe gets a fast, stateless HTTP round trip without opening a long-lived socket just to ask "are you alive," and the socket client gets a connection with nothing HTTP-shaped layered in front of it. The two listeners sharing a process instead of running as two separate deployables is a scale decision as much as a code-organization one (it keeps the example to one container, one `main`, one set of logs), and the scale-out and fan-out chapter is where that single-process model gets revisited once a real deployment needs to scale the socket independently of the HTTP side.

## Generating the contract model at build time

Every `HandlingEvent` this server sends has to match `contracts/asyncapi.yaml`'s schema, and the chapter's answer to "how do we keep that true" is not a hand-written `class HandlingEvent(BaseModel): ...` kept in sync by discipline. It is a generated one, produced fresh at every build from the contract itself, that a developer never hand-edits and the repository never commits.

`datamodel-code-generator`'s direct AsyncAPI input support turned out to be unreliable against this contract's structure, so the pipeline goes through an intermediate step instead: `scripts/extract-message-schema.py`, run from the repo root, reads `contracts/asyncapi.yaml`, walks to `components.schemas.HandlingEvent`, and inlines its `$ref`s to `HandlingEventType`, `Location`, and `Money` into one self-contained JSON Schema document (Draft 2020-12, no remaining external references), written with `json.dumps(schema, indent=2, sort_keys=True)`. That `sort_keys=True` detail matters later in this chapter; hold onto it. `scripts/generate-models.sh` runs that extraction and then feeds the result to the actual generator:

```bash
uv run datamodel-codegen \
  --input "$SCHEMA" \
  --input-file-type jsonschema \
  --output app/models_generated.py \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.15 \
  --use-schema-description \
  --disable-timestamp \
  --formatters black isort
```

`--output-model-type pydantic_v2.BaseModel` is the choice that makes the generated class a real Pydantic v2 model with real validation: a `bookingId` that fails `^bkg_[0-9A-Za-z]{26}$`, an `eventType` outside the enum, or a missing required field all raise `pydantic.ValidationError` at parse time, not silently produce a malformed object. `--use-schema-description` carries the contract's own field descriptions into the generated class as docstrings, so a developer reading the Python model sees the same explanation an AsyncAPI-aware editor would show them reading the YAML. `--disable-timestamp` and the `black`/`isort` formatters keep the output deterministic and readable rather than timestamped and unformatted, which matters because the output is regenerated on every build: a diff between two generations of the same schema should be empty, not full of timestamp churn.

{% include excalidraw.html file="09-model-generation-flow" alt="A two-band diagram. The top band, labeled build time, shows contracts/asyncapi.yaml (components.schemas.HandlingEvent) flowing through extract-message-schema.py (inlines refs, sort_keys=True) into build/handling-event.schema.json (gitignored, Draft 2020-12), then into datamodel-codegen, with an amber arrow labeled pydantic_v2.BaseModel flowing down into the bottom band. The bottom band, labeled runtime, shows app/models_generated.py (gitignored, class HandlingEvent(BaseModel)) flowing into app/feed.py (HandlingEvent.model_validate(fixture), sequence_as_json()) flowing into app/ws_server.py (handler(): await websocket.send(frame) for frame in sequence_as_json()). A caption at the bottom reads: one generated model does both jobs: validate the fixture in, serialize the wire frame out, nothing hand-written in between to drift from the contract." caption="Figure 9.2: contracts/asyncapi.yaml becomes app/models_generated.py's Pydantic model at build time; nothing hand-written sits between the contract and the wire frame." %}

The output, `app/models_generated.py`, is gitignored (the project's `.gitignore` names it explicitly with a comment to regenerate rather than hand-edit it), and both the local dev loop and the `Containerfile` regenerate it as a build step rather than assuming a checked-in copy is current. `app/feed.py` is the only place that imports it, and it uses the generated `HandlingEvent` for both halves of the job: `HandlingEvent.model_validate(raw)` on the way in, which fails loudly (at import/startup time, not silently on the wire) if the fixture ever drifts from what the contract allows, and `event.model_dump_json(exclude_none=True)` on the way out, producing the exact bytes `ws_server.py`'s `handler` sends. `exclude_none=True` is doing real work here: the fixture's RECEIVE event has no `voyageNumber` or `amount`, and the generated model declares both as optional fields that default to `None`, so without `exclude_none` the wire frame would gain two null fields the fixture never had. Generating the model instead of writing it by hand means there is exactly one place a schema change has to land (the contract), and the Python side picks it up on its next build, rather than a developer needing to remember to update a hand-written class every time the AsyncAPI document gains or renames a field.

## The conformance test

A generated model removes one class of drift (hand-written code falling out of sync with a schema someone forgot to re-read), but it doesn't remove the need to prove the generated code and the fixture it's validating actually agree: that is `tests/test_contract.py`'s job, run with `uv run pytest`. It validates against the same extracted JSON Schema the generator consumed, loaded once per test module:

```python
def test_emitted_frames_validate_against_schema(validator: Draft202012Validator) -> None:
    frames = sequence_as_json()
    assert len(frames) == 3
    for frame in frames:
        doc = json.loads(frame)
        errors = list(validator.iter_errors(doc))
        assert not errors, f"{frame} failed schema validation: {errors}"


def test_generated_model_round_trips_fixture_values_exactly() -> None:
    for raw in load_fixture():
        model = HandlingEvent.model_validate(raw)
        dumped = json.loads(model.model_dump_json(exclude_none=True))
        assert dumped == raw, f"round-trip drift for {raw['eventId']}: {dumped} != {raw}"
```

The first test is the most direct claim a generated-from-contract pipeline can make: every frame the server would actually send (the real output of `sequence_as_json()`, not a hand-constructed sample) validates against the schema the model was generated from. The second test is the subtler one, and it's where `--disable-timestamp` and deterministic generation earn their keep for a different reason: `parse, then dump` has to reproduce the exact same JSON values the fixture started with, field for field, not merely "still valid JSON." The test's own module docstring calls out the specific trap this guards against: Pydantic v2's datetime serialization preserves a trailing `Z` UTC suffix from the input rather than normalizing it to `+00:00`, and if that normalization ever happened silently, the Python stack's wire frames would stop being byte-identical to the Quarkus stack's, even though both would still be "valid" by the schema's `format: date-time` constraint. A round-trip test catches that class of silent reformatting that schema validation alone can't, because `2026-01-15T08:00:00Z` and `2026-01-15T08:00:00+00:00` are the same instant and both validate: only an exact-value comparison against the fixture, the way `test_generated_model_round_trips_fixture_values_exactly` does it, would fail if one stack started emitting the other form. The remaining three tests round out the set: the fixture is `RECEIVE`, `LOAD`, `CUSTOMS` in that order; the first emitted frame matches `fixture[0]` exactly, including `eventType == "RECEIVE"`; and `sequence()` returns real `HandlingEvent` instances, not raw dicts, with `eventType.value` confirming the enum parsed correctly rather than staying a bare string.

## When to reach for the framework's WebSocket instead

None of the above is an argument that the native `websockets` library is always the right call. Starlette's bundled `WebSocket` is the better default when the socket is incidental to an otherwise HTTP-centric FastAPI app: a small admin dashboard that pushes a handful of live-updating numbers alongside a dozen REST routes, where pulling in a second server, a second port, and a second library's connection-lifecycle API would cost more in operational surface than it buys in control nobody in that app needs. It's also the right call early in a prototype, or on a team already deep in FastAPI's dependency-injection and middleware ecosystem, where `websocket: WebSocket = Depends(...)` reusing the same auth dependency a REST route already has is worth more than direct access to ping/pong timing. The tell is whether the application ever needs to reason about the connection as a *state machine* (distinguishing a clean close from a dropped one, sending an application-level ping and measuring the pong, closing with a specific RFC 6455 code a client branches on) or whether "send JSON, receive JSON, handle disconnect" covers the whole requirement. This chapter's example needs the state machine, because Part 4 builds liveness detection and reconnect logic directly on top of it; a dashboard that quietly drops and reconnects without anyone needing to know why usually doesn't, and wrapping that in the native library's extra API surface would be solving a problem the app doesn't have. The decision, in other words, tracks the same axis the transport-choice framework used for the stack as a whole, just applied one layer deeper: pick the tool that matches how much control the requirement needs, not the one with more features.

## On the wire

`examples/part3-handling-events/verify.sh` brings both stacks up via Compose and checks the Python listener at `localhost:8081` the same way it checks Quarkus at `localhost:8080`: wait for the upgrade to succeed, read the first pushed frame, validate it against the contract-derived schema, and assert its fields against the fixture. Run just the Python side with websocat directly, once the example is running (`uv run python -m app.main` from `examples/part3-handling-events/python/`):

```bash
websocat "ws://localhost:8081/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events" -1 -n
```

or run the chapter's full both-stack check:

```bash
bash examples/part3-handling-events/verify.sh
```

The first frame off the wire is the RECEIVE event, with `exclude_none=True` dropping the absent `voyageNumber` and `amount` fields, and with its JSON keys in **alphabetical** order rather than the fixture's own field order, because the generated model's fields follow the extracted schema's `sort_keys=True` property order, and Pydantic v2's `model_dump_json` serializes fields in the model's declared order:

```json
{"bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
```

That's the same fields, the same values (including the `Z` suffix on both timestamps) as the Quarkus stack's first frame, just in a different key order, which `verify.sh`'s own cross-stack comparison step calls out by name: it parses both frames and compares field by field rather than diffing raw bytes, specifically because "key order differs between Jackson and Pydantic, and that's fine": the two stacks don't need to agree on serialization conventions, only on the contract.

## Where this goes next

The connection-state-machine vocabulary this chapter built the case for (`ConnectionClosed`, explicit close codes, `wait_closed()`) isn't exercised yet beyond the one `1008` rejection path; a real client against this server, next, starts asking what that client does when the connection drops mid-feed, and the heartbeats chapter is where `websocket.ping()` and pong round-trip timing finally get used for something this chapter only named. The polyglot comparison takes the two-listeners architecture this chapter built and the Quarkus one built earlier and runs them side by side against the one contract, proving the cross-stack agreement `verify.sh` already checks on every build. Error handling comes back to this handler's error paths with the fuller treatment this chapter only touched with one close code. And security is where the `handling-events.v1` subprotocol and the `token` query parameter (both named in the contract, neither enforced by `create_server` today) get the validation this chapter's docstring deferred.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Choosing the native <code>websockets</code> library over FastAPI/Starlette's bundled <code>WebSocket</code> is a decision about how much of the connection's state machine the application needs to control, not a verdict that one is categorically better than the other. Reach for the framework's bundled support when the socket is incidental to an HTTP-centric app, when the team's auth and middleware stack already lives in FastAPI's dependency-injection model and reusing it outweighs direct protocol control, or when "send JSON, receive JSON, handle disconnect" is the entire requirement: a small live-updating dashboard bolted onto a dozen REST routes is the clearest case, and paying for a second server and a second library's API to gain ping/pong and close-code control nobody uses there is a net loss. Reach for the native library when the application needs to reason about the connection as a state machine: distinguishing <code>ConnectionClosedOK</code> from <code>ConnectionClosedError</code>, sending an application-level ping and measuring the pong that comes back, closing with a specific RFC 6455 code a client is built to branch on: exactly the knobs Part 4's liveness and reconnect chapters build on, and exactly what this chapter's <code>handler</code> already uses once, rejecting an unmatched path with <code>close(code=1008, ...)</code> rather than a dropped connection or a generic exception. Running that native listener and a FastAPI app side by side in one process, on one <code>asyncio</code> event loop via <code>asyncio.gather</code>, is the same kind of scoped decision: FastAPI keeps the job it's good at (HTTP routing, lifecycle, a probe a load balancer understands) while the socket gets a listener built for exactly what it has to do, and neither listener pays for capability the other one needed.</p></div>

## For deeper coverage

- Lukasz Dynowski & Marcin Dulak, *Learning API Styles* (O'Reilly, 2025): a style-by-style comparison of how much of the transport a framework hides versus exposes, the same axis this chapter uses to pick the native `websockets` library over FastAPI's bundled wrapper.
- *Cloud Native Design Patterns*, "Communications" chapter: running two independent listeners (socket and HTTP health check) cooperatively on one process instead of splitting them into separate deployables.
- *Cloud Native Design Patterns*, "WebSockets at Scale" chapter: the connection-state-machine vocabulary (ping/pong, close codes) this chapter builds toward Part 4's liveness and reconnect chapters.
- [Python `websockets` documentation](https://websockets.readthedocs.io/): `serve`, `ServerConnection`, `ConnectionClosed`/`ConnectionClosedOK`/`ConnectionClosedError`, and the ping/pong API this chapter's `handler` is built from.
- [RFC 6455: The WebSocket Protocol](https://www.rfc-editor.org/rfc/rfc6455): the `1008` Policy Violation close code and the broader close-code vocabulary this chapter contrasts against a framework-level wrapper.
