---
title: "Anti-Patterns"
order: 24
part: "Testing, Debugging & Observability"
description: "The recurring mistakes that make a WebSocket API harder to run than it needs to be."
duration: "12 min read"
---

## Learning objectives

By the end of this chapter you can:

- Recognize idle-timeout as a liveness trap when a server's own outbound ping resets the same clock meant to detect a silent peer.
- Distinguish a reconnect loop from a resumed stream, and know when stateless mode drops an event from the gap without signaling it.
- Catch a size-like parameter's inverted default, such as `asyncio.Queue(maxsize=0)` meaning unbounded rather than zero-capacity.
- Avoid turning an auth failure response into a signature oracle by collapsing distinct JWT failure modes into one close code.
- Treat `contracts/handling-event.proto` and `asyncapi.yaml` as two contract halves that need an explicit parity gate.

## Why this matters

Each anti-pattern here already happened in the examples. The `examples/part4-connection` heartbeat config shipped with the idle-timeout trap before `HeartbeatLivenessSweep` existed. `OUTBOUND_QUEUE_MAXSIZE=0` was set by someone expecting the smallest possible queue, and produced the opposite. The stateless backplane is the "before" picture the Kafka-backed reconnect mode was built to fix.

Eight mistakes follow, grouped by where they surface: a connection's lifecycle, the bounds around what a server will hold, the authentication boundary, the wire schema two stacks share, and the design habit of treating a socket like a request/response call.

| Anti-pattern | Fix |
|---|---|
| Idle-timeout as a liveness detector | Track pongs per connection, sweep on a separate clock, close `4408` |
| Reconnect loop that assumes no gap | Retain events durably and resume with `?afterEventId=` |
| `maxsize=0` meaning unbounded | A positive bound and a send timeout, close `4290` |
| Backplane scaled as an unbounded broadcast | Key records by `bookingId` so the domain can be partitioned |
| Distinct auth errors on the wire | One close code, `1008`, reason logged server-side only |
| Reused Protobuf field number | Additive-only numbers, `buf breaking` and a parity gate |
| Rejecting a client that offers no subprotocol | A permissive JSON fallback |
| No message design or versioning plan | Self-describing messages and an explicit breaking-change rule |

{% include excalidraw.html file="24-pattern-remedy-map" alt="A map of eight anti-patterns in four groups, lifecycle, bounds, security, and schema and design. Each failure on the left is paired with the fix on the right: pong-tracked liveness sweep, a positive queue bound with close 4290, one collapsed auth close code 1008, additive-only Protobuf field numbers with buf breaking and a parity script, and a permissive JSON subprotocol fallback." caption="Figure 24.1: eight anti-patterns and the fix each one already has in the examples." %}

## Lifecycle: mistaking activity for liveness

**Idle-timeout as a liveness detector.** The `examples/part4-connection` Quarkus config looked complete: turn on `auto-ping-interval` so pings go out, set `quarkus.http.idle-timeout` so Vert.x tears down a connection that goes quiet. It wasn't. Vert.x's idle-timeout resets on any read or write, and the server's own outbound ping is a write. Every 20 seconds, whether or not the peer has answered, the server resets its own idle clock by sending the next ping. A silent peer and a healthy one look identical, because the mechanism watches for traffic, not for a pong, and the server guarantees there is always some.

A raw TCP client that completes the handshake and then never pongs, never closes and never sends again stayed open against the Quarkus app well past the idle-timeout window. A bigger timeout doesn't fix that; a different signal does. `HeartbeatLivenessSweep` records `LAST_PONG_AT` per connection, set on open and advanced only by an actual pong, and a separate `@Scheduled` bean sweeps every open connection on its own clock, closing anything silent for longer than the configured window.

A liveness check that is one config line is tempting, and it is wrong whenever the thing it watches is something the server can produce without the peer.

{% include excalidraw.html file="24-dev-vs-prod-timeline" alt="Two lanes on one time axis. In a short manual test, a connection opens, a few messages are sent and the tab closes well inside the idle-timeout window, so the configuration looks fine. In production, a peer goes silent after hours and the server's own pings keep resetting the idle clock, so the server still thinks the connection is healthy until a pong-tracked sweep closes it with 4408." caption="Figure 24.2: the idle-timeout trap never appears in a short manual test; it appears when a connection lives long enough for a silent peer's ping-driven clock reset to matter." %}

**Stateless reconnect assuming no gap.** A reconnect loop with backoff and jitter solves "the client notices its connection died and gets a new one." It says nothing about what happened during the gap. In `examples/part4-backplane`'s default mode, `StatelessBackplane.publish` fans an event out to whatever is subscribed right now and forgets it when the call returns: no queue, no log, nowhere for a disconnected client's missed event to wait.

