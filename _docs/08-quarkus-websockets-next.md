---
title: "Quarkus WebSockets Next"
order: 8
part: "Building It"
description: "Implementing the handling-event feed on Quarkus WebSockets Next."
duration: "20 min read"
---

## Learning objectives

By the end of this chapter you can:

- Implement a `@WebSocket` endpoint whose `@OnOpen` method returns a `Multi<HandlingEvent>` to push a known sequence of events to a connecting client.
- Explain why `HandlingEventWebSocket` declares no `@OnTextMessage` or `@OnClose` method, tracing each omission back to the contract's `action: receive` operation and the endpoint's actual resource lifecycle.
- Choose between returning a declarative `Multi`/`Uni` and calling `WebSocketConnection.sendText` imperatively, based on whether the data to push is already fully known at connection time.
- Configure Jackson, via `@JsonInclude(NON_NULL)`, `Instant` serialization, and enum naming, so a `HandlingEvent` record serializes to match `contracts/asyncapi.yaml` without a custom serializer.
- Verify a running endpoint's output against a JSON Schema generated from the contract, using `HandlingEventContractTest` rather than a hand-read comparison.

## Why this matters

The AsyncAPI contract fixed the channel; message design fixed the message shape; versioning and evolution fixed what a version change may and may not do to a client already connected. None of that work ran a socket. This chapter does: `examples/part3-handling-events/quarkus` is a complete, buildable Quarkus module that implements `operations.receiveHandlingEvent` from `contracts/asyncapi.yaml`: one class, one record, one enum, and a test that checks the three against the schema the contract describes. The whole implementation is `HandlingEventWebSocket`, nineteen lines excluding imports and comments, and the reason it stays that short is the subject of this chapter: `quarkus-websockets-next` turns "replay a sequence of events onto an open connection" into a method signature, not a hand-rolled state machine.

## The endpoint and its path parameter

A Quarkus WebSockets Next endpoint is a plain CDI bean annotated `@WebSocket`, with the connection's address as the annotation's one required attribute:

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

`path` is the same `{% raw %}{bookingId}{% endraw %}` template `channels.handlingEvents.address` declares in the contract, character for character: `/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events`. That is not a coincidence the implementation has to maintain by discipline alone; it is the one string a reviewer diffs against the contract to confirm this class still answers the channel it claims to. `@PathParam String bookingId` on the `onOpen` method parameter binds the matched path segment to a plain `String`: WebSockets Next resolves it the same way a JAX-RS `@PathParam` resolves a REST path segment, by name match against the template, not by position. Nothing in this class parses the path manually or reaches into a raw upgrade request to pull `bookingId` out of a URI; the framework does that resolution before `onOpen` is ever invoked, and a malformed `bookingId` that doesn't match the path template never reaches this method at all: it fails the route match the same way an unmatched REST path does.

The class carries exactly one field: an injected `HandlingEventFeed`. There is no connection registry, no per-session map keyed by `bookingId`, no manually managed collection of open sockets anywhere in this module. A WebSockets Next endpoint bean is not a singleton holding every connection's state in instance fields the way a naively written endpoint on an older framework might be tempted to; the runtime manages one logical endpoint invocation per connection, and state that belongs to one connection lives in that invocation's local scope (here, the `Multi` returned from `onOpen`) rather than in a field shared across every booking a client happens to watch concurrently.

## The connection lifecycle: what fires, what doesn't

WebSockets Next exposes a connection's lifecycle through three annotations a method can carry: `@OnOpen` for the upgrade completing, `@OnTextMessage` (or `@OnBinaryMessage`) for an inbound frame, and `@OnClose` for the connection ending. `HandlingEventWebSocket` declares exactly one of the three. That is not an oversight the example will fill in later: it is the direct, literal consequence of `operations.receiveHandlingEvent`'s `action: receive`, which traces back to `contracts/asyncapi.yaml` declaring no corresponding `send` operation on this channel. `contracts/README.md` states the same fact in prose: "the server never expects a client-to-server message on this channel." A method annotated `@OnTextMessage` would be dead code here: nothing in the contract describes a message shape for it to deserialize, and nothing about this channel's purpose (a live push feed, not a request/response exchange riding a socket) calls for a client to send anything after the upgrade completes. Leaving it off is not a gap to close; it is the implementation matching what the contract already said.

