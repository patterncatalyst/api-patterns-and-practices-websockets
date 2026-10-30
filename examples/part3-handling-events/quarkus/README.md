# Part 3 "Handling It": Quarkus (WebSockets Next)

Implements `operations.receiveHandlingEvent` from
[`contracts/asyncapi.yaml`](../../../contracts/asyncapi.yaml): one WebSocket
connection per booking, server-to-client push only. On open, the server
replays the three `HandlingEvent`s in
[`../fixtures/handling-events.json`](../fixtures/handling-events.json) (the
same canonical fixture the Python/FastAPI sibling app replays) in order, as
JSON text frames. There is no client-to-server message on this channel.

- **Endpoint:** `ws://localhost:8080/ws/v1/bookings/{bookingId}/handling-events`
- **Model:** `HandlingEvent` (record) + `HandlingEventType` (enum) in
  `src/main/java/.../handlingevents/`, matching the contract's field and
  enum-member names exactly. Jackson (pulled in transitively by
  `quarkus-websockets-next`) serializes each record to JSON; optional fields
  (`voyageNumber`, `amount`) are omitted when absent.
- **Push mechanism:** `@OnOpen` returns `Multi<HandlingEvent>`: WebSockets
  Next treats that as a persistent server-push stream for the connection's
  lifetime (see the
  [WebSockets Next reference guide](https://quarkus.io/guides/websockets-next-reference),
  "Streams"). `HandlingEventFeed` loads the fixture once at startup.

## The fixture is not duplicated here

`../fixtures/handling-events.json` is the single source of truth (the Python
sibling app reads the identical file). `pom.xml`'s
`copy-handling-events-fixture` execution copies it onto the classpath
(`/fixtures/handling-events.json`) at build time via a path relative to this
module's basedir (`../fixtures`), with no manual copy step for a local build.
`Containerfile` reproduces the same relative layout inside the build stage so
the identical `pom.xml` reference resolves there too. The copy itself is a
generated build artifact, not a second checked-in copy (see `../../.gitignore`'s
`fixtures` entry).

## Running it

```shell
./mvnw quarkus:dev
```

Dev UI: <http://localhost:8080/q/dev/>.

## Running the conformance test

The test validates every fixture-derived `HandlingEvent` against the
contract-derived JSON Schema, which is a generated, gitignored build
artifact. Regenerate it first:

```shell
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./mvnw -q test
```

## Packaging

```shell
./mvnw package
java -jar target/quarkus-app/quarkus-run.jar
```

Or build the container image from the **repo root** (the build context needs
to reach `examples/part3-handling-events/fixtures/`):

```shell
docker build -f examples/part3-handling-events/quarkus/Containerfile \
  -t part3-handling-events-quarkus .
docker run --rm -p 8080:8080 part3-handling-events-quarkus
```

## Manually inspecting a frame

Using the shared harness (`examples/_lib/lib.sh`):

```shell
source examples/_lib/lib.sh
ensure_websocat
wait_for_ws localhost:8080 /ws/v1/bookings/BKG1/handling-events
ws_first_frame "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
```

The first frame is the fixture's `RECEIVE` event
(`evt_01HZY3M1V8X4D7Q6B2N9C0T5E8`). The server does not look up or validate
`bookingId` against the fixture's events in this chapter: any path segment
upgrades the connection and replays the same fixed sequence; a later chapter
adds real per-booking lookup.

## Observability

`quarkus-opentelemetry` is on the classpath but the OTel SDK is disabled by
default (`quarkus.otel.sdk.disabled=true` in `application.properties`). Set
`QUARKUS_OTEL_SDK_DISABLED=false` and point `OTEL_EXPORTER_OTLP_ENDPOINT` at
a reachable collector to turn tracing on.

## Related guides

- [WebSockets Next](https://quarkus.io/guides/websockets-next-reference):
  Implementation of the WebSocket API with enhanced efficiency and usability.
- [OpenTelemetry](https://quarkus.io/guides/opentelemetry): Use
  OpenTelemetry to trace services.