The consequence is observable. Connect, receive the three-event seed, disconnect, inject a new event through the same instance, then reconnect with `?afterEventId=<last seen>`. The injected event is gone, not delayed. The inject call returns `202 Accepted` the whole time, and nothing errors, retries or alerts. A reconnecting client ends up with fewer events than if it had never disconnected.

Stateless mode is the right tool when a stale value is harmless or a full resync is cheap elsewhere. The mistake is assuming a reconnect loop recovers data for a feed where every event is an individually significant fact and nothing can re-fetch what the gap cost. That feed needs somewhere to retain events and a way to answer "after X" against it, which is the Kafka-backed reconnect mode, not a cleverer client.

## Bounds: the zero that isn't zero, and the broadcast that isn't free

**`asyncio.Queue(maxsize=0)` meaning unbounded.** The `examples/part4-connection` `OutboundQueue` sits on `asyncio.Queue` to bound how many unsent frames a slow client's connection may accumulate before the server closes it or drops work. `OUTBOUND_QUEUE_MAXSIZE=0` does not mean a zero-capacity queue that trips backpressure on the first send. In `asyncio.Queue`, `maxsize <= 0` disables the bound, the opposite of what zero means for almost every other size-like parameter. A developer reaching for `0` gets the one value that guarantees backpressure never trips.

The two stacks disagree on the same-looking knob. Quarkus compares `pending.get() >= maxPendingSends`, so `0` trips immediately, while the Python side needs `OUTBOUND_QUEUE_MAXSIZE=1` to force the same trigger. Check what the primitive underneath does at zero before trusting that "0" means "nothing fits."

**Unbounded fan-out across instances.** An event injected through instance B reaches a client connected to instance A because every instance subscribes to the same Kafka topic or Redis channel. That is the fix, and it has a cost to size: with N instances subscribed, each injected event costs roughly N times the deserialize-and-filter work, whether or not any instance has a client waiting. Every other instance's consumer wakes, checks its local connection registry, finds nothing and discards the record. That is cheap per instance and not free, and it grows with instance count, not with the number of watchers.

Sticky sessions can't replace the backplane, because they say nothing about where an event originates. Treat the topic as a broadcast domain you can partition. `examples/part4-backplane` keys every record by `bookingId`, even on a single-partition topic, so a production deployment can shard the domain before the N-times multiplier becomes real cost.

## Security: authenticating too late, and answering too precisely

**Collapsing a real auth decision into something a prober can mine.** A browser's `WebSocket` constructor can't attach a custom `Authorization` header to the opening handshake, so the bearer token travels as a `?token=` query parameter and ends up in access logs, browser history and proxy traces. The channel's security design names that trade-off and relies on a short TTL and `wss://` to make it tolerable.

The sharper problem is how a failed token is reported. `app/auth.py` collapses four failure modes (missing, malformed, bad signature, expired) into one outcome: close code `1008`, no data sent, no reason echoed. A server that answered "bad signature" for a forged signature and "expired" for a stale but correctly signed one would tell a prober whether it holds a working key. That turns the signature check into an oracle to iterate against. The reason is still logged server-side for the operator, and never crosses the wire.

A related mistake with Python's `websockets` is rejecting at the door with `process_request`, as an HTTP middleware would. That hook runs before the handshake completes, when no WebSocket exists, so its only option is an HTTP response with no application close code. `app/ws_server.py` accepts the handshake for every connection and closes unauthenticated ones with `1008` first thing. To the client that is almost identical to an HTTP rejection, and it is consistent with the channel's other connection-concern close codes (`4290`, `4400`, `4408`).

## Schema: treating the wire format like source code

**Reusing a Protobuf field number, or assuming a JSON rename is free.** The header of `contracts/handling-event.proto` states the rule: field numbers are additive-only. A number is never reused or renumbered, even after the field it named is removed. A Protobuf field carries no name on the wire, only a tag. If field `8` is reused after `voyage_number` is retired, an old message serialized before the change decodes under the new schema as if it carried the new field's value. That is silent data corruption with no parse error. `buf breaking` exists to catch the renumbering before it ships.

JSON has a gentler-looking version of the same mistake. Removing a field a client already reads, or repurposing an enum member's meaning in place, breaks an already-connected client the same way, even though nothing in the text format looks dangerous.

