---
title: "Quarkus WebSockets Next"
order: 8
part: "Building It"
description: "Implementing the handling-event feed on Quarkus WebSockets Next with one annotated class, a Multi, and Jackson."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Implement a `@WebSocket` endpoint whose `@OnOpen` method returns a `Multi<HandlingEvent>` to push a known sequence of events.
- Bind a path template to a method parameter with `@PathParam`.
- Leave out `@OnTextMessage` and `@OnClose` when the contract and the endpoint's resources call for neither.
- Choose between returning a `Multi` or `Uni` and calling `WebSocketConnection.sendText`.
- Make a record serialize to match `contracts/asyncapi.yaml` with `@JsonInclude(NON_NULL)`, `Instant` and enum names, without a custom serializer.

## Why this matters

The contract fixed the channel and the message shape. Implementing `operations.receiveHandlingEvent` on `quarkus-websockets-next` takes one class, one record and one enum. The class is nineteen lines because replaying a sequence of events onto an open connection is a method signature, not a hand-written state machine.

## The endpoint and its path parameter

A WebSockets Next endpoint is a CDI bean annotated `@WebSocket`. The annotation's `path` is the channel address from the contract, character for character:

```java
@WebSocket(path = "/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events")
public class HandlingEventWebSocket {

    @Inject
    HandlingEventFeed feed;

    @OnOpen
    public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {
        Log.infof("handling-events connection opened for bookingId=%s; replaying %d fixture event(s)",
                bookingId, feed.events().size());
        return Multi.createFrom().iterable(feed.events());
    }
}
```

That string is the one a reviewer diffs against `channels.handlingEvents.address`. `@PathParam String bookingId` binds the matched segment by name, the way a JAX-RS `@PathParam` does. The framework resolves it before `onOpen` runs, and a path that does not match the template never reaches the method.

The class holds one injected field and no connection registry. The runtime manages one endpoint invocation per connection, so state that belongs to a connection lives in that invocation (here, the returned `Multi`), not in a field shared across every booking.

## Lifecycle callbacks: what to declare

WebSockets Next exposes the lifecycle as `@OnOpen` (upgrade completed), `@OnTextMessage` or `@OnBinaryMessage` (inbound frame) and `@OnClose` (connection ended). The endpoint declares only the first.

| Callback | Declared | Why |
|---|---|---|
| `@OnOpen` | yes | Starts the push stream. |
| `@OnTextMessage` | no | The contract has `action: receive` and no `send` operation on this channel, so there is no inbound message shape to deserialize. |
| `@OnClose` | no | `HandlingEventFeed` is `@ApplicationScoped` and read-only, so `onOpen` allocates nothing that a disconnect has to release. |

A live per-booking source, such as a Kafka consumer scoped to one booking, is where `@OnClose` becomes necessary: a connection ending then has a subscription to cancel.

{% include excalidraw.html file="08-ws-endpoint-lifecycle" alt="The HandlingEventWebSocket class with three lifecycle callbacks. Only @OnOpen is implemented and returns a Multi of HandlingEvent. @OnTextMessage and @OnClose are marked not declared. HandlingEventFeed loads the fixture once and Jackson serializes each event." caption="Figure 8.1: One lifecycle callback is implemented because the contract declares one operation on this channel." %}

## Returning a Multi or calling sendText

An `@OnOpen` or `@OnTextMessage` method has two ways to push data.

| Form | How | Use it when |
|---|---|---|
| Declarative | Return `Multi<T>` (or `Uni<T>` for one reply). The runtime subscribes, serializes each item to a text frame and sends in emission order. | The data is known when the connection opens, or is already a reactive stream. |
| Imperative | Inject `WebSocketConnection` and call `sendText`, `sendTextAndAwait` or `sendTextAndForget` from any method. | A push is driven by a timer, another thread (a Kafka poll, a scheduled job) or logic one returned `Multi` can't express. |

