---
title: "AsyncAPI: Giving a Socket a Contract"
order: 5
part: "Contract-first for Sockets"
description: "AsyncAPI 3 as the single source of truth for a WebSocket channel's messages, generated into both stacks."
duration: "21 min read"
---

## Learning objectives

By the end of this chapter you can:

- Explain the four top-level sections of an AsyncAPI 3 document (`servers`, `channels`, `operations`, `components`) and how each one references the layer below it.
- Read `contracts/asyncapi.yaml`'s `handlingEvents` channel and `receiveHandlingEvent` operation to determine a channel's address, direction, and message shape without running any code.
- Explain why AsyncAPI 3 moved `operations` out of `channels`, unlike 2.x's nested `publish`/`subscribe`, and what that separation buys once a channel carries more than one direction.
- Validate `contracts/asyncapi.yaml` with `npx @asyncapi/cli validate` and tell an `information`-level governance note apart from a failing error.
- State what "contract-first" means for this site at this stage (validated and reviewed, not yet code-generating) and the gap that leaves open until two independently built stacks are shown to agree with it.

## Why this matters

Decoding a WebSocket frame byte by byte and naming the shipping domain this site pushes over that frame covered the mechanics and the vocabulary. Neither wrote down, in a form a machine can check, what a client is allowed to expect from the socket: which address to open, what message shows up on it, and what shape that message takes. `contracts/asyncapi.yaml` is that document. It is the WebSockets analog of the REST site's OpenAPI file and the gRPC site's `.proto` package: one artifact, reviewed before either stack writes a handler, that both the Quarkus and Python examples generate from and validate against. This chapter reads that file section by section and runs the one command that proves it is well-formed.

## Why a socket needs a contract

A REST endpoint publishes its contract in the request method, the path, and a response schema a client can diff against reality one call at a time. A gRPC service publishes it as a compiled `.proto` that produces the client stub directly, so the contract and the code are the same artifact. A WebSocket connection has neither. It is one long-lived, bidirectional pipe, opened once, over which either side can emit a message at any point in the connection's lifetime. Nothing about HTTP's request/response pairing applies past the upgrade handshake: there is no status code to inspect per message, no URL that names "the current message," no framework-level schema validation unless something is told what the valid messages are.

That gap is where undocumented sockets fail. A client guesses a message's shape from a sample payload a teammate pasted into chat, the server adds a field, and the client's parser either drops it without complaint or throws on a value it has never seen; the connection itself stays open and healthy, so nothing about the transport signals that the contract between the two ends broke. The failure shows up as a UI rendering stale data or a background worker crashing on a `None` it didn't expect, minutes or days after the field shipped. A contract does not stop the server from changing its message shape. It gives the change a diff to review before it goes out and a document the client's test suite can assert against instead of a payload example frozen in a chat thread.

AsyncAPI is built for exactly this shape of problem: one or more participants pushing and receiving asynchronous messages over a long-lived channel, where "channel" might be a WebSocket, a Kafka topic, an MQTT topic, or an AMQP queue. This site uses one channel, one message, one direction; this chapter's job is to show that even the smallest AsyncAPI document is still the same object model a larger one would use, not a special case of it.

## AsyncAPI 3 in one page

An AsyncAPI 3 document is four top-level sections, each describing one layer of the system, each referencing the layer below it:

- **`servers`**: where a connection is made: host, protocol (`ws`, `wss`, `kafka`, `mqtt`, ...), and any connection-level detail like required headers or query parameters.
- **`channels`**: an address a connection is scoped to, and the messages that can flow on it. A channel is not a direction; it is a place.
- **`operations`**: the direction. Each operation names an `action` (`send` or `receive`, from the perspective of the *application* described by the document, not of "client" or "server") against one channel, and lists which of that channel's messages apply.
- **`components`**: the reusable building blocks, chiefly `messages` and `schemas`, referenced by `$ref` from channels and operations rather than inlined wherever they're used.

