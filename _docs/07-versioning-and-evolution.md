---
title: "Versioning and Evolution"
order: 7
part: "Contract-first for Sockets"
description: "Classify contract changes as safe or breaking, pick a versioning lever, and retire an old version without cutting off a connected client."
duration: "16 min read"
---

## Learning objectives

By the end of this chapter you can:

- Classify a change to `HandlingEvent` or its channel as breaking or safe with one test: does any code compiled before the change have to look at the part that's different.
- Explain why an open WebSocket connection has no REST or unary-gRPC analog for renegotiating a contract, and name the three client populations a rolling deploy creates.
- Choose among channel-path, subprotocol and message-field versioning, and say what each does to a connection that is already open.
- Make an enum deserializer degrade an unrecognized value to `UNSPECIFIED` instead of failing.
- Size and close a dual-publish window using observed connection lifetimes and an application-defined close code in the `4000` to `4999` range.

## Why this matters

A REST client makes one request, gets one response and is gone; its next request meets whatever the server looks like then. A WebSocket opens once and stays open for as long as a booking is worth watching, minutes or days. Every message the server pushes has to make sense to code that was compiled before the connection opened. So the question for a second release of the contract is what happens to a client already running against the first.

## What counts as breaking

A gRPC message carries field numbers, and an old reader skips a number it doesn't recognize by construction. JSON over a WebSocket carries field names, and whether an old reader skips an unknown name is a property of its deserializer, not of the wire format. A plain Jackson `ObjectMapper` fails on an unrecognized property unless `FAIL_ON_UNKNOWN_PROPERTIES` is disabled; the `ObjectMapper` Quarkus manages disables it by default (`quarkus.jackson.fail-on-unknown-properties`). A Pydantic model ignores extras by default and raises only with `extra="forbid"`. Tolerance has to be configured on both sides, and every "safe" change below is safe only because the consumers are built to tolerate it.

| Part of the contract | Safe | Breaking |
|---|---|---|
| Field | Add an optional field (`carrierRemarks`). An old reader configured to ignore unknown properties drops it | Remove a field a client reads (`amount`); the client now handles `null` for a value the schema guaranteed |
| Enum | Add a member (`REROUTED`), if every consumer maps an unrecognized value to a generic path | Repurpose a member in place: `CUSTOMS` keeps its name and changes meaning, and nothing fails while the client draws the wrong conclusion |
| Shape | Add a channel path version (`/ws/v2/...`) beside the untouched `/ws/v1/...` | Change a type or unit in place: `amount` from the string `"125.00"` to the number `125.00`, or `occurredAt` from ISO 8601 to a Unix timestamp |
| Requirement | Add a second subprotocol token while the first still serves, so a client that offers only the old one still connects | Make an optional field required: `voyageNumber` is absent on `CUSTOMS` by design, and rejecting its absence fails producers that never set it |

{% include excalidraw.html file="07-evolution-gate" alt="A matrix of contract changes in four columns: Field, Enum, Shape, Requirement. The safe row holds the additions (optional field, new enum member, new path version, second subprotocol). The breaking row holds the mutation of the same part (removed field, repurposed member, changed type, newly required field), each linked by a dashed line to the safe cell above it." caption="Figure 7.1: the evolution gate, four kinds of contract change, each with a safe addition above and the breaking mutation of the same thing below." %}

The call is never whether a diff is big or small. If any code compiled before the change has to look at the part that's different, the change is breaking. Changing `Money` from `type: string` with a `^\d+\.\d{2}$` pattern to `type: number` keeps the field name, its position and its meaning, and still breaks every already-connected client that parses `amount` as a string. That is why the decimal-string convention exists: a type this fragile deserves a representation that can't drift into an almost-compatible shape unnoticed.

## The already-connected client

A client that connected at 9:00 is still on that connection at 10:00, and the next day if nothing closes it. After a 9:15 deploy, every message it receives is whatever the new server code sends, over a socket it opened against the old contract and never renegotiated. Three consequences follow:

1. **Three populations exist at once for the whole rollout.** Clients on an instance not yet replaced; clients that were disconnected when theirs was replaced and reconnected to an old or new instance depending on rollout progress; and clients connecting for the first time after it finishes. All three must be served correctly at every moment.
2. **There is no mid-connection renegotiation.** Subprotocol, extensions and path are fixed at the handshake. The server can propose a move with a close frame and reason, but can't force when the client acts on it.
3. **"Already connected" can mean days.** A mobile client that opens a socket at launch and holds it until force-quit outlives a short deprecation window. Sizing a window against deploy duration instead of observed connection lifetime is the commonest way to underestimate this.

A gRPC stream or a long-poll loop meets a version of the same problem. On a WebSocket feed it is the common case, because every connection is long-lived by design.

## Versioning levers: path, subprotocol, field

A breaking change has to reach new clients without cutting off connected ones. The three places a version can live differ in when an open connection finds out.

**Put the version where the change is: the path for a different channel, the subprotocol for a different payload contract on the same channel, a message field for a change that must reach connections already open.**

| Lever | What changes | Effect on an open connection | Cost |
|---|---|---|---|
| Channel path (`/ws/v1/...` to `/ws/v2/...`) | The channel itself: a new message shape, a different parameter set | None. A connection's path is fixed at the handshake, so v1 keeps receiving what the v1 route sends | Two route handlers side by side |
| Subprotocol (`Sec-WebSocket-Protocol`, for example `handling-events.v2`) | The payload contract on the same address | None. The handler reads the negotiated token and serializes to match, as an HTTP endpoint reads `Accept` | One handler branching per connection; reconnect to pick up the new shape |
| Message field (`schemaVersion` in the JSON) | The payload, underneath connections that can't be relied on to reconnect | Takes effect immediately, with no new handshake | Every handler branches on `schemaVersion` forever |

The contract already commits to the path: a breaking change to the message shape becomes `/ws/v2/...`. It also fixes the subprotocol family. `servers.local.bindings.ws` lists `handling-events.v1`, `handling-events.v1+json` and `handling-events.v1+protobuf`, where the `+json` or `+protobuf` suffix selects the encoding within version 1. In either stack the connection handler can read the negotiated subprotocol per connection, and a second path is a second route.

## Enum evolution and the unspecified zero

`HANDLING_EVENT_TYPE_UNSPECIFIED` is never sent, and it is tempting to read that as built-in forward compatibility: anything unrecognized becomes `UNSPECIFIED`. It isn't. The zero value gives the type a safe default before a value is assigned: a field initialized before the first message, a default argument, a test placeholder. It doesn't rescue a future value a client doesn't know yet.

Protobuf enums are open: an unrecognized integer is preserved, so a reader compiled before a new member existed doesn't fail on it. A JSON string enum is closed by default in both stacks, so an unrecognized string is a validation failure, not a fallback to the zero value, unless the deserialization path maps it. Adding `REROUTED` is safe only if every consumer already has that mapping. Otherwise adding a member breaks every client not yet updated, and nothing in the deploy flags it.

| Stack | Unknown property | Unknown enum value |
|---|---|---|
| Jackson | Fails by default on a plain `ObjectMapper`; disable `FAIL_ON_UNKNOWN_PROPERTIES` or use `@JsonIgnoreProperties(ignoreUnknown = true)` | Fails unless `READ_UNKNOWN_ENUM_VALUES_USING_DEFAULT_VALUE` is enabled with `@JsonEnumDefaultValue` on the zero member, or a `@JsonCreator` factory maps it |
| Pydantic | Ignored by default; `extra="forbid"` raises | Raises `ValidationError` unless a `field_validator(..., mode="before")` maps unknown values to `HANDLING_EVENT_TYPE_UNSPECIFIED` |

Put the mapping in one place, not at each call site, so a future `REROUTED` lands as `UNSPECIFIED` and takes whatever path a handler already has for it instead of tearing down the message or the connection. The reference `HandlingEventType` mirrors the contract and sets no fallback; a consumer that has to survive new members adds one.

