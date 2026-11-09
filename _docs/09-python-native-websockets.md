---
title: "Python Native WebSockets"
order: 9
part: "Building It"
description: "Implementing the same feed in Python with the native websockets library beside a FastAPI app, with the message model generated from the contract."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Decide between the native `websockets` library and FastAPI's bundled `WebSocket` by whether the app must reason about the connection as a state machine.
- Write a `websockets.asyncio.server.serve` handler that matches a channel path by regex, pushes a fixture and closes an unmatched path with an RFC 6455 close code.
- Run a `websockets` server and a FastAPI app as two coroutines on one `asyncio` event loop.
- Generate a Pydantic v2 model from `contracts/asyncapi.yaml` instead of writing one, and say what `exclude_none=True` and `sort_keys=True` each protect.
- Check emitted frames by schema validation and by an exact round trip of the fixture values.

## Why this matters

The Python service implements the same channel as the Quarkus one: `/ws/v1/bookings/{bookingId}/handling-events`, the same three-event fixture, the same `HandlingEvent` schema. The first decision is which WebSocket: the native `websockets` library for the socket, and FastAPI only for HTTP. The choice decides how much of the connection the code can see.

## Why not FastAPI's bundled WebSocket

FastAPI's `WebSocket` is Starlette's ASGI `WebSocket`, running on whatever ASGI server (uvicorn by default) hosts the app. It fits the common case, `await websocket.accept()`, `receive_text()`, `send_json(...)`, inside a route that gets dependency injection like any other. It also reduces the connection to something you send text or JSON to and receive from, and hides how the connection got there and how it leaves.

What it hides is the connection's state machine, the ping and pong control frames, and the close-code vocabulary. Starlette has no first-class way to send a ping with a payload you choose and wait for the matching pong, and closing with an arbitrary RFC 6455 code goes through an ASGI message dict. The native library makes all three direct:

| Need | Native `websockets` |
|---|---|
| Ping and measure the pong | `websocket.ping()` returns an awaitable that completes on the matching pong |
| Close with a specific code | `websocket.close(code=..., reason=...)` |
| Tell how the connection ended | Catch `ConnectionClosed`, or its subclasses `ConnectionClosedOK` and `ConnectionClosedError` |

Reach for the framework's `WebSocket` when the socket is incidental to an HTTP-centric app, such as a dashboard that pushes a few live numbers beside a dozen REST routes. One server, one port and the same auth dependency as the REST routes outweigh control nobody uses. The same holds early in a prototype, or for a team already invested in FastAPI's dependency injection and middleware. Reach for the native library when the app distinguishes a clean close from a dropped network, pings and measures the pong, or closes with a code a client branches on.

## One handler, one channel

`serve()` takes a coroutine and a host and port, runs an accept loop, and calls the coroutine once per connection with a `ServerConnection`. It has no path router, so a regex does the routing:

```python
# Matches the AsyncAPI channel address `/ws/v1/bookings/{bookingId}/handling-events`.
# bookingId is captured but, for this deterministic fixture-replay example,
# not used to select a different sequence: every connection on this path
# replays the same shared fixture (see app/feed.py).
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
        # The fixture sequence is finite; a real feed would keep the loop
        # open and `send` as new handling events are recorded. Here we just
        # hold the connection open so the channel's long-lived-per-booking
        # semantics still hold, until the client disconnects.
        await websocket.wait_closed()
    except ConnectionClosed:
        logger.info("handling-events: client disconnected bookingId=%s", booking_id)
```

- **Routing.** An upgrade on any other path closes with `1008` (Policy Violation), a code a client can branch on, instead of a dropped connection. A service with several channels dispatches on this match or runs one `serve()` per path.
- **Push.** The fixture's pre-serialized frames go out back to back as soon as the connection opens. The contract's operation is server-to-client with no expected client message. A live backend replaces the finite `for` with a loop over a queue or a Kafka consumer, and the shape stays the same.
- **Hold open.** The handler waits on `wait_closed()` instead of returning, because returning lets `serve()` tear the connection down. `ConnectionClosed` is what that wait raises when the client leaves, and the handler logs it.

The contract's `local` server binding names a `handling-events.v1` subprotocol and a `token` query parameter. This server enforces neither. Passing `subprotocols=["handling-events.v1"]` to `serve()` makes the library answer `400` to any client that does not offer it, which breaks plain clients such as websocat for a guarantee with no behavior behind it yet. Token validation belongs with the security work, where it can be built and tested.

{% include excalidraw.html file="09-two-listeners-one-loop" alt="One asyncio.gather call in main starts two coroutines. The websockets server on port 8081 handles one handler coroutine per WebSocket connection. The uvicorn server on port 8082 runs FastAPI with GET /healthz and GET /. Neither blocks the other." caption="Figure 9.1: The websockets server and FastAPI run as two coroutines on one asyncio event loop." %}

## Two listeners, one event loop

A socket and an HTTP health check do not need separate processes. Both run as coroutines on the loop `asyncio.run(main())` starts, scheduled by one `asyncio.gather`:

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

`_run_ws()` enters the server's `async with` block and awaits a future that never resolves, which holds the coroutine open without busy-waiting. `_run_http()` awaits `uvicorn.Server.serve()`. Both libraries are `asyncio`-native, so the loop interleaves them on one thread.

FastAPI's job here is HTTP and app lifecycle only: `GET /healthz` for a liveness or readiness probe, and `GET /` describing the channel. Two ports separate the concerns: `8081` for the socket, `8082` for HTTP, with `8080` left for the Quarkus service in the same Compose file. A probe gets a fast stateless round trip without opening a socket, and a socket client gets a connection with nothing HTTP-shaped in front of it. One process keeps the deployment to one container. Scaling the socket independently of the HTTP side means splitting them, which the scale-out design addresses.

