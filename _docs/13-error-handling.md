---
title: "Error Handling"
order: 13
part: "Production Concerns"
description: "Modeling and surfacing errors over a connection that has no status codes of its own."
duration: "16 min read"
---

## Learning objectives

By the end of this chapter you can:

- Place a close code into RFC 6455's `1000`–`2999` protocol range or its `4000`–`4999` private-use range, and explain why every code this chapter invents (`4400`, `4290`, `4408`) lives in the private range.
- Apply the envelope-then-close rule: send an `ErrorEnvelope` first while the socket is still open and there's a specific frame to annotate, rely on the close code alone when there isn't or when replying would open a signature oracle.
- Explain why `1006` can never be sent by either stack's `ErrorEnvelope`/`CloseCodes` machinery, and why a client's reconnect logic still has to handle it.
- Map each close code this channel uses to a retry decision: not retryable (`4400`), conditionally retryable (`1008`), or retryable with backoff (everything else), rather than treating every close as "reconnect."
- Account for the one disclosed cross-stack mismatch, Quarkus's `4408` versus Python's library-default `1011` for the identical liveness condition, in a client meant to work against either server.

## Why this matters

An HTTP response to a bad request carries its own verdict: `400`, `401`, `429`, `500` arrive in the status line before a single byte of body is read, and a client branches on that number without parsing anything else. A WebSocket connection has no equivalent. Once the upgrade handshake completes, every frame that crosses the wire is just a frame, text or binary; no header field marks one as "this is an error" and another as "this is data." `examples/part4-connection` is where this book's running example first has to answer a question an HTTP status line answers without any extra application code: the `handlingEvents` channel (`contracts/asyncapi.yaml`'s `operations.receiveHandlingEvent`) defines exactly one valid direction (server to client), so by construction, anything a client sends on it is wrong, and this chapter is about the two mechanisms available for saying so: a close code the transport itself carries, and an in-band JSON envelope the application has to invent. Both the Quarkus implementation (`quarkus/.../connection/HandlingEventConnectionWebSocket.java`, `ErrorEnvelope.java`, `CloseCodes.java`) and the Python one (`python/app/ws_server.py`, `python/app/auth.py`) answer identically, down to the JSON shape and (mostly) the numeric codes, and `verify.sh`'s error-taxonomy step proves that identity live against both.

## No status line, two signaling channels

RFC 6455 gives a closing connection exactly one structured piece of information beyond "it's closing": a 16-bit close code and an optional UTF-8 reason string, both carried in the close frame itself (section 7.4). That's the entire built-in vocabulary. There is no WebSocket equivalent of an HTTP response header, no standard place to attach a machine-readable error body, and critically, the close code only exists at the moment the connection is ending; it tells a client *that* something went wrong and, if the code is specific enough, roughly *what* category, but it arrives too late to carry a sentence of detail a developer debugging their own client could act on. `CloseCodes.java`'s class-level Javadoc states this directly: a close code "carries no human-readable detail and arrives only as the socket is going away, which is too late for a client developer to see anything more useful than 'it closed.'" The Python sibling's `ws_server.py` module docstring makes the identical argument in different words: a close code alone "arrives after the connection is already gone; too late for the client to log anything but 'it closed.'"

So every WebSocket application doing real error handling ends up building a second, in-band channel on top of the one RFC 6455 provides, and this example is no exception. `ErrorEnvelope.java` defines `{"error":{"code":"BAD_REQUEST","message":"..."}}` as a plain JSON text frame, sent while the connection is still open, read by the exact same message handler a client already has wired up for ordinary `HandlingEvent` push frames. Nothing about the WebSocket protocol tells a client "the next frame is an error, parse it differently"; the envelope is a convention this application layer defines and both stacks honor identically, not a framing-level feature either `quarkus-websockets-next` or Python's `websockets` library provides. That's the structural fact this whole chapter sits on top of: a close code is cheap, transport-level, and arrives last; an envelope is applicationlevel, requires the socket still be open to send it, and arrives first. Everything else in this chapter is about choosing between them, or using both.

## The close-code taxonomy: RFC 6455's ranges, and this site's application range

