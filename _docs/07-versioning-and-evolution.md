---
title: "Versioning and Evolution"
order: 7
part: "Contract-first for Sockets"
description: "Evolving a socket's contract without breaking a client that's already connected."
duration: "20 min read"
---

## Learning objectives

By the end of this chapter you can:

- Classify a proposed change to `HandlingEvent` or its channel as breaking or safe, using the test "does any code compiled before this change have to look at the part that's different."
- Explain why an already-open WebSocket connection has no REST or gRPC-unary analog for contract renegotiation, and name the three populations a rolling deploy creates at once.
- Choose among channel-path, subprotocol, and message-field versioning for a given kind of change, and state what each lever does to a connection that is already open.
- Implement a defensive `HandlingEventType` deserializer (`fromWire` / `unknown_becomes_unspecified`) that degrades an unrecognized enum value to `UNSPECIFIED` instead of failing the connection.
- Size and close a dual-publish window using observed connection lifetimes and an application-defined close code in the `4000`–`4999` range.

## Why this matters

Chapter 5 built `contracts/asyncapi.yaml` and fixed the shape of one message, `HandlingEvent`, on one channel, `/ws/v1/bookings/{% raw %}{bookingId}{% endraw %}/handling-events`. Chapter 6 settled what belongs in that shape. Neither chapter answered the question that matters the moment this contract ships a second time: what happens to a client already running against version one when version one changes underneath it? A REST client makes one request, gets one response, and is gone; its next request, whenever that is, picks up whatever the server looks like by then. A gRPC unary call behaves the same way. A WebSocket connection doesn't get that luxury — it opens once and stays open for as long as a booking is worth watching, minutes or days, and every message the server pushes down it has to make sense to whatever code the client compiled before the connection opened. This chapter is about keeping that promise as the contract moves: what counts as breaking it, the three places a version number can live, why `HandlingEventType`'s unspecified zero matters more here than it looks like it should, and the one problem a socket has that nothing else in this series does — the client is already on the call when you change what you're saying.

## What counts as breaking, for a socket

A gRPC message on the wire carries field numbers, not names, and an old reader skips a field number it doesn't recognize by construction — protobuf's wire format does the forward-compatibility work without any application code written for it. JSON over a WebSocket carries field *names*, and whether an old reader skips a name it doesn't recognize is a property of whatever JSON library deserialized the message, not of the wire format. Jackson's `ObjectMapper` fails closed on an unrecognized property unless `FAIL_ON_UNKNOWN_PROPERTIES` is turned off; a Pydantic model raises a validation error on an extra field unless `model_config = ConfigDict(extra="ignore")` says otherwise. The generated classes either stack produces don't inherit permissiveness automatically — it has to be configured on the deserializer, on both sides of this contract. That single fact reframes everything below: a change this chapter calls "safe" is only safe because this site's two implementations are built to tolerate it, not because JSON itself guarantees tolerance the way protobuf does.

With that tolerance assumed — and it holds only because both stacks configure for it, which "On the wire" below shows directly — a short list of changes to `HandlingEvent`, the channel, or the subprotocol breaks an already-running client, and a longer list doesn't:

Breaking, because an old client misreads bytes it already expected to understand:

- **Removing a field a client already reads.** `voyageNumber` or `amount` disappearing from the payload isn't skipped the way an *added* field is — code that extracts it starts handling `null`/`None` for a value the schema used to guarantee was there, a code path nobody tested.
- **Changing a field's type or unit in place**, same name, different wire representation — `amount` moving from the decimal string `"125.00"` to the JSON number `125.00`, or `occurredAt` moving from an ISO-8601 string to a Unix timestamp. Every existing parser built for the old shape either can't decode the new value or decodes it into something nobody intended.
- **Repurposing an existing enum member's meaning in place.** `CUSTOMS` continuing to exist as a string but meaning something different than it did when an old client's `switch` was written against it is indistinguishable, on the wire, from no change at all — nothing fails, the client draws the wrong conclusion from every event of that type from then on.
- **Making a previously optional field required.** `voyageNumber` is absent on every `CUSTOMS` or `CLAIM` event by design; a client has code for "this field might not be there." If a later revision starts rejecting a message that's missing it, any older producer that never populated it starts failing validation it used to pass.

Safe, because an old client's deserializer never has to look at the new part at all:

- **Adding a new optional field.** `carrierRemarks` showing up on `HandlingEvent` is bytes an old reader, configured to ignore unrecognized properties, drops on the floor — exactly the way an old protobuf reader drops an unknown field number.
- **Adding a new enum member**, as long as every consumer of `HandlingEventType` treats a value it doesn't recognize as "handle me generically" rather than "this can only ever be one of the seven values I was compiled with." The enum evolution section below is the whole story on that second half of the sentence.
- **Adding a new channel path version.** `/ws/v2/bookings/{% raw %}{bookingId}{% endraw %}/handling-events` existing alongside the untouched `/ws/v1/...` path changes nothing about any connection already open there — it's a new route, not an edit to the old one.
- **Adding a second subprotocol token while still serving the first.** A server that still accepts `handling-events.v1` and now also accepts `handling-events.v2` breaks nothing for a client that only ever offered `v1`.

{% include excalidraw.html file="07-evolution-gate" alt="A matrix of changes to the handling-event contract, aligned in four topic columns — Field, Enum, Shape, Requirement. Safe row: add an optional field (carrierRemarks), add a new enum member (REROUTED), add a new channel path version (/ws/v2/), add a second subprotocol while the old one still serves. Breaking row, aligned under it by topic: remove a field a client already reads (amount), repurpose an enum member's meaning in place (CUSTOMS), change a field's type or unit in place (Money as a string becoming a number), make a previously optional field required. A dashed line connects each safe cell to the breaking cell below it, showing the same part of the contract handled two different ways." caption="Figure 7.1 — the evolution gate: four kinds of contract change, each with a safe addition above and the breaking mutation of the same thing below." %}

Read the two lists column by column: each pair is the same part of the contract, handled two different ways. The judgment call is never "is this change big or small" — it's "does any code compiled before this change ships have to look at the part that's different," and if the answer is yes, the change is breaking regardless of how small the diff looks in a pull request.

## The already-connected-client problem

Here is the part with no REST or gRPC unary analog at all. A REST client's contract is renegotiated, implicitly, on every request: it sends a request, gets a response built against whatever the server looks like *right now*, and is done — there was never a multi-message commitment to any particular version. A WebSocket connection makes exactly that commitment, for however long it stays open. A client that connected at 9:00 AM, before a 9:15 AM deploy changed what the server pushes, is still on that connection at 10:00 and the next day if nothing closes it — every message arriving from 9:15 onward is whatever the *new* server code decided to send, over a socket the client opened against the *old* contract and never had a chance to renegotiate.

That has three concrete consequences a rolling deploy makes unavoidable, not hypothetical:

1. **Three populations exist at once, for the whole length of a rollout.** Clients still on an instance that hasn't been replaced yet; clients that got disconnected when their instance was replaced and reconnected mid-rollout, landing on an old or a new instance depending on how far the rollout has progressed; clients connecting for the first time after the rollout finishes. All three have to be served correctly by whatever the contract looks like at that moment — there's no window where only one population exists to design for.
2. **There is no mid-connection renegotiation.** Subprotocol, extensions, and the channel path are fixed at handshake time; nothing lets either side agree to a new contract version without closing the connection. The server can *propose* a move — a close frame with a reason — but can't *force* when the client acts on it.
3. **"Already connected" can mean "for days."** A connection opened the day before a breaking change ships can still be alive when a shorter deprecation window closes, if this feed's typical connection lifetime runs to hours or days rather than minutes — a mobile client that opens a socket at launch and holds it until the app is force-quit, say. Sizing a deprecation window against deploy duration instead of observed connection lifetime is the most common way this problem gets underestimated.

None of this is solved by anything already decided about this contract — `/ws/v1/...` and `handling-events.v1` exist precisely because Chapter 5 anticipated needing a lever here. The next section is what pulling each of those levers does to a connection that's already open.

## Versioning strategies: channel path, subprotocol, message field

Three places a version can live, and each answers a different question about when an already-open connection finds out something changed.

**Channel path** — `/ws/v1/...` becoming `/ws/v2/...` — is the coarsest lever and the one Chapter 5's README already commits this contract to for a fully incompatible redesign. A server registers both paths at once, running two route handlers side by side; a connection's path is fixed the moment the handshake completes, so a client on `/ws/v1/...` keeps receiving whatever that route sends for the rest of its life, unaffected by whatever `/ws/v2/...` does in parallel. This is the right lever when the change is structural enough that expressing both shapes through one handler would mean branching on version everywhere inside it — an entirely new message shape, a different parameter set, a channel that means something different now.

