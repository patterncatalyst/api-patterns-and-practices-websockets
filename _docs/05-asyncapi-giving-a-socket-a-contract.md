---
title: "AsyncAPI: Giving a Socket a Contract"
order: 5
part: "Contract-first for Sockets"
description: "AsyncAPI 3 as the single source of truth for a WebSocket channel's messages, validated once and followed by both stacks."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Name the four top-level sections of an AsyncAPI 3 document (`servers`, `channels`, `operations`, `components`) and how each references the layer below it.
- Read a channel's address, direction and message shape from `contracts/asyncapi.yaml` without running any code.
- Explain why AsyncAPI 3 moved `operations` out of `channels`, and what that buys once a channel carries more than one direction.
- Validate the contract with `npx @asyncapi/cli validate` and tell an `information` note from a failing error.
- State how each stack follows the contract: Python generates its model from it, Quarkus hand-keeps a record that its build checks against the same schema.

## Why this matters

A frame has bytes and an opcode. Nothing in it says which address to open, which messages arrive on it, or what shape they take. `contracts/asyncapi.yaml` writes that down in a form a machine can check. It is the WebSocket counterpart of an OpenAPI file or a `.proto` package: one artifact, reviewed before either stack writes a handler, that both the Quarkus and Python examples answer to.

{% include excalidraw.html file="05-asyncapi-object-model" alt="The AsyncAPI 3 object model: servers.local binds to channels.handlingEvents, which binds to operations.receiveHandlingEvent, which references components.messages.HandlingEvent and from there components.schemas.HandlingEvent with its HandlingEventType, Location and Money schemas." caption="Figure 5.1: the AsyncAPI 3 object model: servers, channels, operations, components, each referencing the one below it." %}

## Why a socket needs a contract

A REST endpoint publishes its contract in a method, a path and a response schema. A gRPC service compiles it into a client stub. A WebSocket connection has neither: it is one long-lived, bidirectional pipe, and after the upgrade handshake there is no status code per message, no URL naming the current message, and no schema validation unless something is told what a valid message is.

Undocumented sockets fail quietly. A client guesses a message's shape from a payload pasted into chat, the server adds a field, and the client's parser drops it or throws on a value it has never seen. The connection stays open and healthy, so the transport never signals the break. It shows up minutes or days later as a stale screen or a worker crashing on a `None`. A contract doesn't stop the server from changing a message. It gives the change a diff to review, and gives the client's tests a document to assert against.

AsyncAPI describes exactly this: participants pushing and receiving asynchronous messages over a long-lived channel, whether that is a WebSocket, a Kafka topic, an MQTT topic or an AMQP queue. This contract has one channel, one message and one direction, and uses the same object model a large document would.

## AsyncAPI 3 in one page

| Section | Describes | Notes |
|---|---|---|
| `servers` | Where a connection is made | Host, protocol (`ws`, `wss`, `kafka`, `mqtt`), and connection-level detail such as required query parameters or headers |
| `channels` | An address and the messages that can flow on it | A place, not a direction |
| `operations` | The direction | An `action` of `send` or `receive`, from the perspective of the application the document describes, against one channel |
| `components` | Reusable `messages` and `schemas` | Referenced by `$ref` instead of inlined |

In AsyncAPI 2.x a channel carried its own `publish` and `subscribe` keys, so a channel and its direction were one piece of YAML, and `publish` read backwards for anyone asking who was producing. In 3.x a channel names an address and its messages and nothing more. A separate operation states the direction, with an explicit `action` and a `$ref` back to the channel. A second direction later, such as a client acknowledgment, becomes a second operation against the same channel without touching the channel definition. The `action` also means the same thing whether the channel underneath is a WebSocket, a Kafka topic or an MQTT topic.

## Walking the contract

The document opens with the version and an `info` block:

```yaml
asyncapi: 3.0.0

info:
  title: Handling Events WebSocket Feed
  version: 0.1.0
```

### servers

One server, `local`, named for what it is. The site has one deployment target, so it doesn't invent `dev`, `staging` and `prod`:

```yaml
servers:
  local:
    host: localhost:8080
    protocol: ws
```

The `ws` binding holds what the core spec has no vocabulary for: the HTTP method of the upgrade request, a required `token` query parameter, and the `Sec-WebSocket-Protocol` values the server accepts.

```yaml
    bindings:
      ws:
        method: GET
        query:
          type: object
          properties:
            token:
              type: string
              description: >
                Placeholder auth token passed as a query parameter. Treated
                as opaque by this contract; the auth chapter specifies the
                token format and validation.
          required:
            - token
```

