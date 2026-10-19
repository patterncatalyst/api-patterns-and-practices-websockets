# Part 5 "Performance" — Quarkus (WebSockets Next)

Forked from the LAYOUT of
[`examples/part4-connection/quarkus`](../../part4-connection/quarkus) (pom,
`@WebSocket` endpoint, `HandlingEvent` record/enum/feed, Containerfile
build-context-from-repo-root, `HandlingEventContractTest`) — but NOT its
connection-concern code (JWT auth, heartbeats, backpressure, the malformed-
frame error envelope): this part is about wire ENCODING, not connection
hardening, so those stay out of scope here. The same `handlingEvents`
channel (`operations.receiveHandlingEvent`,
[`contracts/asyncapi.yaml`](../../../contracts/asyncapi.yaml)) — one
WebSocket connection per booking, replaying the shared fixture on open, then
staying open — now negotiates which of TWO wire encodings carries that
replay. The Python/`websockets`-library sibling app
([`../python`](../python)) implements the identical behavior against the
same contract and the same proto; see that app's README/docstrings for the
other side of every convention below.

- **Endpoint:** `ws://localhost:8090/ws/v1/bookings/{bookingId}/handling-events`
  (port **8090** — distinct from part3/part4's 8080 so both can run at once).
- **Model:** `HandlingEvent` / `HandlingEventType` are byte-for-byte copies
  of part3/part4's — this part adds no new message content, only a second
  wire encoding of the same shape.

## Encoding negotiation (DRQ-026)

A client picks the wire encoding via `Sec-WebSocket-Protocol`, offering one
or more of the three values `contracts/asyncapi.yaml` declares:

| Client offers                  | Server selects (echoed back)   | Wire encoding                                  |
|---------------------------------|----------------------------------|-------------------------------------------------|
| `handling-events.v1+protobuf`  | `handling-events.v1+protobuf`  | Protobuf **binary** frames (opcode `0x2`)        |
| `handling-events.v1+json`      | `handling-events.v1+json`      | JSON **text** frames (opcode `0x1`) — same as part3/part4 |
| `handling-events.v1` (bare)    | `handling-events.v1`           | JSON **text** frames — equivalent to `+json`     |
| nothing                        | *(none negotiated)*            | JSON **text** frames — the pre-Part-5 default    |

`quarkus.websockets-next.server.supported-subprotocols` (application.properties)
lists all three; Vert.x picks the first entry in THAT list the client also
offered and echoes it back in the `101` response.
`HandlingEventPerformanceWebSocket#onOpen` reads the result via
`WebSocketConnection#subprotocol()` and branches on it — see that class's
Javadoc for why this is an explicit `sendText`/`sendBinary` chain rather than
`return Multi<...>` (the framework's own build-time dispatch code picks
text-vs-binary wiring from the `@OnOpen` method's STATIC declared return
type, which rules out one method dynamically choosing between the two per
connection).

Field VALUES are identical between the two encodings — `occurredAt` /
`registeredAt` stay RFC-3339 strings and `amount` stays a decimal string on
BOTH sides (see `contracts/handling-event.proto`'s header comment and
`HandlingEventProtoMapper`'s Javadoc) — a client decodes the same values
whichever encoding it negotiated.

## Protobuf generation

`contracts/handling-event.proto` (package `shipping.handlingevents.v1`) is
generated into `target/generated-sources/` by
`io.github.ascopes:protobuf-maven-plugin` at `generate-sources` — never
committed (see `pom.xml`'s header comment for the exact relative path
resolution, and `contracts/README.md`'s "No generated stubs are committed"
convention). Pins (kept in lockstep — see `pom.xml`'s `protobuf.version`
property comment):

- `com.google.protobuf:protobuf-java:4.36.2` (runtime)
- `com.google.protobuf:protoc:4.36.2` (compiler, downloaded by the plugin)
- `io.github.ascopes:protobuf-maven-plugin:5.1.11`

**Generated class name note:** the file declares no
`option java_outer_classname`, so `protoc` derives one from the file name
(`handling-event.proto` → `HandlingEvent`), which collides with the
`HandlingEvent` message itself declared in the same file. `protoc`'s
standard collision-avoidance rule appends `OuterClass`, so the generated,
confirmed-live class is `shipping.handlingevents.v1.HandlingEventOuterClass`,
nesting `HandlingEventOuterClass.HandlingEvent` and
`HandlingEventOuterClass.HandlingEventType` — see
`HandlingEventProtoMapper`'s Javadoc for why this wasn't "fixed" by editing
the shared, parity-gated contract file just for this one stack's naming
convenience.

## Measured frame sizes (confirmed live)

Compact (no-pretty-print) JSON vs. serialized Protobuf, same three fixture
events, same field values — protobuf runs **38–41% smaller**:

| Event                          | JSON (bytes) | Protobuf (bytes) | Reduction |
|---------------------------------|-------------:|------------------:|----------:|
| `evt_...T5E8` (RECEIVE)         |          247 |                149 |     39.7% |
| `evt_...U6F9` (LOAD)            |          267 |                156 |     41.6% |
| `evt_...V7G0` (CUSTOMS)         |          265 |                157 |     40.8% |

`HandlingEventProtoRoundTripTest#protobufFrameIsSmallerThanTheEquivalentJsonFrame`
asserts this (strictly smaller, not just "close") for every fixture event on
every test run.

## Running it

```shell
./mvnw quarkus:dev
```

Dev UI: <http://localhost:8090/q/dev/>.

## Running the conformance tests

Regenerate the contract-derived schema first (from the repo root), then run
both test classes (from this directory):

```shell
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./mvnw -q test
```

- `HandlingEventContractTest` — the JSON path: every fixture event validates
  against `build/handling-event.schema.json` (forked verbatim from part3/
  part4's test of the same name).
- `HandlingEventProtoRoundTripTest` — the Protobuf path: every fixture event
  round-trips through `toProto().toByteArray()` → `parseFrom()` →
  `fromProto()` back to an `equals()`-identical `HandlingEvent`, the
  round-tripped value ALSO validates against the same schema, and the
  Protobuf byte count is asserted strictly smaller than the JSON byte count.

## Packaging

```shell
./mvnw package
java -jar target/quarkus-app/quarkus-run.jar
```

Or build the container image from the **repo root** (the build context
needs to reach both `examples/part3-handling-events/fixtures/` and
`contracts/handling-event.proto`):

```shell
docker build -f examples/part5-performance/quarkus/Containerfile \
  -t part5-performance-quarkus .
docker run --rm -p 8090:8090 part5-performance-quarkus
```

## Self-verify (live, using the shared harness)

```shell
source ../../_lib/lib.sh
ensure_websocat

CHANNEL="/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
wait_for_ws localhost:8090 "$CHANNEL"

# JSON path: offer the +json subprotocol, read one text frame, validate it.
frame="$(websocat --protocol handling-events.v1+json -1 -n -t "ws://localhost:8090$CHANNEL")"
schema_validate "$frame" "$(pwd)/../../../build/handling-event.schema.json"

# Protobuf path: offer the +protobuf subprotocol, capture one BINARY frame.
websocat --protocol handling-events.v1+protobuf -1 -n -B "ws://localhost:8090$CHANNEL" > /tmp/first-event.pb
wc -c /tmp/first-event.pb   # strictly smaller than the JSON frame above
```

A small Java one-off (compiled against the generated proto classes under
`target/classes`) decodes `/tmp/first-event.pb` back to the same RECEIVE
event the JSON path returned, confirming both encodings carry identical
field values — see this module's test suite for the same assertion made
reproducibly (not just as a manual spot check).

## Observability

`quarkus-opentelemetry` is on the classpath but the OTel SDK is disabled by
default (`quarkus.otel.sdk.disabled=true`). Set
`QUARKUS_OTEL_SDK_DISABLED=false` and point `OTEL_EXPORTER_OTLP_ENDPOINT` at
a reachable collector to turn tracing on.

## Related guides

- [WebSockets Next](https://quarkus.io/guides/websockets-next-reference) —
  Implementation of the WebSocket API with enhanced efficiency and usability.
- [OpenTelemetry](https://quarkus.io/guides/opentelemetry) — Use
  OpenTelemetry to trace services.