RFC 6455 section 7.4.1 reserves four numeric bands for close codes, and understanding which band a given code lives in is what lets a client tell "this is a standard, protocol-level reason" from "this is an application convention it needs this specific service's documentation to decode." `1000`-`2999` is the protocol's own range: codes `1000` through `1015` are defined (`1000` normal closure, `1001` going away, `1002` protocol error, `1003` unsupported data, `1007` invalid payload, `1008` policy violation, `1009` message too big, `1010` mandatory extension, `1011` internal error; a few, like `1005` and `1006`, are reserved specifically so they can *never* appear in an actual close frame, which the next section comes back to), and `1016`-`2999` is reserved for future protocol revisions nobody should be using yet. `3000`-`3999` is registered through IANA for libraries and frameworks that want a standard code without squatting on the protocol's own range. `4000`-`4999` is explicitly private-use: the one band RFC 6455 sets aside for an application to define its own vocabulary with zero risk of colliding with a future protocol-level code.

`CloseCodes.java` places every code this example uses into exactly one of those bands, and says so in its own Javadoc rather than leaving a reader to look the numbers up:

- **`1008`: `AUTH_FAILURE`**, RFC 6455's standard "policy violation," reused as-is for a JWT that's missing, malformed, badly signed, or expired.
- **`1011`: `UNEXPECTED_SERVER_ERROR`**, RFC 6455's standard "unexpected condition," for an unmapped server-side exception, this chapter's backstop.
- **`1001`: `GOING_AWAY`**, RFC 6455's standard code, used by `ConnectionLifecycleShutdown` on graceful application shutdown.
- **`1000`**: normal closure, the one every WebSocket library defaults to for a clean, mutually-agreed close with nothing to explain.
- **`4400`: `BAD_REQUEST`**, placed *outside* the RFC 6455 range and into `4000`-`4999` precisely so it "can't be confused with an RFC 6455 standard code" (the Javadoc's own words); this is this chapter's main subject, for a client text or binary frame outside the contract.
- **`4290`: `SLOW_CONSUMER`**, same private-use range, the backpressure `CLOSE` policy.
- **`4408`: `LIVENESS_TIMEOUT`**, same private-use range, the heartbeat mechanism's dead-peer detector, named after HTTP 408 Request Timeout for the mnemonic, not because it reuses anything HTTP-specific.

The pattern is deliberate, not accidental: every code this application invents (`4400`, `4290`, `4408`) lives in the `4000`-`4999` band, and every code this application reuses (`1008`, `1011`, `1001`, `1000`) is an RFC 6455 standard code being used for exactly the meaning the spec already assigns it. A client's reconnect logic can use the band itself as a first signal before it even needs this example's specific documentation: a code starting with `1` is a protocol-level reason a generic WebSocket client library might already know how to interpret, a code starting with `44` is this application's own convention and the client needs this chapter (or the README's close-code table) to know what it means.

One mismatch is a real, documented difference rather than an oversight, named directly: Quarkus's liveness detector closes a silent dead peer with `4408`, but the Python sibling's equivalent condition, the `websockets` library's own `ping_timeout` keepalive firing, closes with that library's hardcoded `1011`. `CloseCodes.java`'s Javadoc documents this explicitly: "The two stacks therefore agree on when a silent peer is closed, but not on the exact close code; documented here rather than silently left inconsistent." Giving a library-default behavior its own app-range code would have meant wrapping or overriding that library's keepalive machinery, which the Javadoc calls "out of scope for this chapter." A client written against both stacks has to tolerate seeing either `4408` or `1011` for the same underlying condition, a silent peer, which is exactly the kind of two-stack seam running one contract against two independently built stacks exists to surface rather than paper over.