**Subprotocol** — `Sec-WebSocket-Protocol: handling-events.v1` versus `handling-events.v2`, negotiated in the same handshake that already carries this token per Chapter 5's `servers.local.bindings.ws` block — is a finer-grained lever than the path. One channel path, one route handler, but the handler reads which subprotocol this *particular* connection negotiated and serializes outgoing messages to match it, the way an HTTP endpoint reads an `Accept` header to choose a representation. Reach for this when the channel's addressing hasn't changed — still one connection per booking — but the payload shape has, and standing up a second route would duplicate connection-lifecycle code (auth, backpressure, heartbeats) that has nothing to do with the version difference.

**Message-level version field** — a `schemaVersion` property inside the JSON payload itself — is the finest-grained lever and the only one that doesn't require a new handshake at all. A connection negotiated months ago can start receiving `schemaVersion: 2` payloads without ever reconnecting, because nothing about the handshake pinned it to a payload shape — only the message body did. This is the right lever for a change that has to land on connections already open, without waiting for every client to reconnect on its own schedule — a gradual, flag-driven payload enrichment, say. It's also the most expensive lever to live with long-term: every message handler has to branch on `schemaVersion` forever, because the connection no longer guarantees one shape for its whole life the way path and subprotocol versioning both do.

The three don't compete so much as answer different-sized questions. Bump the path when the channel itself is different. Bump the subprotocol when the channel is the same but the payload contract isn't, and reconnecting to pick up the new shape is acceptable. Add a message field when the payload needs to change underneath connections that cannot be relied on to reconnect on any particular schedule.

## Enum evolution and the unspecified zero

`HandlingEventType`'s zero value, `HANDLING_EVENT_TYPE_UNSPECIFIED`, is never sent by the server — `contracts/README.md` says so directly — and it is tempting to read that as "the enum already has a forward-compatibility story built in: anything we don't recognize becomes `UNSPECIFIED`." It doesn't, not automatically, and the gap between what the zero value buys and what it sounds like it buys is worth being precise about.

What `UNSPECIFIED` solves is a narrower, real problem: giving the type a safe default to initialize into *before* a value has been assigned. A language whose enum-equivalent construct needs some starting value — a struct field set up before the first message arrives, a default argument, a test fixture placeholder — has a documented thing to put there instead of `null` or a sentinel that means something different depending on which engineer invented it. That's the same role `*_UNSPECIFIED` plays in every enum across this series' gRPC sibling site, carried over here even though the mechanism underneath is different.

What it does *not* do is rescue a *future* value a client doesn't recognize *yet*. Protobuf enums are open by design — an unrecognized integer on the wire is preserved rather than rejected, so a reader compiled before a new member existed doesn't fail over its mere presence. A JSON string enum, as generated by a typical Pydantic model or a Java/Kotlin `enum` deserialized by Jackson, is closed by default: an unrecognized string is a validation failure, not a fallback to the zero value, unless the deserialization path is written to catch that failure and map it to `UNSPECIFIED`. Adding `REROUTED` to `HandlingEventType` is a safe change by the earlier section's reckoning only if every consumer of that enum was written with that catch-and-fall-back branch already in place. Without it, "add a new enum member" quietly becomes breaking for any client that hasn't been updated yet — the gap between "the zero value exists" and "the zero value is doing forward-compatibility work."

{% include codetabs.html langs="Quarkus|Python" %}

```java
// Quarkus — deserialize HandlingEventType defensively, not exhaustively
public enum HandlingEventType {
    HANDLING_EVENT_TYPE_UNSPECIFIED, RECEIVE, LOAD, UNLOAD,
    CUSTOMS, CLAIM, HOLD, DELIVERED;

    @JsonCreator
    public static HandlingEventType fromWire(String raw) {
        try {
            return valueOf(raw);
        } catch (IllegalArgumentException unrecognized) {
            // a future member this build predates — don't fail the connection
            return HANDLING_EVENT_TYPE_UNSPECIFIED;
        }
    }
}
```