The fixture is fully known, in memory and in order, when the connection opens, so a `Multi` is the right shape. A loop of `sendText` calls would replace a one-line `return` with code that adds nothing. The two forms compose on one endpoint: `@OnOpen` can return a `Multi` for the steady-state stream while an `@OnTextMessage` method answers a single inbound message through `WebSocketConnection`.

{% include excalidraw.html file="08-multi-push-flow" alt="A client connects to the handling-events path. onOpen returns a Multi built from the fixture. The runtime sends three text frames in order (RECEIVE, LOAD, CUSTOMS) and the connection stays open after the Multi completes." caption="Figure 8.2: One Multi becomes three ordered text frames, and completion of the stream does not close the connection." %}

## Serializing HandlingEvent

No code in the endpoint touches an `ObjectMapper`. `quarkus-websockets-next` brings in Quarkus's managed Jackson, and each item a callback returns is serialized to JSON before it is sent. The record carries the whole serialization contract:

```java
@JsonInclude(JsonInclude.Include.NON_NULL)
public record HandlingEvent(
        String eventId,
        String bookingId,
        String cargoId,
        HandlingEventType eventType,
        String location,
        Instant occurredAt,
        Instant registeredAt,
        String voyageNumber,
        String amount) {
}
```

Each choice maps to `components.schemas.HandlingEvent`:

- **`location` and `amount` are `String`.** The contract defines `Location` (a UN/LOCODE) and `Money` (a decimal string) as `type: string` with a `pattern`. A nested class would invent structure the wire does not have.
- **`eventType` is an enum whose constants are the contract's wire values.** Jackson writes `Enum.name()` by default, so no `@JsonProperty` is needed. `HANDLING_EVENT_TYPE_UNSPECIFIED` is the zero value for a deserializer with nothing recognized yet, and the server never sends it.
- **`Instant` serializes as ISO-8601.** Quarkus's `ObjectMapper` registers `JavaTimeModule` and disables `WRITE_DATES_AS_TIMESTAMPS`, so `occurredAt` is `"2026-01-15T08:00:00Z"`, matching `format: date-time`.
- **`@JsonInclude(NON_NULL)` omits absent optionals.** `voyageNumber` and `amount` are not in `required`. The `RECEIVE` event has neither, `LOAD` has only `voyageNumber` and `CUSTOMS` has only `amount`. Without the annotation each event carries `null` literals the schema never promised.

```java
public enum HandlingEventType {
    HANDLING_EVENT_TYPE_UNSPECIFIED,
    RECEIVE,
    LOAD,
    UNLOAD,
    CUSTOMS,
    CLAIM,
    HOLD,
    DELIVERED
}
```

## Loading the fixture once

`HandlingEventFeed` is what keeps the endpoint's body a one-line `return` instead of a parsing routine:

```java
@ApplicationScoped
public class HandlingEventFeed {

    private static final String FIXTURE_RESOURCE = "/fixtures/handling-events.json";

    @Inject
    ObjectMapper objectMapper;

    private List<HandlingEvent> events;

    @PostConstruct
    void load() {
        try (InputStream in = getClass().getResourceAsStream(FIXTURE_RESOURCE)) {
            if (in == null) {
                throw new IllegalStateException(
                        "Fixture resource not found on classpath: " + FIXTURE_RESOURCE + ", expected "
                                + "pom.xml's copy-handling-events-fixture execution to have copied "
                                + "examples/part3-handling-events/fixtures/handling-events.json there "
                                + "during the generate-resources phase.");
            }
            CollectionType listOfHandlingEvent = objectMapper.getTypeFactory()
                    .constructCollectionType(List.class, HandlingEvent.class);
            events = List.copyOf(objectMapper.<List<HandlingEvent>>readValue(in, listOfHandlingEvent));
        } catch (IOException e) {
            throw new UncheckedIOException("Failed to load fixture resource: " + FIXTURE_RESOURCE, e);
        }
    }

    /** The fixture's handling events, in the exact order they appear in the file. */
    public List<HandlingEvent> events() {
        return events;
    }
}
```