{% include excalidraw.html file="13-error-decision-tree" alt="A decision tree. At the top, a box reads Something went wrong on this connection, with an arrow down to a decision box: Is there one specific offending frame to annotate, and is the socket still open to send on? A yes arrow goes left to a box: YES, e.g. a malformed client frame -- 1. send ErrorEnvelope while still open, 2. THEN close with BAD_REQUEST / 4400, with an amber arrow down to a note: client's normal message handler sees WHY. A no arrow goes right to a box: NO, no single frame to blame, or the socket is already gone -- close code ALONE is the signal, listing AUTH_FAILURE 1008, SLOW_CONSUMER 4290, LIVENESS_TIMEOUT 4408, UNEXPECTED 1011. A caption at the bottom reads: a close code alone arrives as the socket is going away, too late to carry detail -- the envelope is sent first, while the connection is still open." caption="Figure 13.1: the one decision CloseCodes.java's Javadoc states for every failure on this channel: is there a specific frame to annotate, while the socket is still open?" %}

## Envelope first, then close: the two-signal pattern and when to use which

With the taxonomy in hand, the actual decision this example's code makes is narrow enough to state in one sentence, and `CloseCodes.java`'s Javadoc states it almost exactly this way: send the envelope when there's a specific offending message to annotate and the connection is still open to send it on; rely on the close code alone when there isn't. Of the four application-specific failure modes this channel has, exactly one, the malformed-client-frame case this chapter is named for, gets both signals. The other three don't, and the Javadoc explains why for each: auth failure and backpressure both close "before any data has been streamed on the connection," so there's no established protocol moment yet in which an envelope would make sense to a client that hasn't received its first real frame either; an unmapped server exception closes "after the connection is already in an unknown state," where attempting to send a well-formed JSON envelope first risks failing on an already-broken channel for no benefit.

This is worth contrasting with a design that always sends an envelope before every close, which would look more "consistent" on paper and is worse in practice. An envelope sent on an auth rejection would mean replying, even briefly, to a connection the server hasn't yet decided is worth talking to. For auth specifically, that reply is itself the oracle an attacker probing the channel wants: different response shapes for "missing token" versus "bad signature" versus "expired token" would let a prober learn which check failed one bit at a time. `auth.py`'s `AuthError` class docstring states this concern directly: "the specific reason is logged server-side ... but never echoed back to the client on the wire, to avoid handing a prober a signature oracle." Collapsing every auth failure to the same `1008` close with no envelope and no distinguishing reason string follows the same "distinct failures as one payload-free signal" principle this example also uses to collapse missing, malformed, badly-signed, and expired tokens into the identical rejection. Figure 13.1's decision tree asks two separate questions at once: is there something worth saying, and is it safe to say it. For auth, the answer to the second question is no by design, even when the first answer might be yes.

## Two stacks, one mapping: the envelope shape and the handlers that send it

Both stacks define the envelope as the identical JSON shape, independently, in their own idiom. The Quarkus side is a Jackson-serializable record; the Python side is a plain dict built by a small function with the same two fields.

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
    """The in-band JSON error shape sent before a 4400 close ... `BAD_REQUEST`
    is the only code this channel emits today (every client-sent frame is
    invalid, since the contract defines no client-to-server operation on
    this channel); a richer channel with multiple failure modes would add
    more `code` values here."""
    return {"error": {"code": "BAD_REQUEST", "message": message}}
```

`BAD_REQUEST` is the only `code` value either side ever emits, and both Javadocs/docstrings say so explicitly rather than leaving it implicit: this channel has exactly one client-to-server failure mode (any frame at all is wrong), so a richer `code` enum would be speculative infrastructure for a case this contract doesn't have. A channel with an actual client-to-server operation, one where *some* requests are valid and others fail validation in distinguishable ways, is where a real `code` taxonomy (`INVALID_FIELD`, `UNKNOWN_OPERATION`, and so on) would be justified; this one doesn't need it yet.

The handlers that build and send that envelope are where the two stacks' idioms diverge the most, because Quarkus's `@OnTextMessage`/`@OnBinaryMessage`/`@OnError` annotations and Python's single `async for` receive loop are structurally different ways of reaching the same three-stage decision: classify the frame, send the envelope, then close.

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

private Uni<Void> rejectMalformed(String reason) {
    String bookingId = connection.pathParam("bookingId");
    Log.warnf("handling-events connection bookingId=%s sent an unexpected client frame: %s", bookingId, reason);
    return connection.sendText(ErrorEnvelope.badRequest(reason))
            .chain(() -> connection.close(new CloseReason(CloseCodes.BAD_REQUEST, "malformed client message")));
}

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
```python
async def _reject_malformed(websocket: ServerConnection, reason: str) -> None:
    await websocket.send(json.dumps(_error_envelope(reason)))
    await websocket.close(code=CLOSE_CODE_MALFORMED, reason="malformed client message")

