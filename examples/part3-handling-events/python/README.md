# Ch9 example — Python native `websockets` + FastAPI

Implements `contracts/asyncapi.yaml`'s `handlingEvents` channel: one
WebSocket connection per booking at
`/ws/v1/bookings/{bookingId}/handling-events`, pushing the shared fixture's
three `HandlingEvent`s (RECEIVE, LOAD, CUSTOMS — see
`../fixtures/handling-events.json`) in order as soon as the upgrade
completes. The Quarkus sibling (`../quarkus/`) replays the identical
fixture, byte-for-byte, so the two stacks are directly comparable.

## Architecture

Two listeners, one process, one event loop (`app/main.py`):

- **`app/ws_server.py`** — the WebSocket endpoint, built on the native
  `websockets` library (`websockets.asyncio.server.serve`), not
  FastAPI/Starlette's bundled WebSocket support. That's the point of this
  chapter: see `../../_docs/09-python-native-websockets.md`. Listens on
  `WS_HOST:WS_PORT` (default `0.0.0.0:8081` — `8080` is the Quarkus
  sibling's port).
- **`app/http_app.py`** — a small FastAPI app (`/healthz`, `/`) for
  HTTP/app lifecycle, run under uvicorn on `HTTP_HOST:HTTP_PORT` (default
  `0.0.0.0:8082`).

The contract documents a `handling-events.v1` subprotocol and a `token`
query parameter for a future auth chapter (Ch17); neither is enforced here
— see the docstring on `app/ws_server.py:create_server` for why requiring
the subprotocol today would reject plain clients (websocat, browsers)
for no behavior this example implements yet.

## Build-time model generation

`app/models_generated.py` is **generated, gitignored, never committed**.
`datamodel-code-generator`'s AsyncAPI input support is unreliable for this
contract, so generation goes through the extracted JSON Schema instead
(that's what `../../../scripts/extract-message-schema.py` is for — it
inlines `HandlingEvent`'s `$ref`s into one self-contained Draft 2020-12
document):

```bash
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./scripts/generate-models.sh
```

The app imports the generated `HandlingEvent` Pydantic v2 model from
`app.models_generated`; `app/feed.py` validates every fixture event against
it and emits the model's own `model_dump_json(exclude_none=True)` as the
wire frame — one source of truth for both validation and serialization, so
there's no hand-written JSON-building code to drift from the contract.

## Run it

```bash
uv sync --group dev
./scripts/generate-models.sh
uv run pytest                 # conformance test (see tests/test_contract.py)

uv run python -m app.main     # starts both listeners
```

Then, from the repo root, with `examples/_lib/lib.sh` sourced:

```bash
source examples/_lib/lib.sh
ensure_websocat
wait_for_ws localhost:8081 /ws/v1/bookings/BKG1/handling-events
frame="$(ws_first_frame "ws://localhost:8081/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events")"
schema_validate "$frame" build/handling-event.schema.json
```

The first frame is the RECEIVE event, with fields and values identical to
`../fixtures/handling-events.json[0]`.

## Container build

Build from the **repo root** (the context needs to reach `contracts/` and
the shared `fixtures/` directory):

```bash
docker build -f examples/part3-handling-events/python/Containerfile \
  -t ch09-handling-events-python .
docker run --rm -p 8081:8081 -p 8082:8082 ch09-handling-events-python
```

The image runs the same two build-time steps as local dev (extract →
generate) before building the runtime venv; see the Containerfile for
details and the UBI 10 base image pin.

## Pinned versions

| Tool / package | Version |
| --- | --- |
| Python | 3.15 (3.15.0 locally) |
| uv | 0.13.1 |
| fastapi | 0.146.0 |
| websockets | 17.2 |
| uvicorn[standard] | 0.54.0 |
| opentelemetry-distro | 0.66b1 (declared; not yet wired into the entrypoint — no exporter is configured for this example, see scope note below) |
| datamodel-code-generator (dev) | 0.86.0 |
| jsonschema (dev) | 4.26.0 |
| pytest (dev) | 9.1.1 |
| UBI base image | `registry.access.redhat.com/ubi10/python-314-minimal:10.2-1791928506` |

`opentelemetry-distro` is declared per the dependency list for this example
but intentionally not wrapped around the entrypoint yet: without an OTLP
exporter package configured, wrapping `python -m app.main` with
`opentelemetry-instrument` would default to trying to export traces nowhere
useful. Observability wiring is Ch23's job, not Ch9's — this example keeps
the dependency available without reaching ahead of scope.