## Deprecation and dual-publish windows

A dual-publish window is the period during which a server serves both the old and new shape at once (both subprotocol tokens, both paths, or an old field beside its replacement), so no already-connected client sees a break mid-connection.

Size it against the connection population, not the deploy. A twenty-minute deploy says nothing about how long the longest-lived connection stays open: a dashboard tab left overnight, a worker holding a socket for a long job, a mobile client that reconnects only on relaunch. Take a histogram of this feed's connection durations. The window has to outlast whatever was open when the new shape began, which means watching the old version's active-connection count reach zero, not trusting a calendar date.

{% include excalidraw.html file="07-connected-client-migration" alt="A dual-publish window in three lanes across time: the server, a v1 client connected before the change, and a v2 client connecting after. At deploy time the server serves v1 and v2 together and the v1 client keeps reading v1. When the window closes the server serves v2 only, closes the lingering v1 client with a deprecation close code, and the client reconnects on v2." caption="Figure 7.2: a connection opened before the deploy outlives it; the dual-publish window keeps that connection correct until it reconnects or the server closes it as planned." %}

Close the window in two steps:

1. Stop offering the old version to anything new. Drop the deprecated subprotocol token from new handshakes, or stop routing new connections to the old path. Connections that already negotiated it run untouched.
2. When telemetry shows zero live connections on the old version, an actual zero and not "probably none left", close any stragglers with an application-defined close code in `4000` to `4999`, such as `4010` meaning "this channel version is retired, reconnect on `/ws/v2/...`". A generic `1001` gives a client's retry logic nothing to act on.

> **Decision**
>
> Pick the lever by what an open connection may keep assuming: the path for a structural break, the subprotocol for a payload break where a reconnect is acceptable, a message field for a change that must reach connections already open. Size the dual-publish window by observed connection lifetime, and close it in two steps: stop offering the old version, then close stragglers with a code a reconnect loop can act on.

> **🤖 Explore with your agent**
>
> "In contracts/asyncapi.yaml, add REROUTED to components.schemas.HandlingEventType and an optional carrierRemarks string to HandlingEvent, leaving `required` unchanged. Then check how examples/part3-handling-events/quarkus deserializes HandlingEventType and unknown properties, and tell me which of the two changes would break a client built the way the Java record and enum are written. Do not change handler code."
>
> Check: `npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml` exits 0, and the reply names the enum (no fallback on an unknown string) as the risk and states the unknown-property behavior from the Jackson configuration it found.

## Build, run, observe

Evolution is a contract change first. After every edit:

```bash
npx -y @asyncapi/cli@6.2.1 validate contracts/asyncapi.yaml
cd examples/part3-handling-events
./verify.sh
```

`verify.sh` brings up both stacks (Quarkus on port 8080, Python on 8081) and checks that each pushes frames that validate against the schema extracted from the contract, and that the two agree. It prints `PASS:` when they do.

- Add `carrierRemarks` as an optional string to `components.schemas.HandlingEvent`: validation still passes and `required` is unchanged. This is a safe addition.
- Add `REROUTED` to `HandlingEventType`: the Python model picks it up when it is regenerated on build, while the hand-kept Quarkus enum has no `REROUTED` until you add it. The Quarkus enum test compares against its own copy of the eight member names, so it still passes: a hand-kept mirror drifts silently.

## For deeper coverage

- J. J. Geewax, *API Design Patterns* (Manning, 2021): the compatibility and versioning patterns behind the breaking and safe classification.
- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022): message-level evolution patterns for a channel that can't renegotiate mid-connection.
- *Cloud Native Design Patterns*, "Versioning & Evolution" chapter: the path, subprotocol and payload-field levers at the level of an API's whole lifecycle.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `servers` and `channels` structure that makes `/ws/v1/...` and `/ws/v2/...` two independently addressable routes.
- [Semantic Versioning](https://semver.org/): the additive-versus-breaking vocabulary, mapped here onto a schema.
