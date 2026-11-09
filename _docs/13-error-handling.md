---
title: "Error Handling"
order: 13
part: "Production Concerns"
description: "Close codes, an in-band error envelope, and per-code retry rules for a connection that has no status line."
duration: "16 min read"
---

## Learning objectives

By the end of this chapter you can:

- Place a close code in RFC 6455's protocol range or its `4000` to `4999` private-use range, and explain why every code an application invents belongs in the private one.
- Apply the envelope-then-close rule: send an error envelope first when a specific frame is at fault and the socket is open, and rely on the close code alone otherwise.
- Explain why `1006` can never come from a server, and why client reconnect logic must still handle it.
- Map each close code to a retry decision instead of treating every close as "reconnect."
- Handle the one cross-stack mismatch: Quarkus closes a silent peer with `4408`, Python's library with `1011`.

## Why this matters

An HTTP response carries its verdict in the status line: `400`, `401`, `429` and `500` arrive before a byte of body. A WebSocket has no equivalent. After the upgrade every frame is just a frame, and no header marks one as an error. The `handlingEvents` channel defines one direction, server to client, so anything a client sends is wrong by construction. Two mechanisms can say so: a close code the transport carries, and an in-band JSON envelope the application invents. Both stacks implement both, with the same JSON shape and almost the same numeric codes.

## No status line, two signaling channels

RFC 6455 section 7.4 gives a closing connection a 16-bit close code and an optional UTF-8 reason string in the close frame. That is the whole built-in vocabulary. There is no machine-readable error body, and the code exists only as the connection ends. It says that something went wrong, and roughly what category, but too late to carry a sentence a developer debugging their client could act on.

So an application that handles errors builds a second channel on top. The envelope is a plain JSON text frame sent while the socket is still open, read by the handler a client already has for ordinary push frames:

```json
{"error":{"code":"BAD_REQUEST","message":"..."}}
```

No WebSocket framing marks the next frame as an error; the envelope is an application convention that both stacks honor. A close code is cheap, transport-level and arrives last. An envelope is application-level, needs the socket still open, and arrives first.

## The close-code taxonomy

RFC 6455 section 7.4.1 reserves bands, and the band tells a client whether a code is a standard reason or a convention that needs this service's documentation:

| Range | Use |
|---|---|
| `1000` to `2999` | Protocol. `1000` to `1015` are defined: `1000` normal, `1001` going away, `1002` protocol error, `1003` unsupported data, `1007` invalid payload, `1008` policy violation, `1009` message too big, `1010` mandatory extension, `1011` internal error. `1005` and `1006` are reserved so they never appear in a close frame. `1016` to `2999` are held for future protocol revisions. |
| `3000` to `3999` | Registered with IANA for libraries and frameworks |
| `4000` to `4999` | Private use: an application's own vocabulary, with no risk of colliding with a future standard code |

`CloseCodes.java` puts every code this channel uses in exactly one band. Reused standard codes keep their RFC meaning; invented codes live in the private band.

| Code | Name | Band | Used for |
|---|---|---|---|
| `1000` | Normal closure | Standard | A clean close with nothing to explain |
| `1001` | `GOING_AWAY` | Standard | Graceful application shutdown |
| `1008` | `AUTH_FAILURE` | Standard | A JWT that is missing, malformed, badly signed or expired |
| `1011` | `UNEXPECTED_SERVER_ERROR` | Standard | An unmapped server-side exception, the backstop |
| `4400` | `BAD_REQUEST` | Private | A client text or binary frame outside the contract |
| `4290` | `SLOW_CONSUMER` | Private | The backpressure `CLOSE` policy |
| `4408` | `LIVENESS_TIMEOUT` | Private | The heartbeat detector closing a dead peer, named after HTTP 408 as a mnemonic |

The first digit is a first signal for a client: a code starting with `1` is something a generic WebSocket library may already interpret, and `44` is this application's convention.