```yaml
        headers:
          type: object
          properties:
            Sec-WebSocket-Protocol:
              type: string
              enum:
                - handling-events.v1
                - handling-events.v1+json
                - handling-events.v1+protobuf
```

`handling-events.v1` and `handling-events.v1+json` are equivalent and name the JSON encoding. `handling-events.v1+protobuf` selects the binary encoding of the same fields. A connection negotiates exactly one.

### channels

One channel, `handlingEvents`, with its address and the parameter embedded in it:

```yaml
channels:
  handlingEvents:
    address: /ws/v1/bookings/{bookingId}/handling-events
    title: Handling events for a booking
    description: >
      One WebSocket connection per booking. The server pushes a
      `HandlingEvent` message each time a new handling event is recorded for
      the booking identified by `bookingId`; the server never expects a
      client-to-server message on this channel.
    servers:
      - $ref: '#/servers/local'
```

```yaml
    parameters:
      bookingId:
        description: >
          The booking whose handling events this connection watches. Matches
          the `Booking.id` identifier shape shared with the REST and gRPC
          sites: a `bkg_` prefix followed by a 26-character ULID
          (`^bkg_[0-9A-Za-z]{26}$`).
        examples:
          - bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A
    messages:
      handlingEvent:
        $ref: '#/components/messages/HandlingEvent'
```

The `{bookingId}` path parameter is declared under `parameters` with a description and an example, the way an OpenAPI path parameter is. The channel's `servers` list binds it to `local`; a document with several servers could scope channels to different ones. `messages` lists `HandlingEvent` by reference and says nothing about who sends it. That is an operation's job.

### operations

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
    description: >
      Server-to-client push only; this channel defines no client-to-server
      operation. One `HandlingEvent` message is sent per recorded event, in
      the order the server registers them.
    tags:
      - name: handling-events
    messages:
      - $ref: '#/channels/handlingEvents/messages/handlingEvent'
```

`action: receive` reads from the perspective of the described application, here the client. The server pushes and the client receives. There is no `send` operation, so the channel is one-way: a reader of this document alone knows the server never expects a client-to-server message on it.

### components

The message wraps a content type and a reference to the schema that constrains the JSON payload:

```yaml
components:
  messages:
    HandlingEvent:
      name: HandlingEvent
      title: Handling event
      summary: A single handling event recorded against a booking's cargo.
      contentType: application/json
      tags:
        - name: handling-events
      payload:
        $ref: '#/components/schemas/HandlingEvent'
```

The schema's properties reference the shared shapes by `$ref` and keep the time and voyage rules in their descriptions:

```yaml
        eventType:
          $ref: '#/components/schemas/HandlingEventType'
        location:
          $ref: '#/components/schemas/Location'
        occurredAt:
          type: string
          format: date-time
          description: When the handling event physically happened.
        registeredAt:
          type: string
          format: date-time
          description: >
            When the handling event was recorded by the system. Greater than
            or equal to `occurredAt`; the two differ whenever registration is
            delayed (e.g. a paper manifest keyed in after the fact).
        voyageNumber:
          type: string
          description: >
            Optional carrier voyage number in effect when the event was
            recorded (e.g. a LOAD or UNLOAD event). Absent for events that
            are not tied to a specific voyage (e.g. CUSTOMS, CLAIM).
          examples:
            - MSC-0417W
        amount:
          $ref: '#/components/schemas/Money'
```

The `required` list names the fields every message carries:

```yaml
      required:
        - eventId
        - bookingId
        - cargoId
        - eventType
        - location
        - occurredAt
        - registeredAt