{% include excalidraw.html file="05-asyncapi-object-model" alt="The AsyncAPI 3 object model drawn against this site's own contract: servers.local at the top, binding to channels.handlingEvents below it, which binds to operations.receiveHandlingEvent, which references components.messages.HandlingEvent, whose payload references components.schemas.HandlingEvent, which in turn references the HandlingEventType, Location, and Money schemas." caption="Figure 5.1: the AsyncAPI 3 object model: servers, channels, operations, components, each referencing the one below it." %}

That `operations` live outside `channels` matters before the next section, because it is the one thing that changed most visibly between AsyncAPI 2.x and 3.x, and because getting it backwards makes this chapter's cross-references read wrong. A channel in 3.x is direction-agnostic: `handlingEvents` names an address and the messages that can appear on it, nothing more. That this particular channel only ever pushes server-to-client is stated once, separately, by the one operation that references it.

## Walking our contract

`contracts/asyncapi.yaml` opens with `asyncapi: 3.0.0` and an `info` block naming the feed and describing what it replaces: polling the REST booking service for a status that has not changed:

```yaml
asyncapi: 3.0.0

info:
  title: Handling Events WebSocket Feed
  version: 0.1.0
  description: >
    The live handling-event feed for the shipping/cargo domain shared with the
    REST and gRPC sibling sites (Booking, Cargo, Location/UN-LOCODE, Route,
    Leg, Operation, Money-as-decimal-string). A client opens a WebSocket
    connection scoped to one booking and receives a server-to-client push
    every time a handling event ... is recorded for that booking's cargo.
```

### `servers`

One server, `local`, named for the development environment rather than a role: there is only one deployment target so far, so the name says what it is instead of inventing a `dev`/`staging`/`prod` distinction the site doesn't have yet:

```yaml
servers:
  local:
    host: localhost:8080
    protocol: ws
    bindings:
      ws:
        method: GET
        query:
          type: object
          properties:
            token:
              type: string
          required:
            - token
        headers:
          type: object
          properties:
            Sec-WebSocket-Protocol:
              type: string
              const: handling-events.v1
```

The `ws` binding is where protocol-specific detail that the core AsyncAPI spec has no vocabulary for lives: the HTTP method the upgrade request uses, a required `token` query parameter, and a `Sec-WebSocket-Protocol` header pinned to the constant `handling-events.v1`. AsyncAPI calls this family of extensions "bindings" precisely because they bind the protocol-agnostic core model to one specific transport's quirks, the same role HTTP bindings play on an OpenAPI operation, generalized to cover transports that aren't HTTP underneath.

### `channels`

One channel, `handlingEvents`, naming the address and the parameter embedded in it:

```yaml
channels:
  handlingEvents:
    address: {% raw %}/ws/v1/bookings/{bookingId}/handling-events{% endraw %}
    title: Handling events for a booking
    servers:
      - $ref: '#/servers/local'
    parameters:
      bookingId:
        description: >
          The booking whose handling events this connection watches. Matches
          the Booking.id identifier shape shared with the REST and gRPC
          sites: a bkg_ prefix followed by a 26-character ULID.
        examples:
          - bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
    messages:
      handlingEvent:
        $ref: '#/components/messages/HandlingEvent'
```

Three things to notice here, each a direct consequence of the object model above. The `{% raw %}{bookingId}{% endraw %}` path parameter is declared under `parameters` with a pattern and an example, the same way an OpenAPI path parameter would be: AsyncAPI borrows the mechanism wholesale rather than reinventing path-templating. The channel's `servers` list is what binds this specific channel to the `local` server declared above; a document with multiple servers could scope different channels to different ones. And `channels.handlingEvents.messages` only *lists* `HandlingEvent` by reference; it does not say who sends it or who receives it. That's an operation's job, next.

### `operations`

One operation, `receiveHandlingEvent`, and this is where direction finally enters the document:

```yaml
operations:
  receiveHandlingEvent:
    action: receive
    channel:
      $ref: '#/channels/handlingEvents'
    title: Receive a handling event
    summary: >
      The client receives a HandlingEvent push whenever one is recorded for
      the watched booking.
    messages:
      - $ref: '#/channels/handlingEvents/messages/handlingEvent'
```

`action: receive` reads from the perspective of the application this document describes: here, the client. The server pushes; the client receives. There is no corresponding `send` operation on this channel, and that absence is not an oversight to fill in later: `contracts/README.md` states it directly: "the server never expects a client-to-server message on this channel." A reader of this contract alone, with no access to either implementation, already knows the channel is one-way, because the document declares exactly one operation against it and that operation's action is `receive`.

### `components`

`components.messages.HandlingEvent` wraps a content type and a reference to the schema that constrains the JSON payload:

```yaml
components:
  messages:
    HandlingEvent:
      name: HandlingEvent
      title: Handling event
      contentType: application/json
      payload:
        $ref: '#/components/schemas/HandlingEvent'

  schemas:
    HandlingEvent:
      type: object
      properties:
        eventId:
          type: string
          pattern: '^evt_[0-9A-Za-z]{26}$'
        bookingId:
          type: string
          pattern: '^bkg_[0-9A-Za-z]{26}$'
        cargoId:
          type: string
          pattern: '^crg_[0-9A-Za-z]{26}$'
        eventType:
          $ref: '#/components/schemas/HandlingEventType'
        location:
          $ref: '#/components/schemas/Location'
        occurredAt:
          type: string
          format: date-time
        registeredAt:
          type: string
          format: date-time
        voyageNumber:
          type: string
        amount:
          $ref: '#/components/schemas/Money'
      required:
        - eventId
        - bookingId
        - cargoId
        - eventType
        - location
        - occurredAt
        - registeredAt
```

Every one of those nested `$ref`s points at a schema the gRPC and REST sites already made a convention, not something invented fresh for this site. `HandlingEventType` is a string enum (`RECEIVE`, `LOAD`, `UNLOAD`, `CUSTOMS`, `CLAIM`, `HOLD`, `DELIVERED`) with a `HANDLING_EVENT_TYPE_UNSPECIFIED` zero value the server never sends, the same `*_UNSPECIFIED`-zero-value convention the gRPC site's `BookingState` enum uses so a deserializer always has a safe default. `Location` is a UN/LOCODE string (`^[A-Z]{2}[A-Z2-9]{3}$`, e.g. `USNYC`). `Money` is a decimal string (`^\d+\.\d{2}$`, e.g. `'125.00'`), never a JSON number: the same Money-as-decimal-string convention that keeps a binary float from drifting a price's last cent on either the REST or gRPC sibling site, applied here to an amount that rides a WebSocket frame instead of an HTTP body or a protobuf field. A client reading this schema inherits the whole series' domain vocabulary without this contract having to redefine a single one of those shapes from scratch.

## AsyncAPI 3 vs 2.x

Readers coming from an AsyncAPI 2.x document, or from an OpenAPI background where paths and operations live together, will look for a `publish`/`subscribe` pair nested under each channel and not find one. That nesting is exactly what 3.x removed. In 2.x, a channel object carried its own `publish` and `subscribe` keys directly, so the channel and its direction were one piece of YAML; adding a second direction to the same channel meant adding a second key to the same object, and a reader had to infer from the key's name (`publish` is "the application publishes to this channel," which inverts intuitively for who's producing versus consuming) which side was doing what.