One mismatch is documented rather than hidden. Quarkus closes a silent peer with `4408`. Python's equivalent condition, the `websockets` library's own `ping_timeout` keepalive, closes with the library's hardcoded `1011`. Giving it an application code would mean overriding the library's keepalive machinery. The stacks agree on when a silent peer is closed but not on the code, so a client that targets both must accept either.

{% include excalidraw.html file="13-error-decision-tree" alt="A decision tree. If one specific offending frame can be annotated and the socket is still open, send an error envelope and then close with 4400, so the client's normal message handler sees why. Otherwise the close code alone is the signal: 1008, 4290, 4408 or 1011." caption="Figure 13.1: The one decision for every failure on this channel: is there a specific frame to annotate while the socket is still open?" %}

## Envelope first, then close

Send the envelope when a specific offending message can be annotated and the connection is still open to carry it. Otherwise rely on the close code alone. Of the application's failure modes, only the malformed client frame gets both signals. Auth failure and backpressure close before any data has been streamed, so there is no established moment in which an envelope would make sense. An unmapped server exception leaves the connection in an unknown state, and a well-formed envelope may fail on an already-broken channel for no benefit.

An envelope before every close would look consistent and would be worse. For auth it creates an oracle: different replies for a missing token, a bad signature and an expired token let a prober learn which check failed. `AuthError` is logged server-side with its specific reason and never echoed on the wire. Every auth failure collapses to the same `1008` close with no envelope and no distinguishing reason string. The decision has two questions: is there something worth saying, and is it safe to say it. For auth the second answer is no, even when the first is yes.

## Two stacks, one mapping

Both stacks define the identical envelope in their own idiom: a Jackson record in Quarkus, a plain dict in Python.

{% include codetabs.html langs="Quarkus|Python" %}

```java
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ErrorEnvelope(ErrorBody error) {

    public record ErrorBody(String code, String message) {
    }

    public static ErrorEnvelope badRequest(String message) {
        return new ErrorEnvelope(new ErrorBody("BAD_REQUEST", message));
    }
}
```

```python
def _error_envelope(message: str) -> dict:
    """The in-band JSON error shape sent before a 4400 close; see the
    "Close-code-vs-envelope" note in this module's docstring. `BAD_REQUEST`
    is the only code this channel emits today (every client-sent frame is
    invalid, since the contract defines no client-to-server operation on
    this channel); a richer channel with multiple failure modes would add
    more `code` values here.
    """
    return {"error": {"code": "BAD_REQUEST", "message": message}}
```

`BAD_REQUEST` is the only code either side emits, because the channel has one client-to-server failure mode: any frame at all. A channel where some requests are valid and others fail in distinguishable ways would earn a real taxonomy (`INVALID_FIELD`, `UNKNOWN_OPERATION`).

The handlers diverge most. Quarkus uses `@OnTextMessage`, `@OnBinaryMessage` and `@OnError`; Python has one `async for` receive loop. Both reach the same decision: classify the frame, send the envelope, close.

{% include codetabs.html langs="Quarkus|Python" %}

```java
    @OnTextMessage
    public Uni<Void> onTextMessage(String raw) {
        String reason;
        try {
            JsonNode parsed = MAPPER.readTree(raw);
            reason = parsed.isObject()
                    ? "this channel accepts no client-to-server messages"
                    : "expected a JSON object";
        } catch (Exception e) {
            reason = "invalid JSON: " + e.getMessage();
        }
        return rejectMalformed(reason);
    }

    /** Binary frames are not defined on this channel either; same treatment as an invalid text frame. */
    @OnBinaryMessage
    public Uni<Void> onBinaryMessage(Buffer data) {
        return rejectMalformed("binary frames are not supported on this channel");
    }

    /**
     * Sends the {@link ErrorEnvelope} then closes with
     * {@link CloseCodes#BAD_REQUEST}, composed as ONE chained {@code Uni}
     * (never a manual nested {@code .subscribe()}; see {@link #onOpen}'s
     * Javadoc) so both calls run inside the single subscription Quarkus
     * itself manages for the {@code Uni<Void>} this method returns.
     */
    private Uni<Void> rejectMalformed(String reason) {
        String bookingId = connection.pathParam("bookingId");
        Log.warnf("handling-events connection bookingId=%s sent an unexpected client frame: %s", bookingId, reason);
        return connection.sendText(ErrorEnvelope.badRequest(reason))
                .chain(() -> connection.close(new CloseReason(CloseCodes.BAD_REQUEST, "malformed client message")));
    }
```