```python
# Python — the same fallback, via a validator rather than a try/except in every caller
from pydantic import field_validator

class HandlingEvent(BaseModel):
    event_type: HandlingEventType

    @field_validator("event_type", mode="before")
    @classmethod
    def unknown_becomes_unspecified(cls, value: str) -> str:
        if value not in HandlingEventType._value2member_map_:
            return "HANDLING_EVENT_TYPE_UNSPECIFIED"
        return value
```

Both snippets do the same thing: move the "what if this is a value I don't recognize" decision out of every call site and into one place, so a future `REROUTED` lands as `UNSPECIFIED` — and whatever a handler already does for `UNSPECIFIED` — instead of raising a deserialization error that tears down the whole message, or the whole connection, over one event type a build predates.

## Deprecation and dual-publish windows

A dual-publish window is the period during which a server serves both the old and the new shape of something at once — both subprotocol tokens, both channel paths, or an old field alongside the new one that replaces it — so that neither population of already-connected clients from the section above ever sees a contract break mid-connection. Closing that window too early reopens exactly the problem it exists to prevent; the question is how to size it and how to close it as a planned step rather than by accident.

Size the window against the connection population's actual behavior, not the deploy's duration. A twenty-minute deploy says nothing about how long the longest-lived client connection stays open — a dashboard tab left open overnight, a worker holding a socket for a long-running job, a mobile client that only reconnects when relaunched. The right input is a histogram of this feed's own connection durations: the window needs to outlast whatever was already open when the new shape started being served, which in practice means watching the old version's active-connection count reach zero, not assuming a calendar date is close enough.

Close it in two steps, not one. First, stop *offering* the old version to anything new — drop the deprecated subprotocol token from new handshakes, or stop routing new connections to the old channel path — while every connection that already negotiated the old version keeps running untouched. Second, once telemetry shows the old version at zero live connections — not "probably none left," an actual zero — close any stragglers with an application-defined close code in the `4000`–`4999` range Chapter 13 reserves for this feed's own reasons (`4010`, say: "this channel version is retired, reconnect on `/ws/v2/...`") rather than a generic `1001` that gives a client's retry logic nothing to act on.

{% include excalidraw.html file="07-connected-client-migration" alt="A dual-publish window shown as three lanes across time — Server, a v1 client already connected before the change ships, and a v2 client that connects after. Before the deploy, the server serves v1 only and the v1 client is connected reading v1. At deploy time t0, the server starts serving v1 and v2 together; the v1 client stays connected and ignores the new field or enum member it doesn't recognize, while a v2 client connects and reads the new shape. When the dual-publish window closes, the server drops to v2 only, the lingering v1 client is closed with a deprecation close code and must reconnect on v2, and every connection is now on the new shape." caption="Figure 7.2 — a connection opened before t0 outlives the deploy that changed the contract; the dual-publish window is what keeps it alive and correct until it reconnects or the server closes it as planned." %}

## On the wire

Here is the safe addition from the evolution gate, applied to the real contract: a new optional field and a new enum member, shown as a diff against `contracts/asyncapi.yaml`.

```yaml
# contracts/asyncapi.yaml — components.schemas.HandlingEventType, before
HandlingEventType:
  type: string
  enum:
    - HANDLING_EVENT_TYPE_UNSPECIFIED
    - RECEIVE
    - LOAD
    - UNLOAD
    - CUSTOMS
    - CLAIM
    - HOLD
    - DELIVERED
```

```yaml
# contracts/asyncapi.yaml — components.schemas.HandlingEventType, after
HandlingEventType:
  type: string
  enum:
    - HANDLING_EVENT_TYPE_UNSPECIFIED
    - RECEIVE
    - LOAD
    - UNLOAD
    - CUSTOMS
    - CLAIM
    - HOLD
    - DELIVERED
    - REROUTED           # new member — cargo diverted mid-voyage to a new port
```

```yaml
# contracts/asyncapi.yaml — components.schemas.HandlingEvent.properties, after
    voyageNumber:
      type: string
    carrierRemarks:        # new optional field — free-text note from the carrier
      type: string
      description: >
        Optional free-text remark attached by the carrier system, present only
        when one was supplied. Absent on every event type before this field
        existed and on any event a carrier doesn't annotate.
    amount:
      $ref: '#/components/schemas/Money'
```