Because `contracts/handling-event.proto` and `asyncapi.yaml` are two hand-kept files describing the same `HandlingEvent`, drift between them is its own anti-pattern. Neither `buf lint` nor `buf breaking` can see it, and a field added to one side passes every single-file lint. `scripts/check-proto-parity.py` guards the seam: field names, required versus optional, and enum membership and order, checked statically on every run.

**Rejecting a client that offers no subprotocol.** Python's `websockets` aborts the handshake with HTTP 400 the moment a client connects without offering a subprotocol. That default is reasonable in isolation and wrong here: a plain browser `WebSocket`, or `websocat` with no `--protocol`, must keep working and fall through to JSON. `_select_subprotocol` in `app/ws_server.py` reimplements negotiation by hand, picks JSON when nothing or only the bare `handling-events.v1` token is offered, and reserves `+protobuf` for a client that asks.

The same mistake applies to any negotiated capability, whether a subprotocol, a compression extension or an API version. A server that refuses a client that doesn't participate has confused "optional" with "required." Define a permissive default path for the case where nothing was negotiated.

## Design: treating a push channel like a request/response call

**No message design and no versioning plan, because the channel "is nothing but JSON."** This one produces most of the others. A WebSocket has no request to pair a response against and no envelope from the transport, unlike an HTTP status line or a gRPC method name. Nothing prompts the question of what happens to a client that is already connected when the schema changes.

A team that treats a socket as "a REST response that happens to arrive more than once" skips two things. One is a message shape that carries enough context to be understood standing alone, since no request triggered it. The other is an explicit definition of a breaking change on a connection that may stay open for hours, which a one-shot HTTP client never needs because its next request sees whatever the server looks like by then.

The schema anti-patterns above follow from skipping that design work. A field-numbering rule matters only to a team that accepts a durable client is watching the channel over time, and a subprotocol fallback only to a team that planned for a client that hasn't adopted the newest negotiation.

> **Decision**
>
> Every anti-pattern here trusts a signal that looks like the one you need without checking what it measures. Traffic is not liveness, so track pongs. A reconnected socket is not a resumed stream, so put something durable behind the socket. A size parameter's zero is not necessarily its smallest value, so run the trigger. A specific error message is not more helpful than a collapsed one, so answer every auth failure `1008`. A field's name is not its wire identity in Protobuf, so never reuse a tag.

> **🤖 Explore with your agent**
>
> "In examples/part4-connection, review the heartbeat configuration and `HeartbeatLivenessSweep` against the rule that traffic is not liveness. Then set the Python server's OUTBOUND_QUEUE_MAXSIZE to 0 and to 1, and report which value trips close code 4290 and why, citing asyncio.Queue's maxsize semantics."
>
> Check: `bash examples/part4-connection/verify.sh` still prints PASS, and the reply states that `maxsize <= 0` is unbounded so only `1` trips the guard.

## Build, run, observe

```bash
bash examples/part4-connection/verify.sh
```

The script runs both stacks. Its heartbeat step starts one-off instances with a short window (`liveness-timeout` forced to 5 s) and opens a raw TCP socket that completes the `101` upgrade and then stays silent: no pong, no close. Before `HeartbeatLivenessSweep` the connection stayed open indefinitely. Now it closes in about 15.8 s: the liveness timeout, up to one 1 s sweep interval, and Vert.x's roughly 10 s closing-handshake grace. The sweep requests close `4408`, but the silent peer never completes the handshake, so `@OnClose` sees Vert.x's abnormal-closure code `1006` when the grace period gives up. Detection is not instant; it is bounded, which the earlier configuration never was. The script prints `PASS: ` when every step holds.

- To see the idle-timeout trap, run the same check on a build without the sweep: the connection stays open where the script expects it closed.
- To see the stateless gap, run the backplane example's stateless stage (`examples/part4-backplane/verify.sh`): the injected event is missing after reconnect.
- To see the zero trap, set `OUTBOUND_QUEUE_MAXSIZE=0` on the Python app: backpressure never trips. `1` does.

## For deeper coverage

- Gerald Bachlmayr, Aiden Ziegelaar, Alan Blockley & Bojan Zivic, *Cloud Native Anti-Patterns* (Packt, 2025): the broader catalogue of operational mistakes these eight entries belong to.
- Michael T. Nygard, *Release It!, Second Edition* (Pragmatic Bookshelf, 2018): stability patterns and the bounded-queue, fail-fast reasoning behind the backpressure and idle-timeout entries.
- *Cloud Native Design Patterns*, "Anti-Patterns" chapter: the companion list these eight entries sit alongside.
- RFC 6455: the close-code semantics (`1006`, `1008`) the lifecycle and security entries depend on.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the subprotocol and message-schema contract the schema entries work against.