```python
async def _reject_malformed(websocket: ServerConnection, reason: str) -> None:
    await websocket.send(json.dumps(_error_envelope(reason)))
    await websocket.close(code=CLOSE_CODE_MALFORMED, reason="malformed client message")


async def _receive_loop(websocket: ServerConnection) -> None:
    """This channel is server-push-only (the contract defines
    no client-to-server operation on `handlingEvents`), so ANY frame a
    client sends here is, by definition, a protocol error: there is no
    valid shape to accept. The first inbound frame, whatever it is, gets
    the error envelope + 4400 treatment. Binary frames are rejected the same
    way (no binary framing is defined on this channel either).
    """
    async for message in websocket:
        if not isinstance(message, str):
            await _reject_malformed(websocket, "binary frames are not supported on this channel")
            return
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError as exc:
            await _reject_malformed(websocket, f"invalid JSON: {exc}")
            return
        if not isinstance(parsed, dict):
            await _reject_malformed(websocket, "expected a JSON object")
            return
        await _reject_malformed(
            websocket, "this channel accepts no client-to-server messages"
        )
        return


```

Quarkus's backstop for anything that reaches the framework unhandled closes with `1011` if the socket is still open:

```java
    @OnError
    public Uni<Void> onError(Throwable t) {
        String bookingId = connection.pathParam("bookingId");
        Log.errorf(t, "handling-events unexpected error bookingId=%s", bookingId);
        if (connection.isOpen()) {
            return connection.close(new CloseReason(CloseCodes.UNEXPECTED_SERVER_ERROR, "unexpected server error"));
        }
        return Uni.createFrom().voidItem();
    }
```

- **Send, then close, in sequence.** `Uni.chain()` and Python's two awaits both finish handing the envelope to the transport before the close frame follows. Only that order lets a client's message handler see the envelope before its close handler fires. Reversed or raced, the client cannot read a body off a connection already declared over.
- **One outcome for every case.** Both stacks distinguish binary, invalid JSON, a non-object and a well-formed object, so the logged reason is specific. All four end in `BAD_REQUEST` and `4400`; the specificity is for the developer reading the message.
- **`onError` is a last resort.** Auth and malformed-frame handlers close the connection themselves rather than throwing, so it only sees what nobody mapped: a conversion error, or a failure from `OutboundBackpressureGuard` not already turned into `4290`. Python's equivalent is the outer `try`/`except` in `handler()`: `SlowConsumerError` closes `4290`, `ConnectionClosed` is logged and ignored because the client already left, and a bare `Exception` closes `1011`.

## What the client observes

For a malformed frame the client sees two events in a fixed order: a message carrying the envelope's JSON, indistinguishable at the transport level from any other text frame, then a close with `code=4400` and the server's reason string. The client must wire both handlers and check each message for an `error` key before treating it as a push frame. Nothing routes error frames to a different callback.

A peer that vanishes with no handshake (a killed process, a partition, a pulled cable) is the gap no close code can fill. `1006` is one of two codes (`1005` is the other) that an implementation must never place in a close frame. It is a value a client API reports locally when a connection ends without a completed close handshake. No server sent it or could have, because by the time it is reported there was no connection left. A client tested only against the `4400` path will mishandle `1006`, since it bypasses the envelope-then-close sequence entirely. This is also why a server closes every open connection with `1001` on graceful shutdown: otherwise clients would see the drop as an abnormal closure.

{% include excalidraw.html file="13-error-flow-vs-1006" alt="Two parallel flows. On the left, a protocol error: the server sends an error envelope, then closes with 4400, so the client sees a message and then a close. On the right, a peer that vanishes with no close handshake: nothing is sent, and the client runtime synthesizes a local close with code 1006." caption="Figure 13.2: The envelope-then-close sequence, next to the one failure no close code can carry: a peer that vanished before any handshake." %}