3.x pulls `operations` out to its own top-level section, each one a standalone object with an explicit `action: send` or `action: receive` and a `$ref` back to the channel it applies to. The concrete effect for this contract: `handlingEvents` is a channel with no notion of direction baked into it at all, and `receiveHandlingEvent` is the one, separately-declared fact that the direction on this channel runs server-to-client. A second operation, say, a future client-to-server acknowledgment, would be a second entry under `operations`, referencing the same channel, without touching the channel definition itself. That separation is also what makes the object model reusable across transports that don't share HTTP's publish/subscribe metaphor at all: an operation's `action` means the same thing whether the channel underneath it is a WebSocket, a Kafka topic, or an MQTT topic, because the verb lives in the operation, not borrowed from one protocol's vocabulary and stretched to fit the others.

## Validating the contract

{% include codetabs.html langs="Quarkus|Python" %}

```bash
# Quarkus side of the toolchain contributes nothing to validation —
# the contract is plain YAML, checked once, upstream of either stack.
npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml
```

```bash
# Python side: identical command, same contract, same gate.
npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml
```

Both tabs run the same command because validation is stack-agnostic: it checks the YAML against the AsyncAPI 3 meta-schema and resolves every internal `$ref`, which happens once, before either stack exists. `6.2.1` is pinned rather than floating: `contracts/README.md` tracks `npm view @asyncapi/cli version` and documents re-checking it before bumping the pin, the same pinned-and-reviewed posture the gRPC site takes with `buf`'s CLI version. `npx -y` fetches that exact version without requiring a local global install, so the command runs the same way on a laptop and in CI.

## One contract, two stacks

{% include excalidraw.html file="05-contract-to-two-stacks" alt="contracts/asyncapi.yaml sits above two independent implementations, Quarkus on WebSockets Next and Python on FastAPI/Starlette plus the websockets library, each validating against and eventually generating from the same file, with a dashed bidirectional arrow between them labeled same channel, same message shape." caption="Figure 5.2: one contract, two stacks: neither implementation reads the other's source." %}

This site commits to two independent implementations of the same channel: Quarkus on WebSockets Next, Python on FastAPI/Starlette plus the native `websockets` library. Neither is a port of the other's source code. What keeps a client written against one interchangeable with a client written against the other is that both answer to this one file. A Quarkus `@OnTextMessage` handler and a Python connection coroutine will each, once the examples land, deserialize the identical `HandlingEvent` JSON shape, reject the identical malformed payload, and reject a `bookingId` that doesn't match `^bkg_[0-9A-Za-z]{26}$`, not because either implementation imports the other, but because both are implementations of the same reviewed document.

This stage stops short of generating code from the contract. `contracts/README.md` is explicit about the gap: schema-mirroring types are "hand-kept in sync with the schemas here until a generator step lands with the examples." That is a narrower claim than the gRPC site's, where a `.proto` compiles directly into the Java and Python classes both services use; there is no equivalent compiler step for a hand-maintained AsyncAPI document the way there is for Protobuf, so "contract-first" here means "the contract is reviewed and validated first, and the code that follows it is checked against it," not "the contract mechanically produces the code." The payoff is still real at this stage: a reviewer reading a pull request against `asyncapi.yaml` sees the whole message shape change in one diff, before any handler on either stack has to be touched to match it.

## On the wire

Running the pinned CLI against the file as it stands today:

```bash
$ npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml

File contracts/asyncapi.yaml is valid but has (itself and/or referenced documents) governance issues.
Information
contracts/asyncapi.yaml
 1:11  information  asyncapi-latest-version  The latest version of AsyncAPI is not used. It is recommended update to the "3.1.0" version.  asyncapi

✖ 1 problem (0 errors, 0 warnings, 1 info, 0 hints)
```

Zero errors, zero warnings: one informational note that a newer minor version of the spec exists, which this contract is not yet pinned to. That distinction matters for reading CI output later: an `information`-level line is not a failed gate. The CI step runs this exact command and only fails the build on a non-zero exit from an actual error, which an informational note does not trigger.

The schema this validates against governs a real JSON payload. Here is the shape `components.schemas.HandlingEvent` describes, next to a message that satisfies it:

```yaml
# the contract (excerpt)
eventType:
  $ref: '#/components/schemas/HandlingEventType'
location:
  $ref: '#/components/schemas/Location'
amount:
  $ref: '#/components/schemas/Money'
required:
  - eventId
  - bookingId
  - cargoId
  - eventType
  - location
  - occurredAt
  - registeredAt
```

```json
{
  "eventId": "evt_01HZY3M1V8X4D7Q6B2N9C0T5E8",
  "bookingId": "bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A",
  "cargoId": "crg_01HZY3N4F6K1W9P3R7T0Y2Q8M5",
  "eventType": "LOAD",
  "location": "NLRTM",
  "occurredAt": "2026-03-14T08:12:00Z",
  "registeredAt": "2026-03-14T08:14:31Z",
  "voyageNumber": "MSC-0417W",
  "amount": "125.00"
}
```

Every field in that JSON traces back to a schema property one section up: `eventId`/`bookingId`/`cargoId` match their `evt_`/`bkg_`/`crg_` prefix patterns, `eventType` is a member of the `HandlingEventType` enum, `location` is a UN/LOCODE, `amount` is a decimal string rather than `125.0` or `125`, and `voyageNumber` is present here because this is a `LOAD` event: the schema marks it optional precisely because a `CUSTOMS` or `CLAIM` event carries no voyage. `registeredAt` sits a little after `occurredAt`, which the contract's description calls out as the normal case when registration lags the physical event rather than an error in either implementation's clock handling.

## Where this goes next

This contract is the thing message design works against directly: the message shape itself, and why `HandlingEvent` stays one flat shape instead of a union of per-event-type payloads. Versioning and evolution then takes up message versioning: how an additive field differs from a breaking one, and what happens to this exact schema the day it needs to change. The `/ws/v1/...` prefix on this channel's address is already doing the heavy lifting for breaking changes: `contracts/README.md` states that a breaking change to the message shape becomes `/ws/v2/...`, the same versioned-path convention the REST site uses for its resources, which means versioning inherits a working answer to "what happens when this schema needs an incompatible change" rather than inventing one from nothing. The validate-only CI gate wired in now keeps this exact command running on every push from here forward; the full regenerate-and-diff gate that would catch drift between the contract and either stack's generated code waits until there is generated code on both sides for it to compare.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>A validated contract with no running service is a smaller claim than the equivalent contract-first chapter makes on the REST or gRPC sibling sites, and that gap reflects where this contract stands before either stack exists. A WebSocket's failure mode without a contract is not a 404 or a compile error; it is a connection that stays open and healthy while the two ends disagree about what a message means, a disagreement surfacing only when a field a client never learned to expect reaches it. Writing the schema down and running <code>asyncapi validate</code> against it before either stack exists catches the version of that problem a reviewer can catch on paper: a typo'd pattern, a missing required field, a <code>$ref</code> to nothing. It does not catch the version only a running client and a running server can surface together: a Quarkus handler and a Python handler disagreeing at runtime about a field neither one's code path exercises in its own tests. That is exactly the gap closed once both stacks exist, and exactly why today's gate is pinned to "validates" rather than overclaiming "generates identically" before a second implementation exists to check it against.</p></div>

## For deeper coverage

- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022): the message-exchange pattern vocabulary this contract's `channels`/`operations`/`components` split is an instance of.
- Higginbotham, J., *Principles of Web API Design* (Addison-Wesley, 2021): contract-first review discipline, applied here to a channel instead of a REST resource.
- *Cloud Native Design Patterns*, "API Registry" chapter: one authoritative, versioned home for a contract with compatibility rules gating changes, the same role this chapter's `asyncapi validate` gate plays for `asyncapi.yaml`.
- *Cloud Native Design Patterns*, "API Management" chapter: governing a published contract's lifecycle once more than one consumer depends on it.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `servers`/`channels`/`operations`/`components` object model this chapter walks section by section.