```

The nested schemas reuse the conventions of the REST and gRPC sibling books. `HandlingEventType` is a string enum with a `HANDLING_EVENT_TYPE_UNSPECIFIED` zero value the server never sends. `Location` is a UN/LOCODE (`^[A-Z]{2}[A-Z2-9]{3}$`, for example `USNYC`). `Money` is a decimal string (`^\d+\.\d{2}$`, for example `'125.00'`), never a JSON number. A client reading the schema inherits the whole domain vocabulary without the contract redefining any of it. The next chapter covers why each shape was chosen.

## One contract, two stacks

{% include excalidraw.html file="05-contract-to-two-stacks" alt="contracts/asyncapi.yaml above two independent implementations, Quarkus on WebSockets Next and Python on the websockets library. Both are checked against the same file, and a dashed arrow between them is labeled same channel, same message shape." caption="Figure 5.2: one contract, two stacks: neither implementation reads the other's source." %}

Quarkus on WebSockets Next and Python on the native `websockets` library are independent implementations of the same channel. Neither is a port of the other. A client written against one works against the other because both answer to this file.

The two stacks follow the contract differently, because AsyncAPI has no compiler step the way Protobuf does:

| Stack | How it follows the contract |
|---|---|
| Python | `scripts/extract-message-schema.py` inlines the `$ref`s of `components.schemas.HandlingEvent` into one JSON Schema. `datamodel-code-generator` turns that into the Pydantic model, and every emitted frame is serialized by it |
| Quarkus | A hand-kept `HandlingEvent` record and `HandlingEventType` enum mirror the schema field for field. The build validates fixture events against the same extracted schema and checks that the enum has exactly the contract's members, in order |

So "contract-first" here means the contract is reviewed and validated first, and the code is checked against it, not that the contract mechanically produces both stacks. A pull request against `asyncapi.yaml` shows the whole message change in one diff.

The `/ws/v1/` prefix on the address is the escape hatch for incompatible change: a breaking change to the message shape becomes `/ws/v2/...`, the counterpart of the REST series' versioned resource paths and the gRPC series' versioned packages.

> **Decision**
>
> Write the AsyncAPI document before the handlers, validate it on every push, and make each stack prove it follows the file: generate from it where a generator is reliable, check against the extracted schema where it isn't. Without a contract, a socket's failure mode is a connection that stays open and healthy while the two ends disagree about a message. Validation catches what a reviewer can catch on paper: a mistyped pattern, a missing required field, a `$ref` to nothing. Only a running client and server catch the rest.

> **🤖 Explore with your agent**
>
> "In contracts/asyncapi.yaml, add an optional `carrierRemarks` string to components.schemas.HandlingEvent without touching `required`. Run the AsyncAPI validation from the repo root, then run python3 -I scripts/extract-message-schema.py build/handling-event.schema.json and confirm the new property appears in the extracted schema. Do not edit either stack's code."
>
> Check: the validate command exits 0 with only the `asyncapi-latest-version` information note, and `grep carrierRemarks build/handling-event.schema.json` finds the property.

## Build, run, observe

From the repo root:

```bash
npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml
```

The contract is plain YAML, so validation is the same for both stacks. It checks the file against the AsyncAPI 3 meta-schema and resolves every internal `$ref`. `npx -y` fetches the pinned version without a global install, so the command runs the same on a laptop and in CI.

```text
File contracts/asyncapi.yaml is valid but has (itself and/or referenced documents) governance issues.
Information
contracts/asyncapi.yaml
 1:11  information  asyncapi-latest-version  The latest version of AsyncAPi is not used. It is recommended update to the "3.1.0" version.  asyncapi

✖ 1 problem (0 errors, 0 warnings, 1 info, 0 hints)
```

Zero errors and zero warnings. The one `information` line says a newer minor version of the spec exists; it is not a failed gate, and the CI step fails only on a non-zero exit from an actual error.

To see both stacks follow the file, run the shared example (`examples/part3-handling-events`):

```bash
./verify.sh
```

It brings up Quarkus on port 8080 and Python on 8081, captures the first frame each pushes on `/ws/v1/bookings/{bookingId}/handling-events`, validates it against the schema extracted from the contract, and compares the two frames field by field. It prints `PASS:` when both stacks agree.

- Point a `$ref` in `contracts/asyncapi.yaml` at a schema name that doesn't exist: `validate` reports an error and exits non-zero.
- Change `amount` in `fixtures/handling-events.json` to `"125"`, which breaks the `Money` pattern: the Python stack's generated Pydantic model raises a validation error when it loads the fixture, and the Quarkus contract test rejects the event against the extracted schema.

## For deeper coverage

- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022): the message-exchange pattern vocabulary that the `channels`, `operations` and `components` split instantiates.
- Higginbotham, J., *Principles of Web API Design* (Addison-Wesley, 2021): contract-first review discipline, applied here to a channel instead of a REST resource.
- *Cloud Native Design Patterns*, "API Registry" chapter: one authoritative, versioned home for a contract with compatibility rules gating changes, the role `asyncapi validate` plays here.
- *Cloud Native Design Patterns*, "API Management" chapter: governing a published contract's lifecycle once more than one consumer depends on it.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `servers`, `channels`, `operations` and `components` object model.