Neither addition touches `required`, neither reuses an existing property name or enum member, and both are exactly the kind of change the evolution gate calls safe: an old reader never has to look at anything it wasn't already looking at. What an old reader does when the first `REROUTED` event or the first `carrierRemarks` field arrives depends on how it was built — the opening section's claim that JSON's tolerance is a deserializer setting, not a protocol guarantee, made concrete. A Jackson `ObjectMapper` with default settings throws `UnrecognizedPropertyException` on `carrierRemarks`; the same mapper with `FAIL_ON_UNKNOWN_PROPERTIES` disabled drops the field without complaint, the way an old protobuf reader skips an unknown field number. A Pydantic model with `extra="forbid"` raises a `ValidationError` on the same payload; one configured `extra="ignore"` does not. `REROUTED` hits the identical fork, resolved by the enum-evolution section's `fromWire`/`unknown_becomes_unspecified` pattern. Both stacks in this site's examples sit on the permissive side of both forks, which is the configuration choice that makes "add a field" and "add an enum member" land as safe in practice and not only in theory.

Here is the breaking change the evolution gate warns against, on the same contract, so the failure mode is as concrete as the safe one:

```yaml
# contracts/asyncapi.yaml — components.schemas.Money, before (decimal string)
Money:
  type: string
  pattern: '^\d+\.\d{2}$'
  examples:
    - '125.00'
```

```yaml
# contracts/asyncapi.yaml — components.schemas.Money, after (BREAKING — do not ship)
Money:
  type: number
  examples:
    - 125.00
```

The field is still called `amount`, still sits in the same place in the payload, and still means the same thing conceptually — a quoted price. None of that saves an already-connected client. Every piece of code that parses `amount` as a string (`^\d+\.\d{2}$`-validated, compared for equality against another decimal string) now receives a JSON number instead, and a Pydantic field typed `str` or a Java field typed `String` populated via Jackson both raise a validation error on a raw `125.0`. This is the "change a field's type in place" row from the evolution gate, and exactly why the Money-as-decimal-string convention exists on this contract in the first place — a type this fragile to get wrong deserves a representation that can't drift into a different, almost-compatible shape without anyone noticing.

## Where this goes next

Part 2 closes here with a contract that validates, a message shape Chapter 6 settled, and now a documented answer for every way that shape is allowed to move without breaking a client holding a connection open against an earlier version of it. Part 3 is where that contract stops being paper: Chapter 8 builds the Quarkus WebSockets Next side of `handlingEvents`, Chapter 9 builds the Python side, and Chapter 11 is the one that proves both independently-built implementations agree with each other because they both agree with this file — not because either one imports the other. Every evolution rule this chapter named gets its first real test the moment two actual handlers, on two actual stacks, have to honor the same dual-publish window at the same time.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>This contract versions at three granularities — channel path for a structural break, subprotocol for a payload-shape break with an acceptable reconnect, and a message-level field for a change that has to reach connections already open — and picks among them by asking what an already-open connection is allowed to keep assuming. A gRPC streaming call or a long-poll loop both run into a version of this same already-connected problem; a WebSocket makes it the common case instead of an edge case, because every connection this feed serves is long-lived by design. The one discipline that makes all three levers work is sizing the dual-publish window against observed connection lifetimes rather than deploy duration, and closing it in two steps — stop offering the old version to anything new, then close the stragglers with a close code a client's reconnect logic can act on. Skipping either step doesn't save time; it moves the breakage from a planned window a reader can watch in a diagram to an unplanned one a client discovers in production.</p></div>

## For deeper coverage

- J. J. Geewax, *API Design Patterns* (Manning, 2021) — the compatibility and versioning patterns this chapter's breaking/safe classification draws on, generalized across API styles.
- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022) — message-level evolution patterns for a channel that can't renegotiate mid-connection.
- *Cloud Native Design Patterns* — "Versioning & Evolution" chapter — the channel-path, subprotocol, and payload-field levers this chapter applies to one WebSocket feed, treated at the level of an API's whole lifecycle.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0) — the `servers`/`channels` structure that makes `/ws/v1/...` and `/ws/v2/...` two independently addressable routes.
- [Semantic Versioning](https://semver.org/) — the additive-vs-breaking vocabulary this chapter's evolution gate maps onto a schema instead of a package version number.
