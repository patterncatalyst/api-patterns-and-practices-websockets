# Part 4 "Connection Concerns" — Quarkus (WebSockets Next)

Forked from [`examples/part3-handling-events/quarkus`](../../part3-handling-events/quarkus):
the same `handlingEvents` channel
(`operations.receiveHandlingEvent`, [`contracts/asyncapi.yaml`](../../../contracts/asyncapi.yaml)) —
one WebSocket connection per booking, replaying the shared fixture on open —
now hardened with the four connection concerns this part covers. The
Python/`websockets`-library sibling app
([`../python`](../python)) implements the identical behavior against the
same contract; see that app's README/docstrings for the other side of every
convention below.

- **Endpoint:** `ws://localhost:8080/ws/v1/bookings/{bookingId}/handling-events`
- **Auth:** a JWT travels as `?token=<jwt>` on the upgrade URL.
- **Model:** `HandlingEvent` / `HandlingEventType` in
  `src/main/java/.../handlingevents/` are byte-for-byte copies of part3's —
  this part is about connection concerns, not new message content.

## The fixture is not duplicated here

[`../../part3-handling-events/fixtures/handling-events.json`](../../part3-handling-events/fixtures/handling-events.json)
is the single source of truth (the Python sibling reads the identical
file). `pom.xml`'s `copy-handling-events-fixture` execution copies it onto
the classpath (`/fixtures/handling-events.json`) at build time via a path
relative to this module's basedir (`../../part3-handling-events/fixtures` —
two levels up, since part3's and part4's `quarkus/` modules are siblings
under `examples/`) — no manual copy step for a local build. `Containerfile`
reproduces the same relative layout inside the build stage so the identical
`pom.xml` reference resolves there too.

## Close codes

Shared exactly with the Python sibling, so a client sees identical close
semantics regardless of which stack it talks to (see `CloseCodes.java` for
the full rationale, including the close-code-vs-error-envelope choice):

| Code | Name                   | When                                                              |
|-----:|------------------------|--------------------------------------------------------------------|
| 1008 | Policy violation        | Ch17 — missing/malformed/bad-signature/expired JWT, at `@OnOpen`, before any event is streamed. |
| 4400 | Bad request (app range) | Ch13 — a client text/binary frame (this channel accepts none); always preceded by the JSON error envelope. |
| 4290 | Slow consumer (app range) | Ch12 — outbound backpressure CLOSE policy. |
| 4408 | Liveness timeout (app range) | Ch14 — no pong received within the configured window (`HeartbeatLivenessSweep`). NOT bit-identical to the Python sibling, which lets the `websockets` library's own keepalive failure close with its hardcoded 1011 — see `CloseCodes.LIVENESS_TIMEOUT`'s Javadoc and the Ch14 section below. |
| 1011 | Unexpected condition     | Ch13 — an unmapped server-side exception (`@OnError` backstop). |
| 1001 | Going away               | Graceful application shutdown (`ConnectionLifecycleShutdown`). |

## Ch17 — JWT auth

`JwtHs256` is a minimal, dependency-free HS256 mint/verify pair (HMAC-SHA256
via `javax.crypto`, claims JSON via the Jackson `ObjectMapper` already
pulled in by `quarkus-websockets-next` — no new dependency). Deliberately
not `quarkus-smallrye-jwt`: that extension targets RS256/JWKS, the right
shape for a multi-service-audience token, not this chapter's single
shared-secret token.

- Secret: `ws.jwt.secret`, mapped from the `WS_JWT_SECRET` env var (dev
  default `dev-secret-change-me` — never use it past local dev/test).