## What a client does with each code

A close code is an input to the client's reconnect decision. A universal "reconnect with exponential backoff and jitter" is a reasonable default, but it misses cases where blind retry is pointless or harmful:

| Code | Retry? | Why |
|---|---|---|
| `4400` `BAD_REQUEST` | No | The same frame produces the same rejection. This is a client bug, and a loop that retries every close spins forever |
| `1008` `AUTH_FAILURE` | After a fresh token | The same expired or badly signed token fails forever. At scale, blind retries resemble the probing that the no-oracle design resists |
| `4290` `SLOW_CONSUMER` | With backoff, after the client is fixed | Reconnecting into the same consumption pattern trips `4290` again. The client must process faster or accept `DROP_OLDEST`-style loss on its own inbound buffer |
| `4408` or `1011` (keepalive) | Yes | The peer stopped answering pings, which says nothing about the next attempt |
| `1011` `UNEXPECTED_SERVER_ERROR` | Yes, with backoff | The backstop for an unhandled case. Giving up risks abandoning a transient blip; retrying is the reasonable default |
| `1001` `GOING_AWAY` | Yes, expected | The server asked every client to come back later, as in a deploy or restart |
| `1006` | Yes, with backoff | It carries no information beyond "the connection is gone," so it gets the same loop as any unplanned drop |

A client that maps every close to "retry," or every close to "give up," discards the information the taxonomy exists to provide.

> **Decision**
>
> Reuse RFC 6455 codes only for their standard meaning, and put every code you invent in `4000` to `4999`. Send an error envelope, then close, only when a specific frame is at fault and the socket is open; otherwise close with the code alone, and never explain an auth failure on the wire. Treat each close code as input to a retry decision, and handle `1006` locally because no server can send it.

> **🤖 Explore with your agent**
>
> "In `examples/part4-connection`, connect to `/ws/v1/bookings/{bookingId}/handling-events` on the Quarkus server (`localhost:8080`) and the Python server (`localhost:8081`) with a valid token, send `{\"not\":\"valid\"}`, and report the frames received and the close code from each. Then write a reconnect function that returns false for `4400` and `1008` and true for `4290`, `4408`, `1011`, `1001` and `1006`, and explain each case."
>
> Check: both stacks report one frame (a `BAD_REQUEST` envelope) and close code `4400`; the function returns false only for `4400` and `1008`.

## Build, run, observe

```bash
cd examples/part4-connection
./verify.sh
```

`websocat` cannot observe close codes reliably, so `verify.sh` uses a small Python probe built on the `websockets` library. It connects, sends `{"not":"valid"}`, reads every frame until the connection closes, and reports the frame count, whether a `BAD_REQUEST` envelope arrived, and the close code. It runs once against Quarkus on `localhost:8080` and once against Python on `localhost:8081`, and the output has the same shape for both:

```json
{"frames": 1, "envelope_bad_request": true, "close_code": 4400}
```

One frame (the envelope alone, since the fixture replay was never reached), the envelope flag true, and `4400` on both stacks. A full passing run prints `PASS: ` at the end.

- Send a binary frame or invalid JSON instead of `{"not":"valid"}`: the reason in the envelope changes, but the close code stays `4400`.
- Connect with an expired or badly signed token: the close is `1008` with no envelope.

## For deeper coverage

- Michael T. Nygard, *Release It!, Second Edition* (Pragmatic Bookshelf, 2018): the retryable-versus-not distinction per failure, and why treating every failure as transient is a failure mode of its own.
- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022): error-reporting patterns for message-based APIs, including when a machine-readable error body belongs on the wire.
- *Cloud Native Design Patterns*, "API Error Handling" chapter: error taxonomies and in-band error payloads for an API's non-happy paths.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: the broader catalog of ways a connection or call fails, including the "vanished with no signal" case that `1006` represents.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455): section 7.4's close-code ranges and the reserved `1005` and `1006`.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `receiveHandlingEvent` operation's single direction, which makes every client-sent frame wrong by construction.