`@OnClose` is absent for a related but distinct reason: this endpoint keeps no per-connection resource that needs releasing. `HandlingEventFeed` is `@ApplicationScoped` and loaded once at application startup, shared read-only across every connection this endpoint ever serves; there is no per-booking subscription object, no open file handle, no registered listener that `onOpen` allocates and something downstream has to tear down when the client disconnects or the server half-closes. A later chapter that adds a live, per-booking event source (a Kafka consumer group scoped to one booking's topic, say) is exactly the chapter where `@OnClose` becomes necessary: that is where a connection ending has a side effect to clean up. This chapter's fixture-replay example has none, so it has no `@OnClose` method; adding one here would scaffold for a feature this chapter doesn't need yet.

{% include excalidraw.html file="08-ws-endpoint-lifecycle" alt="The HandlingEventWebSocket class and its connection lifecycle. @OnOpen onOpen(@PathParam bookingId) is implemented and returns Multi<HandlingEvent>. @OnTextMessage is shown as not declared, because the channel is receive-only per the contract. @OnClose is shown as not declared, because no per-connection state is kept. Below, WebSocketConnection's imperative sendText is shown as available but unused by this handler; HandlingEventFeed loads the fixture once at startup via @PostConstruct and is called from onOpen; Jackson, pulled in transitively by quarkus-websockets-next, serializes each HandlingEvent to JSON." caption="Figure 8.1: one lifecycle callback implemented, because the contract declares one operation on this channel." %}

## Returning a Multi vs. calling sendText

WebSockets Next gives an `@OnOpen` (or `@OnTextMessage`) method two ways to push data to a client, and `HandlingEventWebSocket` uses the first:

The declarative form is the one in this chapter's example: return a `Multi<T>` (or a `Uni<T>` for a single reply) from the callback method, and the runtime subscribes to it, converts every emitted item to a text frame, and sends each frame in emission order for as long as the `Multi` keeps producing. `Multi.createFrom().iterable(feed.events())` builds exactly such a stream from the fixture's three-event `List<HandlingEvent>`: no explicit send call appears anywhere in the method body, because returning the `Multi` *is* the instruction to push its items.

The imperative alternative is `WebSocketConnection`, injectable into the endpoint bean (or obtainable from the callback's parameters), exposing `sendText(String)` / `sendTextAndAwait(String)` / `sendTextAndForget(String)` methods a handler calls explicitly, at a time of its own choosing, from inside any method, not only from a lifecycle callback. That shape is the one a handler needs when a push has to happen on a timer, in response to an event arriving on a completely different thread (a Kafka consumer poll, a scheduled job), or interleaved with other connection-scoped logic that a single returned `Multi` can't express. `HandlingEventWebSocket` doesn't need any of that for this chapter: the entire event sequence is already known in full, in memory, in order, the moment the connection opens, which is exactly the shape a declarative `Multi` is built for. Reaching for `WebSocketConnection.sendText` here, one call per fixture event, would replace a one-line `return` with a loop maintaining no information the `Multi` version doesn't already express: a self-inflicted imperative rewrite of what the reactive type already does.

The two are not mutually exclusive on the same endpoint. An endpoint can return a `Multi` from `@OnOpen` to establish a connection's steady-state push stream, while a separate `@OnTextMessage` method on the same class calls `WebSocketConnection.sendText` to answer one specific inbound message out of band. This chapter's endpoint doesn't need that combination because it has only the one data flow (server to client, nothing else), but the pattern matters for sizing what WebSockets Next can do before reaching for a workaround: the declarative and imperative forms compose on one connection rather than forcing an all-or-nothing choice between them.

{% include excalidraw.html file="08-multi-push-flow" alt="A client opens a WebSocket connection to /ws/v1/bookings/{id}/handling-events. @OnOpen's onOpen method returns Multi.createFrom().iterable(feed.events()). The WebSockets Next runtime subscribes to that Multi and, as it emits three items in order (RECEIVE at USNYC, LOAD at USNYC, CUSTOMS at NLRTM), sends one text frame per item to the client, which receives the three frames in fixture order. After the third item the Multi completes, but the connection itself stays open; nothing in this flow closes the socket." caption="Figure 8.2: one Multi, three items, three ordered text frames; completion of the stream does not close the connection." %}

## Serializing HandlingEvent: Jackson, enums, Instants, optionals

Nothing in `HandlingEventWebSocket` calls an `ObjectMapper` directly. `quarkus-websockets-next` pulls in Quarkus's managed Jackson integration transitively, and a `Multi<HandlingEvent>` (or any POJO/record type) returned from a callback is serialized to JSON automatically before being sent as a text frame: the same "return a typed object, the framework handles the wire format" shape a JAX-RS resource method gets from `quarkus-resteasy-reactive-jackson` for a REST response body. The `HandlingEvent` record carries the serialization contract entirely in its own declaration:

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

Four decisions are worth pulling apart, because each one maps directly to a line in `contracts/asyncapi.yaml`'s `components.schemas.HandlingEvent`. `location` and `amount` are plain `String` fields, not nested objects, because the contract defines `Location` and `Money` as `type: string` with a `pattern` (a UN/LOCODE and a decimal string respectively), not as structured types with their own properties. Modeling either as a custom class here would invent structure the contract doesn't have and Jackson would have to serialize back down to a bare string to match it; a `String` field needs no custom serializer because the wire shape and the Java shape are already the same shape.

`eventType` is `HandlingEventType`, a plain Java enum:

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

Jackson's default enum serialization writes `Enum.name()` as a JSON string, and this enum's constant names are written in exactly the SCREAMING_SNAKE spelling `components.schemas.HandlingEventType.enum` lists in the contract: `RECEIVE`, `LOAD`, `UNLOAD`, and so on. That alignment means no `@JsonProperty` annotation is needed on a single constant: the contract's enum values and the Java constant names were chosen to be identical strings, so Jackson's unconfigured default behavior already produces the contract's wire format. `HANDLING_EVENT_TYPE_UNSPECIFIED` carries the same `*_UNSPECIFIED`-zero-value convention the gRPC sibling site's enums use: it exists as a safe default for a deserializer that has to represent "no value recognized yet," and the server-side fixture replay in this chapter never emits it, exactly as the contract's description says it won't.

`occurredAt` and `registeredAt` are `java.time.Instant`. Quarkus's managed `ObjectMapper` registers the `JavaTimeModule` and, by default, disables `SerializationFeature.WRITE_DATES_AS_TIMESTAMPS`, so an `Instant` serializes as an ISO-8601 string (`"2026-01-15T08:00:00Z"`) rather than a raw epoch number, matching the contract's `format: date-time` on both fields without any configuration this module has to add itself. `HandlingEventContractTest` builds its own comparison `ObjectMapper` with the identical two settings specifically so the test's serialization matches what the running application produces, rather than testing against a mapper configured differently.

Finally, `voyageNumber` and `amount` are both nullable `String` fields, and `@JsonInclude(JsonInclude.Include.NON_NULL)` on the record omits either one from the JSON entirely when it's `null`, rather than emitting `"voyageNumber": null`. That matches the contract precisely: neither field appears in `components.schemas.HandlingEvent.required`, and the fixture shows why the distinction matters in practice: the `RECEIVE` event has neither field, the `LOAD` event carries `voyageNumber` but not `amount`, and the `CUSTOMS` event carries `amount` but not `voyageNumber`. Without `@JsonInclude(NON_NULL)`, Jackson's default behavior would write `null` literals for both absent fields on every event, which is valid JSON but not what the contract describes: a client written strictly against the schema's `required` list has no obligation to handle a `null` on a field the schema never promised would be present at all, only a field that's either absent or correctly typed.

## Loading the fixture once, replaying it per connection

`HandlingEventFeed` is the piece that makes `HandlingEventWebSocket`'s body a one-line `return` instead of a parsing routine:

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
                        "Fixture resource not found on classpath: " + FIXTURE_RESOURCE + " — expected "
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

    public List<HandlingEvent> events() {
        return events;
    }
}
```

`@PostConstruct` fires once, when the `@ApplicationScoped` bean is first created: in practice, once per application lifetime, not once per connection. The same shared `events` list backs every `onOpen` invocation this endpoint ever handles, which is correct for this chapter's fixed, deterministic replay and would need to change the moment a later chapter scopes the event sequence to the specific `bookingId` a connection names rather than one fixture shared by every connection regardless of which booking it asked for. `pom.xml`'s `copy-handling-events-fixture` execution is what makes `FIXTURE_RESOURCE` resolvable at all: `examples/part3-handling-events/fixtures/handling-events.json` is the single file both the Quarkus and Python stacks replay, kept one level above either module's source tree rather than duplicated into each, and the Maven resources plugin copies it onto this module's classpath at `generate-resources` time so neither a local build nor the Containerfile's containerized build needs a manual step to find it.

## Why WebSockets Next, not the legacy extension

Every Quarkus example in this series uses `quarkus-websockets-next`, not the older `quarkus-websockets` extension Quarkus has carried since before the reactive-native rewrite. The difference that matters for this chapter's class is the programming model itself: the legacy extension follows the JSR 356 (`javax.websocket`/`jakarta.websocket`) annotation set (`@ServerEndpoint`, `@OnOpen`, `@OnMessage`, `@OnClose` on a class registered through a `ServerEndpointConfig`), built around a blocking, one-thread-per-connection execution model inherited from the servlet-era WebSocket API it standardized. WebSockets Next's `@WebSocket`, by contrast, is built on Quarkus's Vert.x-based reactive core from the start, and that's exactly why `onOpen` can return a `Multi<HandlingEvent>` and have the runtime drive it on an event loop rather than blocking a dedicated thread for the connection's entire lifetime: the reactive type *is* the integration point, not a compatibility shim bolted onto an API designed around blocking I/O. A legacy-extension endpoint doing the equivalent push would call `Session.getAsyncRemote().sendText(...)` once per event from inside a loop: the imperative shape this chapter's `WebSocketConnection.sendText` alternative mirrors, minus the option to express the whole stream as one reactive value. Picking WebSockets Next up front means every example in this series, including the ones later chapters add for backpressure and liveness, has a `Multi`/`Uni`-shaped API to reach for instead of relearning a blocking session API that Quarkus itself has moved past.

## Checking the code against the contract test

`HandlingEventContractTest` is plain JUnit (no `@QuarkusTest`, no started container) because what it checks is the serialization behavior of the production `HandlingEvent` record and `HandlingEventType` enum, not the running endpoint:

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
void handlingEventTypeHasAllEightContractMembers() {
    List<String> contractMembers = List.of(
            "HANDLING_EVENT_TYPE_UNSPECIFIED", "RECEIVE", "LOAD", "UNLOAD",
            "CUSTOMS", "CLAIM", "HOLD", "DELIVERED");

    HandlingEventType[] actual = HandlingEventType.values();
    assertEquals(8, actual.length, "HandlingEventType must have exactly 8 members");

    List<String> actualNames = Arrays.stream(actual).map(Enum::name).toList();
    assertEquals(contractMembers, actualNames,
            "HandlingEventType members must match the contract's enum, in order");
}
```

`schema` is loaded from `build/handling-event.schema.json`, generated from `contracts/asyncapi.yaml` by `scripts/extract-message-schema.py`: a JSON Schema derived mechanically from the contract's own `components.schemas.HandlingEvent`, not hand-copied into the test by a developer who could drift it from the source document over time. The first test takes every event in the shared fixture, serializes it with the identical `ObjectMapper` configuration the running endpoint uses, and validates the resulting JSON against that generated schema; the second test asserts `HandlingEventType`'s eight constants match the contract's `enum` list by name, in order, so a constant renamed or reordered on the Java side fails a test before it ever reaches a running connection. Neither assertion touches a socket. Together they close the loop that versioning and evolution left abstract (a Jackson `ObjectMapper` that fails closed on an unrecognized shape only protects a client if the server never produces that unrecognized shape in the first place) by checking the server's actual serialized output against the contract on every build, not only reading the contract and trusting the Java code to match it.

## On the wire

`examples/part3-handling-events/verify.sh` brings the Quarkus and Python stacks up via `compose.yaml`, waits for each socket to accept a connection, and opens one against the Quarkus service at `ws://localhost:8080{% raw %}/ws/v1/bookings/{bookingId}/handling-events{% endraw %}` using `websocat`, capturing the first pushed frame. Run it directly:

```bash
bash examples/part3-handling-events/verify.sh
```

Or open the same connection by hand once the app is running (`mvn quarkus:dev` from `examples/part3-handling-events/quarkus`, or the Containerfile image):

```bash
websocat "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
```

The first frame (fixture event zero, the `RECEIVE` event) arrives the instant the connection opens, with no client message required to trigger it:

```json
{"eventId":"evt_01HZY3M1V8X4D7Q6B2N9C0T5E8","bookingId":"bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A","cargoId":"crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5","eventType":"RECEIVE","location":"USNYC","occurredAt":"2026-01-15T08:00:00Z","registeredAt":"2026-01-15T08:00:05Z"}
```

Neither `voyageNumber` nor `amount` appears: `@JsonInclude(NON_NULL)` omits both, exactly as described above, because this fixture entry carries neither. Two more frames follow on the same connection, in fixture order: a `LOAD` event carrying `voyageNumber` but no `amount`, then a `CUSTOMS` event carrying `amount` but no `voyageNumber`. `verify.sh` checks this exact first frame field-by-field against the fixture and against `build/handling-event.schema.json`, then repeats the same check against the Python implementation on port 8081 and asserts the two parsed frames agree field for field, proving, the way a validated contract alone couldn't, that two independently written implementations of `receiveHandlingEvent` produce the identical message.

## Where this goes next

This chapter's endpoint replays a closed, in-memory fixture: the entire event sequence exists before the first connection ever opens, which is why a single `Multi.createFrom().iterable(...)` call is enough. The next hands-on chapter changes that: a live source (a Kafka topic or an in-process event bus, keyed by `bookingId` rather than shared across every connection) means `HandlingEventFeed.events()` stops being a precomputed `List` and becomes a subscription a connection opens and a later `@OnClose` has to tear down: the exact gap this chapter named and chose not to fill ahead of need. The polyglot comparison that follows puts the Python implementation of this same contract next to this one, side by side, to compare the `Multi`-returning shape here against Python's own mechanism for the identical push; this chapter stayed single-stack so the Quarkus-specific lifecycle, injection, and serialization machinery could be read without a second language's syntax competing for attention on the same page. Part 4's chapters on backpressure and liveness are where `WebSocketConnection`'s imperative `sendText` family and this chapter's declarative `Multi` both get revisited under conditions (a slow consumer, an idle connection a middlebox might reap) this chapter's three-event fixture never produces.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>`HandlingEventWebSocket` returns a declarative <code>Multi&lt;HandlingEvent&gt;</code> from <code>@OnOpen</code> rather than injecting <code>WebSocketConnection</code> and calling <code>sendText</code> in a loop, because the entire event sequence this chapter replays is already known, in full, in memory, the moment a connection opens: exactly the shape a reactive stream is built to express in one line instead of an explicit send per item. It declares no <code>@OnTextMessage</code> method because <code>contracts/asyncapi.yaml</code>'s one operation on this channel is <code>action: receive</code>, not because an inbound handler was deferred for later; and no <code>@OnClose</code> method because no per-connection resource exists yet for one to release. Choosing WebSockets Next over the legacy <code>quarkus-websockets</code> extension is what makes the first of those three choices available at all: a <code>Multi</code> returned from a lifecycle callback has no equivalent on an extension built around JSR 356's blocking, one-thread-per-connection session API. None of this is free-standing trust in the Java code matching the contract by inspection: <code>HandlingEventContractTest</code> serializes every fixture event with the same Jackson configuration the running endpoint uses and validates the result against a JSON Schema generated from <code>contracts/asyncapi.yaml</code> itself, so a field renamed, an enum constant reordered, or an optional field that stops being omitted fails a fast, non-containerized test before it ever reaches a socket a client has connected to.</p></div>

## For deeper coverage

- Lukasz Dynowski & Marcin Dulak, *Learning API Styles* (O'Reilly, 2025): a style-by-style view of how a channel's programming model (here, a reactive `Multi` over a WebSocket) differs from its request/response counterparts.
- *Cloud Native Design Patterns*, "Communications" chapter: the push-vs-pull and connection-lifecycle trade-offs behind choosing a reactive stream over an imperative send loop.
- *Cloud Native Design Patterns*, "WebSockets at Scale" chapter: the backpressure and liveness concerns this chapter's three-event fixture doesn't yet exercise, which Part 4 picks up.
- [Quarkus WebSockets Next reference guide](https://quarkus.io/guides/websockets-next-reference): the `@WebSocket`, `@OnOpen`, and `WebSocketConnection` APIs this chapter's endpoint is built from.
- [RFC 6455: The WebSocket Protocol](https://www.rfc-editor.org/rfc/rfc6455): the connection lifecycle (`CONNECTING`/`OPEN`/`CLOSING`/`CLOSED`) `@OnOpen`/`@OnClose` map onto.