The bean is `@ApplicationScoped`, and its `@PostConstruct` method reads `/fixtures/handling-events.json` from the classpath into an immutable list with the same managed `ObjectMapper` the endpoint serializes with. It runs once per application, so every connection replays the same list. That is correct for a fixed replay and changes when a later source is scoped to the `bookingId` a connection names. The Maven resources plugin copies `examples/part3-handling-events/fixtures/handling-events.json`, the file both stacks replay, onto the classpath at `generate-resources`, so a local build and the container build need no manual step.

## WebSockets Next or the legacy extension

Use `quarkus-websockets-next`, not the older `quarkus-websockets`. The legacy extension implements JSR 356 (`@ServerEndpoint`, `@OnMessage`, `Session.getAsyncRemote().sendText(...)`) on a blocking, thread-per-connection model. WebSockets Next is built on the Vert.x reactive core, which is why `onOpen` can return a `Multi` and have the runtime drive it on an event loop. Backpressure and liveness code later in the series builds on the same `Multi` and `Uni` API.

> **Decision**
>
> Return a `Multi<HandlingEvent>` from `@OnOpen` when the events to push are known or already a stream, and inject `WebSocketConnection` only when a push is driven by a timer, another thread or an inbound message. Declare a callback only when the contract or a per-connection resource needs it: no `@OnTextMessage` for a receive-only channel, no `@OnClose` until `onOpen` allocates something to release.

> **🤖 Explore with your agent**
>
> "In examples/part3-handling-events/quarkus, add an @OnTextMessage method to HandlingEventWebSocket that answers a client's text frame through WebSocketConnection.sendText while @OnOpen keeps returning the Multi. Then tell me whether contracts/asyncapi.yaml would still describe the channel, and what has to change in it first."
>
> Check: the reply should say the contract declares only `action: receive` on this channel, so a client-to-server message needs a `send` operation added to the contract before the handler.

## Build, run, observe

Run both stacks and check the first frame on each against the fixture and the schema generated from the contract:

```bash
cd examples/part3-handling-events && ./verify.sh
```

It prints `PASS: ` when the Quarkus service on port 8080 and the Python service on port 8081 push the same fields. To run Quarkus alone, start `mvn quarkus:dev` in `examples/part3-handling-events/quarkus` and connect:

```bash
websocat "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
```

The `RECEIVE` event arrives as soon as the upgrade completes, with no client message, followed by `LOAD` and `CUSTOMS`:

```json
{"eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
```

The serialization is also checked without a socket, in plain JUnit with no `@QuarkusTest` and no container: `HandlingEventContractTest` serializes every fixture event with an `ObjectMapper` configured like the endpoint's (`JavaTimeModule`, no timestamps) and validates it against `build/handling-event.schema.json`, which `scripts/extract-message-schema.py` generates from `components.schemas.HandlingEvent`.

- Remove `@JsonInclude(NON_NULL)` from `HandlingEvent`: `voyageNumber` and `amount` appear as `null` literals in the frames, which the contract never promises, and `HandlingEventContractTest` fails schema validation because both fields are typed `string`.
- Rename or reorder a `HandlingEventType` constant: the enum check in `HandlingEventContractTest`, which compares against the contract's eight member names in order, fails before any client connects.

## For deeper coverage

- Lukasz Dynowski & Marcin Dulak, *Learning API Styles* (O'Reilly, 2025): how a channel's programming model, here a reactive `Multi` over a WebSocket, differs from its request/response counterparts.
- *Cloud Native Design Patterns*, "Communications" chapter: the push-versus-pull and connection-lifecycle trade-offs behind a reactive stream over an imperative send loop.
- *Cloud Native Design Patterns*, "WebSockets at Scale" chapter: the backpressure and liveness concerns a three-event fixture does not exercise.
- [Quarkus WebSockets Next reference guide](https://quarkus.io/guides/websockets-next-reference): the `@WebSocket`, `@OnOpen` and `WebSocketConnection` APIs.
- [RFC 6455: The WebSocket Protocol](https://www.rfc-editor.org/rfc/rfc6455): the connection lifecycle that `@OnOpen` and `@OnClose` map onto.