## Generating the contract model

A hand-written `class HandlingEvent(BaseModel)` drifts from the contract. The model here is generated at every build and never committed.

`datamodel-code-generator` read directly from AsyncAPI proved unreliable against this contract. `scripts/extract-message-schema.py` instead reads `contracts/asyncapi.yaml`, takes `components.schemas.HandlingEvent`, inlines its `$ref`s to `HandlingEventType`, `Location` and `Money`, and writes one self-contained Draft 2020-12 schema with `sort_keys=True`. `scripts/generate-models.sh` feeds that schema to the generator:

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

- `pydantic_v2.BaseModel` makes the class a validating model. A `bookingId` that fails `^bkg_[0-9A-Za-z]{26}$`, an `eventType` outside the enum or a missing required field raises `pydantic.ValidationError` at parse time.
- `--use-schema-description` carries the contract's field descriptions into docstrings.
- `--disable-timestamp` and the formatters keep output deterministic, so two generations of one schema produce an empty diff.

{% include excalidraw.html file="09-model-generation-flow" alt="At build time, contracts/asyncapi.yaml passes through the extraction script into a JSON Schema and then through datamodel-codegen. At runtime the generated Pydantic model validates the fixture in app/feed.py, and the websockets handler sends its serialized frames." caption="Figure 9.2: The Pydantic model is generated from the contract at build time, so nothing hand-written sits between the contract and the wire frame." %}

`app/models_generated.py` is gitignored, and both the local loop and the `Containerfile` regenerate it. `app/feed.py` is its only importer and uses it both ways. `HandlingEvent.model_validate(raw)` raises a `ValidationError` when the fixture is loaded if it drifts from the contract, so a bad event never reaches the wire as a malformed frame. `model_dump_json(exclude_none=True)` produces the frames the handler sends. `exclude_none` matters because the `RECEIVE` event has no `voyageNumber` or `amount` and the model defaults both to `None`, so without it each frame would gain two null fields the fixture never had.

Schema validation alone misses one failure: a silent reformat. Pydantic v2 keeps a trailing `Z` on a datetime, but `2026-01-15T08:00:00Z` and `2026-01-15T08:00:00+00:00` are the same instant and both validate. If the model ever normalized one to the other, the Python frames would stop matching the Quarkus frames byte for byte. A round trip of each fixture event through the model must reproduce the fixture's values exactly.

> **Decision**
>
> Use the native `websockets` library when the app reasons about the connection as a state machine: `ConnectionClosedOK` versus `ConnectionClosedError`, a ping with a measured pong, a close code a client branches on. Use FastAPI's bundled `WebSocket` when "send JSON, receive JSON, handle disconnect" is the whole requirement or the socket sits beside a dozen REST routes. Run the native listener and FastAPI in one process on one loop with `asyncio.gather`, so each does the job it is built for.

> **🤖 Explore with your agent**
>
> "In examples/part3-handling-events/python, extend app/ws_server.py so a connection on /ws/v1/bookings/{bookingId}/handling-events whose bookingId does not match ^bkg_[0-9A-Za-z]{26}$ closes with code 1008, keeping the regex routing and the wait_closed hold-open. Then run examples/part3-handling-events/verify.sh."
>
> Check: `websocat -v "ws://localhost:8081/ws/v1/bookings/nope/handling-events"` reports a close with code 1008, and `bash verify.sh` still prints `PASS: `.

## Build, run, observe

Start the service from `examples/part3-handling-events/python/`, which listens on `8081` for the socket and `8082` for HTTP:

```bash
uv run python -m app.main
```

Connect with websocat:

```bash
websocat "ws://localhost:8081/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events" -1 -n
```

`verify.sh` brings up both stacks, reads the first frame from each, validates it against the schema extracted from the contract, checks its fields against the fixture and compares the two stacks field by field. Run `bash examples/part3-handling-events/verify.sh` and expect `PASS: `. The conformance tests run with `uv run pytest`.

The first frame is the `RECEIVE` event. Its keys are alphabetical, because the generated model's fields follow the extracted schema's `sort_keys=True` order and Pydantic serializes in declared order:

```json
{"bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
```

The values, including the `Z` suffix, match the Quarkus frame. Key order differs between Jackson and Pydantic, so the cross-stack comparison parses both frames and compares fields instead of bytes. The stacks must agree on the contract, not on serialization order.

- Connect to a path other than `/ws/v1/bookings/{bookingId}/handling-events`: the server closes with `1008`.
- Drop `exclude_none=True` from the dump in `app/feed.py`: frames gain null `voyageNumber` and `amount` fields the fixture never had, and the first-frame and schema checks in `uv run pytest` fail.

## For deeper coverage

- Lukasz Dynowski & Marcin Dulak, *Learning API Styles* (O'Reilly, 2025): how much of the transport a framework hides or exposes, the axis used here to pick the native library over FastAPI's wrapper.
- *Cloud Native Design Patterns*, "Communications" chapter: running two independent listeners cooperatively in one process instead of two deployables.
- *Cloud Native Design Patterns*, "WebSockets at Scale" chapter: the ping/pong and close-code vocabulary the native library exposes.
- [Python `websockets` documentation](https://websockets.readthedocs.io/): `serve`, `ServerConnection`, `ConnectionClosed` and its subclasses, and the ping/pong API.
- [RFC 6455: The WebSocket Protocol](https://www.rfc-editor.org/rfc/rfc6455): the `1008` Policy Violation close code and the wider close-code vocabulary.