async def _receive_loop(websocket: ServerConnection) -> None:
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
        await _reject_malformed(websocket, "this channel accepts no client-to-server messages")
        return
```

Three things to notice in that pair. First, both `rejectMalformed` and `_reject_malformed` chain the send and the close into one sequential operation rather than firing them independently: Quarkus's `Uni.chain()` and Python's two sequential `await`s both guarantee the envelope is fully handed to the transport before the close frame follows it, which is the only ordering that lets a client's `onmessage` handler see the envelope before its `onclose` handler fires. Reversing that order, or racing the two, would make the two-signal design from the previous section pointless: a client can't read a body off a connection that already told it the connection is over. Second, both classify the *same* three cases in the *same* order purely to make the logged/returned `reason` specific rather than because any of this book's clients act differently on each one: not text/JSON, not a JSON object, or (the only remaining case, since nothing is ever accepted) a well-formed JSON object anyway. Every one of those three reasons still maps to the identical `BAD_REQUEST`/`4400` outcome; the specificity is for the developer reading the message, not for branching logic. Third, Quarkus's `onError` is the exception-mapping backstop this section's title promises: a `Throwable` that reaches this method never went through `rejectMalformed` at all, which is a conversion error, an unmapped failure out of `OutboundBackpressureGuard`, or anything else nobody wrote an explicit handler for. Its Javadoc is explicit about scope: "the auth check and the malformed-message handlers above close the connection themselves rather than throwing, so they never reach this method." `onError` is a last resort, not the primary error path; the pattern this chapter teaches routes through `rejectMalformed`, not through the generic exception mapper. Python's structural equivalent isn't a single annotated method but the outermost `try`/`except` in `handler()`: a `SlowConsumerError` closes `4290`, a `ConnectionClosed` is logged and swallowed (the client already left), and a bare `except Exception` closes `1011`, the same three-tier shape (specific handled cases, an expected-and-benign case, a generic backstop) expressed as ordinary Python control flow instead of framework callbacks.

## What the client observes

From outside the server, this whole mechanism collapses to two events on whatever WebSocket client API is listening, in a fixed order for the malformed-frame case: an `onmessage` (or its stack's equivalent, a message received off an `async for` loop, a `@OnTextMessage` callback on a reconnecting client) carrying the envelope's raw JSON text, indistinguishable at the transport level from any other text frame this channel could have sent; nothing in the frame itself marks it as an error, which is precisely why the envelope's own JSON shape (`{"error": {...}}`) has to be the thing a client checks for, not a framing bit. Then, some short time later, an `onclose` fires with `code=4400` and whatever reason string the server supplied. A client has to have both handlers wired up and has to know to look inside a message for an `error` key before assuming it's a normal push frame; there is no protocol-level shortcut that routes error frames to a different callback automatically.

Contrast that with what a client sees when a peer disappears with no handshake at all, a killed process, a network partition, a cable pulled mid-stream, because this is the gap no close code, application-range or otherwise, can ever fill. `ConnectionLifecycleShutdown.java`'s own Javadoc names the alternative directly, explaining why it closes every open connection with `1001` on a graceful shutdown rather than just letting the process exit: a client would otherwise see the drop "as an abnormal closure, code 1006." `1006` is one of the two RFC 6455 close codes (`1005` is the other) that a conforming implementation is required to *never* place in an actual close frame on the wire; it exists purely as a value a client-side API is allowed to report locally when the underlying connection ends without a close handshake completing at all. No server sent it; no server could send it, because by the time it's reported, there was no opportunity left to send anything. It's the client runtime's own synthesized answer to "well, *something* happened, and it definitely wasn't a clean close," the WebSocket equivalent of a TCP connection reset with nobody left to explain why. A client that only ever tested its error handling against this chapter's `4400` path and never against a hard-killed server would ship with an `onclose` handler that mishandles `1006`, because `1006` never arrives through any path this chapter's `ErrorEnvelope`/`CloseCodes` machinery touches; it bypasses the entire envelope-then-close sequence by definition, since there's no connection left standing to send an envelope on.

{% include excalidraw.html file="13-error-flow-vs-1006" alt="Two parallel flows. Left, labeled Protocol error -- verify.sh Ch13 step, both stacks: client sends a client-to-server frame (channel defines none), server's onTextMessage or _receive_loop classifies why, server sends the ErrorEnvelope with code BAD_REQUEST, then closes with BAD_REQUEST -- client onmessage fires first with the envelope, then onclose fires with code 4400. Right, labeled Peer disappears -- no close handshake at all: process killed or network partition or cable pulled, no FIN and no close frame; no ErrorEnvelope is possible because the server never got a chance to send one; the peer's TCP stack eventually gives up or never notices; the client runtime synthesizes onclose with code 1006 abnormal closure locally, shown with a dashed amber arrow since nothing was sent on the wire. A caption reads: 1006 is a reserved RFC 6455 value an implementation must never put in an actual close frame -- it exists only for a local API to report the connection ended with no handshake." caption="Figure 13.2: the envelope-then-close sequence this chapter builds, next to the one failure mode no close code can ever carry: a peer that vanished before any handshake could complete." %}

## Idempotency and retriability: what a client should do with each code

A close code's real job, once a connection has ended, is telling a client's reconnect logic (built earlier for the outbound side; the client the server expects to be on the other end of this channel has the identical shape) whether trying again makes sense at all, and if so, whether to try again immediately or back off. Not every code in this chapter's taxonomy answers that question the same way, and collapsing them to one universal "reconnect with backoff" policy, a reasonable *default*, and exactly what the exponential-backoff-with-jitter reconnect loop implements, misses a few cases where blind retry is either pointless or actively wrong:

- **`4400` `BAD_REQUEST`** is *not* retryable in the sense that matters: reconnecting and sending the exact same malformed frame again produces the exact same rejection, because the server's behavior didn't change and the contract still defines no client-to-server operation on this channel. This is a client bug, not a transient condition; the correct response is fixing the client, not backing off and trying the identical request again. A reconnect loop that treats every close as "try again" will happily spin forever against this one without ever making progress, logging the same `BAD_REQUEST` on every attempt.
- **`1008` `AUTH_FAILURE`** is conditionally retryable: retrying with the *same* expired or bad-signature token produces the same rejection forever, but retrying after minting a fresh token (the actual fix) succeeds immediately. A client's reconnect logic needs to distinguish "the connection dropped" from "the connection was refused for a reason retrying the transport layer can't fix"; blindly reconnecting with a token that's already proven invalid wastes the connection attempt and, at scale, resembles the probing pattern `auth.py`'s no-oracle design was built to resist.
- **`4290` `SLOW_CONSUMER`** is retryable, but only meaningfully if whatever made the client slow gets fixed first: reconnecting into the same consumption pattern that triggered the close in the first place just produces another `4290` after another burst. This is the server-side mirror of the client-side `BLOCK`/`DROP_OLDEST` choice: a client that got closed for being slow needs to either process faster or accept `DROP_OLDEST`-style loss on its own inbound buffer, not just reconnect and hope.
- **`4408` `LIVENESS_TIMEOUT`** (Quarkus) and the Python sibling's `1011` keepalive-failure equivalent are both straightforwardly retryable: the peer was closed because it stopped answering pings, which says nothing about whether the *next* connection attempt will succeed, and detecting this faster than TCP would on its own, so a reconnect can happen sooner, is the whole point of the heartbeat mechanism.
- **`1011` `UNEXPECTED_SERVER_ERROR`** is ambiguously retryable by design: it's the backstop for a case nobody wrote specific handling for, so a client can't know from the code alone whether the underlying condition will have cleared by the next attempt. Treating it like `4290`/`4408` (retry with backoff) is the reasonable default; treating it like `4400` (stop immediately) risks giving up on a transient server-side blip that a human hasn't yet diagnosed.
- **`1001` `GOING_AWAY`** is retryable and *expected* to be retried: this is the server asking every connected client to come back later, so a deploy or restart doesn't look like a crash to anything watching. Stateless reconnect handling names this pattern formally.
- **`1006`**, the abnormal closure covered above, gets the same treatment as `1001` from a well-behaved client: there's no information in it beyond "the connection is gone, unexpectedly," so the correct response is exactly the exponential-backoff-with-jitter reconnect loop already built, the same loop that handles every other unplanned drop, because `1006` by construction carries no signal that would justify treating it any differently.

The pattern across all seven: the close code is the input to a client-side decision, not the decision itself, and a client that maps every close indiscriminately to "retry" or indiscriminately to "give up" is throwing away exactly the information this chapter's taxonomy exists to provide.

## On the wire

`examples/part4-connection/verify.sh` proves the envelope-then-`4400` sequence live against both running stacks, not just in Javadoc and docstrings. Because `websocat` can't observe close codes reliably (both app READMEs note this), the script uses a small, purpose-built Python probe (`ws_close_probe`, fetched into an ephemeral `uv run --with websockets` venv) that connects, sends one malformed frame, reads every frame the server sends back until the connection closes, and reports whether a `BAD_REQUEST` envelope arrived and what close code followed:

```bash
ws_close_probe() {
  local url="$1" payload="${2:-}"
  uv run --with websockets python3 -I -c '
import asyncio, json, sys
import websockets
from websockets.exceptions import ConnectionClosed

async def main():
    url = sys.argv[1]
    payload = sys.argv[2] if len(sys.argv) > 2 else ""
    frames = 0
    envelope_bad_request = False
    async with websockets.connect(url) as ws:
        if payload:
            await ws.send(payload)
        try:
            async for message in ws:
                frames += 1
                try:
                    doc = json.loads(message)
                except Exception:
                    continue
                if isinstance(doc, dict) and isinstance(doc.get("error"), dict) \
                        and doc["error"].get("code") == "BAD_REQUEST":
                    envelope_bad_request = True
        except ConnectionClosed:
            pass
        print(json.dumps({
            "frames": frames,
            "envelope_bad_request": envelope_bad_request,
            "close_code": ws.close_code,
        }))

asyncio.run(main())
' "$url" "$payload" 2>/dev/null
}
```

`run_stack_auth_and_error_tests` calls that probe once per stack against the same `{% raw %}{bookingId}{% endraw %}` channel path from this book's shared fixture, sending a well-formed-but-invalid-for-this-channel JSON object as the malformed frame, then asserts on both fields the envelope-then-close design produces:

```bash
echo "--- Ch13 error taxonomy: malformed client frame -> envelope + close 4400 ---"
local probe_result close_code envelope_ok
probe_result="$(ws_close_probe "${base_url}?token=${VALID_TOKEN}" '{"not":"valid"}')"
echo "lib.sh: $stack error-taxonomy probe result: $probe_result" >&2
close_code="$(json_field '.close_code' <<<"$probe_result")"
envelope_ok="$(json_field '.envelope_bad_request' <<<"$probe_result")"
assert_eq "4400" "$close_code" "$stack error-taxonomy close code"
assert_eq "true" "$envelope_ok" "$stack error-taxonomy BAD_REQUEST envelope received"
```

That block runs twice in one `verify.sh` pass, once against `localhost:8080` (Quarkus, Step 3) and once against `localhost:8081` (Python, Step 4), with the identical `{"not":"valid"}` payload and the identical two assertions, which is exactly the point: the probe can't tell which stack it's talking to from the response shape, because both stacks were built to make that true. Run it yourself from the repo root:

```bash
cd examples/part4-connection
./verify.sh
```

A passing run's Step 3/Step 4 output for this check looks like `lib.sh: quarkus error-taxonomy probe result: {"frames": 1, "envelope_bad_request": true, "close_code": 4400}` followed by the Python equivalent on port `8081`: one frame received (the envelope, nothing else, since the fixture replay was never reached), `envelope_bad_request` true, and `close_code` exactly `4400` on both stacks. The script only prints its final `PASS` line if every assertion across all six of its steps holds, this one included.

## Where this goes next

This chapter built the narrower half of error handling a socket needs that a request/response protocol gets from its status line alone: a taxonomy for the sixteen-bit close code RFC 6455 provides, a private-use range (`4000`-`4999`) for the codes this application had to invent, and a disciplined rule, envelope first while the socket is open, close code alone when it isn't or when saying more would be unsafe, for when to reach for each. It also drew the line this chapter's own machinery can never cross: `1006`, the abnormal closure a client synthesizes locally when a peer vanishes with no handshake at all, which no `ErrorEnvelope` and no close code this server sends can ever touch, because by the time it's reported there was no connection left to send anything on. The heartbeat machinery (`HeartbeatLivenessSweep`, the `websockets` library's own `ping_interval`/`ping_timeout`) picks up immediately where that gap matters most in practice: a silent peer that hasn't technically disappeared yet, detected and converted into a specific-reason close (`4408`, or Python's `1011`) rather than letting a dead connection sit silent until some other timeout notices. Stateless reconnect handling builds on the constraint this chapter's "which codes are retryable" section already leaned on, and Kafka-backed reconnect builds the alternative that removes it. The auth gate this chapter chose not to put an envelope in front of gets its own full treatment under security.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>A WebSocket connection has exactly one built-in error channel: a 16-bit close code, arriving only as the socket is already ending, with RFC 6455 reserving <code>0</code>-<code>2999</code> for the protocol itself and <code>4000</code>-<code>4999</code> for private application use. This example's <code>CloseCodes.java</code> places every code it reuses (<code>1008</code> auth, <code>1011</code> unexpected error, <code>1001</code> going away, <code>1000</code> normal) in the RFC range with RFC's own meaning intact, and every code it invents (<code>4400</code> malformed frame, <code>4290</code> backpressure, <code>4408</code> liveness) in the private range so it can never collide with a future standard code. On top of that, both stacks build a second, in-band JSON envelope (<code>{"error":{"code":"BAD_REQUEST","message":"..."}}</code>) for the one failure mode with both a specific offending frame to explain and a still-open socket to explain it on, sent first, with the close following immediately after, never the reverse. Every other failure (auth, backpressure, an unmapped exception) relies on the close code alone, by design: there's either no single frame to blame or, for auth specifically, replying at all before authentication succeeds would open a signature oracle. No close code, in either range, can ever represent a peer that vanished before any handshake completed: that's <code>1006</code>, a value RFC 6455 forbids putting on the wire, synthesized locally by the client's own runtime. Treat a close code as an input to a retry decision, not the decision itself: <code>4400</code> means fix the client, not retry it; <code>1008</code> means fix the token first; everything else, <code>4290</code>, <code>4408</code>/<code>1011</code>, the generic <code>1011</code> backstop, <code>1001</code>, and <code>1006</code> alike, funnels into the same exponential-backoff-with-jitter reconnect loop built for every other unplanned drop, because none of them carry a reason retrying blindly would make worse.</p></div>

## For deeper coverage

- Michael T. Nygard, *Release It!, Second Edition* (Pragmatic Bookshelf, 2018): the retryable-versus-not distinction this chapter draws per close code, and why treating every failure as transient is its own failure mode.
- Olaf Zimmermann, Mirko Stocker, Daniel Lübke, Uwe Zdun & Cesare Pautasso, *Patterns for API Design* (Addison-Wesley, 2022): error-reporting patterns for a message-based API, including when a machine-readable error body belongs on the wire and when it doesn't.
- *Cloud Native Design Patterns*, "API Error Handling" chapter: error taxonomies and in-band error payloads for an API's non-happy paths, the same problem this chapter solves for a channel with no status line.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: the broader catalog of ways a connection or a call fails, including the "something vanished with no signal at all" case `1006` represents here.
- [RFC 6455](https://www.rfc-editor.org/rfc/rfc6455): section 7.4's close-code ranges and the reserved status of `1005`/`1006`, the two codes a conformant implementation must never place in an actual close frame.
- [AsyncAPI 3.0 specification](https://www.asyncapi.com/docs/reference/specification/v3.0.0): the `receiveHandlingEvent` operation's single direction, the contract fact that makes every client-sent frame on this channel wrong by construction.