- Validated in `HandlingEventConnectionWebSocket#onOpen`, BEFORE the fixture
  replay starts. WebSockets Next doesn't parse query parameters for the
  caller (see the reference guide's "Path parameters" note); the token is
  pulled out of `WebSocketConnection#handshakeRequest().query()` by
  `QueryParams`.
- Every failure mode (missing, malformed, bad signature, expired) collapses
  to the same 1008 close — an attacker probing the channel can't learn
  which specific check failed.

Mint a test token with `TokenMinter` (compile first, then run from
`target/classes` — no packaging/running the whole app needed):

```shell
./mvnw -q compile
TOKEN="$(java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter valid)"
EXPIRED="$(java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter expired)"
BADSIG="$(java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter bad-sig)"
```

## Ch13 — error handling

This channel defines no client-to-server operation (same as part3) — ANY
client frame a connected client sends is, by definition, a protocol error.
`HandlingEventConnectionWebSocket#onTextMessage`/`onBinaryMessage` send an
in-band JSON error envelope first, then close 4400:

```json
{"error":{"code":"BAD_REQUEST","message":"this channel accepts no client-to-server messages"}}
```

Any other, unmapped server-side exception is caught by the `@OnError`
backstop and closes 1011.

## Ch14 — heartbeats

**The naive version of this (WebSockets Next's built-in auto-ping plus
Vert.x's HTTP idle-timeout) does NOT detect a dead peer, confirmed live.**
`quarkus.websockets-next.server.auto-ping-interval` keeps the server
sending pings, but `quarkus.http.idle-timeout` resets on any read OR WRITE
activity on the connection — and the server's own outbound ping IS write
activity. A peer that never answers a single ping never trips idle-timeout,
because the server keeps resetting its own idle clock with its own pings
regardless of whether anything comes back. `verify.sh`'s raw, non-ponging
socket probe stayed open well past idle-timeout before this fix — the
Python sibling's equivalent probe correctly closed at its configured
window, because that library's keepalive check is pong-aware, not a
generic idle timer.

The actual detector is `HeartbeatLivenessSweep`, a pong-tracked liveness
check with no dependence on transport-level idle timers:

1. `HandlingEventConnectionWebSocket#onOpen` and `#onPongMessage` stamp
   `LAST_PONG_AT` (epoch millis) on the connection's `userData()` — on open
   (so a peer that never pongs even once still has a baseline to measure
   from) and on every pong thereafter.
2. `HeartbeatLivenessSweep#sweep`, a `@Scheduled` method, runs every
   `example.heartbeat.sweep-interval` (default `5s`) and closes
   (`CloseCodes.LIVENESS_TIMEOUT`, 4408) any connection on this endpoint
   whose last pong is older than `example.heartbeat.liveness-timeout`
   (default `45s` = `auto-ping-interval` * 2 + 5s grace — a "missed two
   consecutive pongs" window).

The sweep reads connections straight off the injected `OpenConnections`
registry and requests the close directly on each `WebSocketConnection` —
the same no-session-context pattern `ConnectionLifecycleShutdown` already
uses — because a `@Scheduled` method runs on its own worker thread with no
WebSocket `@SessionScoped` context of its own; see `HeartbeatLivenessSweep`'s
Javadoc for the full reasoning, including why it uses the non-blocking
`close(...)` rather than `closeAndAwait`.

**A requested close isn't instant.** Closing a WebSocket is itself a
two-way handshake (server sends a close frame, then waits for the peer's
own close frame back), and a peer this sweep just proved isn't responding
obviously won't send that acknowledgment either — so Vert.x falls back to
forcibly terminating the TCP connection once its own closing-handshake
grace elapses (`HttpServerOptions.DEFAULT_WEBSOCKET_CLOSING_TIMEOUT`, 10s,
not currently exposed as a Quarkus config property). Confirmed live:
`@OnClose` then observes the connection's own final close code as `1006`
(abnormal closure), not `4408` — the close this sweep requested never
completed the handshake, which is standard protocol behavior for an
unresponsive peer, not a bug. Total observed time from "last pong" to the
raw TCP socket actually closing: `liveness-timeout` + up to one
`sweep-interval` + ~10s.

Override via `QUARKUS_WEBSOCKETS_NEXT_SERVER_AUTO_PING_INTERVAL` (ping
interval), `EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT` (dead-peer threshold), and
`EXAMPLE_HEARTBEAT_SWEEP_INTERVAL` (sweep frequency) — `verify.sh`'s Ch14
stage shrinks all three to prove detection within a few seconds instead of
waiting out the production-sized defaults, and asserts the silent
raw-socket peer is actually closed within that short window (see
`examples/part4-connection/verify.sh`'s `raw_silent_client_close_wait`
heartbeat stage).

## Ch12 — outbound backpressure

`OutboundBackpressureGuard` bounds the connection's OUTBOUND path — the
server-side mirror of part3 Ch10's client-side bounded buffer. WebSockets
Next has no built-in outbound-buffer-size knob (only
`max-pending-messages`, which bounds INBOUND messages), so this class
tracks outstanding (not-yet-acknowledged) `sendText` calls for a connection
itself and applies a policy once either of two signals fires:

1. too many sends are outstanding at once
   (`example.backpressure.max-pending-sends`, default 32 — matches the
   Python sibling's `OUTBOUND_QUEUE_MAXSIZE`); or
2. a single `sendText` doesn't complete within
   `example.backpressure.send-timeout` (default `5s` — matches
   `OUTBOUND_SEND_TIMEOUT_S`).

`example.backpressure.policy` is `CLOSE` (default — close with 4290 and
stop sending) or `DROP` (log a warning, skip the one event, keep going).
`CLOSE` is the right default for this channel (a missed `HandlingEvent` is
a correctness problem, not a supersede-by-the-next-update one); `DROP`
exists to show the trade-off.

The default threshold (32) is generous enough that this fixture's 3-event
burst never trips it in normal operation — see "Self-verify" below for how
to exercise the CLOSE policy deterministically.

## Running it

```shell
./mvnw quarkus:dev
```

Dev UI: <http://localhost:8080/q/dev/>.

## Running the conformance test

Identical to part3's test (forked verbatim — this part reuses the same
fixture and model, so the same invariants hold) — regenerate the
contract-derived schema first:

```shell
# from the repo root
python3 -I scripts/extract-message-schema.py build/handling-event.schema.json

# from this directory
./mvnw -q test
```

## Packaging

```shell
./mvnw package
WS_JWT_SECRET=dev-secret-change-me java -jar target/quarkus-app/quarkus-run.jar
```

Or build the container image from the **repo root** (the build context
needs to reach `examples/part3-handling-events/fixtures/`):

```shell
docker build -f examples/part4-connection/quarkus/Containerfile \
  -t part4-connection-quarkus .
docker run --rm -p 8080:8080 part4-connection-quarkus
```

## Self-verify

Using the shared harness (`examples/_lib/lib.sh`):

```shell
source ../../_lib/lib.sh
ensure_websocat

TOKEN="$(java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter valid)"
EXPIRED="$(java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter expired)"
BADSIG="$(java -cp target/classes com.patterncatalyst.shipping.connection.TokenMinter bad-sig)"
CHANNEL="/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"

wait_for_ws localhost:8080 "$CHANNEL?token=$TOKEN"

# Valid token: first frame is the fixture's RECEIVE event.
ws_first_frame_auth "ws://localhost:8080$CHANNEL" "$TOKEN"

# No / bad token: rejected, no data, close 1008.
assert_ws_rejected "ws://localhost:8080$CHANNEL" 10 "no token"
assert_ws_rejected "ws://localhost:8080$CHANNEL?token=garbage" 10 "malformed token"
assert_ws_rejected "ws://localhost:8080$CHANNEL?token=$EXPIRED" 10 "expired token"
assert_ws_rejected "ws://localhost:8080$CHANNEL?token=$BADSIG" 10 "bad signature"

# Malformed client frame: error envelope, then close 4400.
echo '{"not":"valid"}' | websocat -1 "ws://localhost:8080$CHANNEL?token=$TOKEN"
```

To exercise the Ch12 backpressure CLOSE policy deterministically (no
genuinely slow consumer needed — see `OutboundBackpressureGuard`'s
Javadoc), restart with the threshold forced to 0 so the very first fixture
event already exceeds it:

```shell
EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0 java -jar target/quarkus-app/quarkus-run.jar
```

A connected client then receives zero frames and is closed with 4290
("slow consumer: outbound buffer exceeded") — verified live (see this
module's self-verify log). `EXAMPLE_BACKPRESSURE_POLICY=DROP` with the same
threshold instead logs one warning per fixture event and keeps the
connection open with no frames sent at all — also verified live. (A
threshold of 1 is NOT reliably deterministic on a fast local loopback: with
`transformToUniAndMerge` firing all three sends essentially at once, the
first send often completes — decrementing the pending count back to 0 —
before the second item's threshold check runs, so the policy doesn't
trip every time. 0 removes that race by failing before anything is ever
sent.)

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
