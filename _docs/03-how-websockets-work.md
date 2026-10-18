---
title: "How WebSockets Work"
order: 3
part: "Foundations"
description: "The HTTP upgrade handshake, frame types, close codes, and subprotocols under RFC 6455."
duration: "18 min read"
---

Chapter 2 picked WebSockets over SSE, long-polling, and webhooks for this site's handling-event feed on the strength of one property: a WebSocket is bidirectional and holds one connection open for as long as the client cares to watch a booking. That claim has stayed abstract until now. This chapter names the mechanism underneath it — the HTTP Upgrade handshake that turns an ordinary request into a long-lived socket, the frame format RFC 6455 defines for everything that crosses that socket afterward, the control frames that keep a connection alive and end it cleanly, and the parts of the surrounding stack — TLS, proxies, load balancers — that have opinions about a connection that refuses to close. Chapter 4 picks up the handling-event payloads this protocol will carry; this chapter is only the protocol.

## The upgrade handshake

A WebSocket connection starts as a normal HTTP request. There is no separate port, no separate listener, and no new transport underneath it — the client opens a TCP connection to the server exactly as it would for any `GET`, and the first bytes on that connection are an HTTP/1.1 request line and headers. What makes the request a WebSocket handshake rather than a page fetch is a specific set of headers the client adds, and a specific status code the server is allowed to reply with.

The client's request carries:

- `Upgrade: websocket` — "I'd like to stop speaking HTTP on this connection after this response."
- `Connection: Upgrade` — required alongside it, because `Upgrade` by itself is a hop-by-hop header a proxy could otherwise drop.
- `Sec-WebSocket-Version: 13` — the only version RFC 6455 defines; a server that doesn't support it responds `426 Upgrade Required` with a `Sec-WebSocket-Version` header listing what it does support.
- `Sec-WebSocket-Key` — a random, base64-encoded 16-byte value, generated fresh per connection.

A server that wants to accept the upgrade replies `101 Switching Protocols` instead of `200 OK`, and echoes the handshake back with its own required header:

- `Upgrade: websocket` and `Connection: Upgrade`, mirroring the request.
- `Sec-WebSocket-Accept` — not an echo of the key, but a value *derived* from it.

The derivation is the one piece of real cryptographic-looking machinery in the whole handshake, and it exists for a narrow reason. The server takes the client's `Sec-WebSocket-Key`, concatenates it with a fixed GUID the RFC hardcodes (`258EAFA5-E914-47DA-95CA-C5AB0DC85B11`), runs the result through SHA-1, and base64-encodes the digest. The client performs the identical computation on the key it sent and checks the server's answer matches. This isn't authentication and isn't meant to be — the GUID is public, published in the spec text, so anyone can compute the right answer for any key. Its job is narrower: proving the server on the other end understood this was a WebSocket upgrade request and ran RFC 6455's handshake logic, rather than being an HTTP cache, a misconfigured proxy, or some other intermediary that echoed the request back without understanding it. A caching proxy that blindly replayed a prior response, or a server that doesn't implement WebSockets but happens to accept arbitrary `Upgrade` headers, would fail this check because it never computed the hash at all.

Once the client validates `Sec-WebSocket-Accept`, both sides agree: this TCP connection no longer carries HTTP request/response pairs. Every byte from here on is a WebSocket frame, in both directions, until one side closes the connection.

{% include excalidraw.html file="03-upgrade-handshake" alt="Sequence diagram of a client opening a WebSocket connection to a server: an HTTP GET with Upgrade, Connection, and Sec-WebSocket-Key headers; the server computing Sec-WebSocket-Accept from the key and a fixed GUID; a 101 Switching Protocols response carrying that Accept value; then both sides exchanging WebSocket frames over the same TCP connection with no further handshake." caption="Figure 3.1 — One HTTP request becomes a long-lived socket: the 101 response is the whole handshake." %}

The handshake only ever happens once per connection. Nothing about a WebSocket connection re-negotiates the Upgrade on every message the way HTTP/1.1 without keep-alive re-negotiates a TCP connection on every request; the entire point of paying for one handshake is amortizing it across every frame that follows, for however long the client keeps watching that booking.

## Frame anatomy

After the 101, the two endpoints still disagree about one thing conceptually useful to separate from each other: an application sends and receives *messages* — a JSON document describing one handling event, for instance — but the wire carries *frames*, and a message can be split across more than one frame. RFC 6455 defines the frame as the one structure every byte on a WebSocket connection belongs to.

A frame's first two bytes carry almost everything a receiver needs to know before it reads the payload:

- **FIN** (1 bit) — set on the last frame of a message. A message fragmented across several frames sets FIN=0 on every frame but the last, letting a sender start transmitting a large message before the whole thing is serialized, or interleave control frames (a ping) between data fragments. Most messages this site's examples send fit in one frame, so FIN=1 on the first and only frame is the common case.
- **RSV1-3** (3 bits) — reserved for extensions negotiated during the handshake (permessage-deflate, covered in the next section, uses RSV1). Zero unless an extension defines otherwise.
- **Opcode** (4 bits) — what kind of frame this is: `0x0` continuation, `0x1` text, `0x2` binary, `0x8` close, `0x9` ping, `0xA` pong. Text and binary carry application payloads; the other four are control frames, covered next.
- **MASK** (1 bit) — whether the payload that follows is XOR-masked. Every frame a client sends must set this bit; every frame a server sends must not. This isn't symmetric by accident or oversight — the next section explains why.
- **Payload length** (7 bits, extending to 7+16 or 7+64) — lengths up to 125 fit directly in these 7 bits. A length of 126 means "the real length is the next 16 bits"; a length of 127 means "the real length is the next 64 bits." A receiver always knows from these first bits alone how many more length bytes, if any, to read before the payload starts.
- **Masking key** (4 bytes, present only if MASK=1) — the key the payload was XORed against, one byte of key per four bytes of payload, repeating.
- **Payload data** — the message bytes (or fragment of them), masked if MASK was set.

The masking requirement is specific to client-to-server frames and exists for a reason that has nothing to do with confidentiality — masking a payload with a key sent in the clear, in the same frame, provides zero cryptographic protection, and the RFC says so directly. It exists because of cache-poisoning and request-smuggling attacks against intermediaries that sit between a browser and a server without understanding WebSocket framing. Before masking was mandatory, a malicious page could construct a WebSocket payload that, byte-for-byte, looked like a second HTTP request to a misbehaving proxy sharing the connection, smuggling a request the proxy would treat as coming from a trusted origin. Masking every client-sent frame with an unpredictable, per-frame key means an attacker can't control the literal bytes that hit the wire, which closes that class of attack against any intermediary that doesn't speak WebSocket and might otherwise reparse the frame as something else. Servers don't mask their frames because the corresponding attack runs browser-to-intermediary, not server-to-intermediary — a browser is the component with uncontrolled script running inside it that needs the key to be unpredictable.

{% include excalidraw.html file="03-frame-anatomy" alt="Byte-level diagram of the RFC 6455 WebSocket frame format: byte 0 holding FIN, RSV1-3, and a 4-bit opcode; byte 1 holding the MASK bit and a 7-bit payload length; an optional extended payload length field of 2 or 8 bytes; a 4-byte masking key present on client frames; and the payload data, annotated with a real captured client frame (0x81 0x93 plus a mask key) decoding to a handling-event JSON payload." caption="Figure 3.2 — Frame anatomy, decoded against a real captured frame carrying one handling event." %}

A receiver's unmasking step is one line of arithmetic per payload byte: XOR byte *i* of the payload with byte `i mod 4` of the four-byte mask key. The "On the wire" section below runs this exact computation against a frame captured off a real socket, not a worked example.

## Control frames and close codes

Three of the six opcodes exist to manage the connection itself rather than carry application data, and all three share one rule that applies from the start: control frames are never fragmented (FIN is always 1 on them) and carry at most 125 bytes of payload, so an implementation can always process one in a single read regardless of what data frames are mid-flight around it.

**Ping and pong** (`0x9` and `0xA`) are a liveness check. Either endpoint may send a ping at any time, with an optional application-chosen payload; the receiver must reply with a pong carrying the identical payload, as soon as practical, without waiting for any in-progress data frames to finish first. A ping/pong round trip tells a sender the connection's other end is still processing, not only that the TCP connection hasn't been torn down — a TCP socket can sit half-open for minutes after the peer process dies or a network path drops without either side noticing, since TCP's own keepalives are both optional and slow. Chapter 14 builds this into an actual heartbeat strategy for the handling-event feed: how often to ping, how long to wait for a pong before declaring the connection dead, and what "dead" should trigger on each stack.

**Close** (`0x8`) ends the connection, and it's the one control frame carrying structured payload data beyond a plain byte string: an optional 2-byte close code, followed by an optional UTF-8 reason string. Closing is a handshake in miniature — one side sends a close frame, the other side is expected to send its own close frame back (an echo of the code is fine, or its own code if it has something more specific to report), and only after that exchange does either side tear down the underlying TCP connection. A side that stops responding or drops the TCP connection without any close frame has performed an *abnormal closure*, which every implementation needs to handle as a real case, not a deviation to ignore — Chapter 13 covers abnormal closures as the dominant failure mode in production, far more common than a clean close frame exchange.

RFC 6455 reserves a range of close codes with specific meanings, and this site's examples use these rather than inventing ad hoc numbers:

| Code | Name | Meaning |
|---|---|---|
| 1000 | Normal Closure | The purpose this connection was opened for is complete. |
| 1001 | Going Away | A server is shutting down, or a client is navigating away from the page. |
| 1002 | Protocol Error | The peer sent a frame that violates RFC 6455 framing rules. |
| 1003 | Unsupported Data | A text-only endpoint received a binary frame, or vice versa. |
| 1006 | Abnormal Closure | *Reserved* — never sent on the wire; an implementation sets this internally when the connection dropped with no close frame at all. |
| 1008 | Policy Violation | A generic "that message violated an application rule" code, when none of the more specific codes fit. |
| 1009 | Message Too Big | The server refused a message past a configured size limit. |
| 1011 | Internal Error | The server hit an unexpected condition and can't continue. |
| 4000-4999 | Application-defined | Reserved by the RFC for private use between a specific client and server. |

That last row matters more than its one line suggests. The standard codes cover transport-level and generic-protocol conditions; they have nothing to say about *why* a handling-event feed closed a connection for an application-specific reason — a booking that doesn't exist, a subscription the caller isn't authorized to hold, a backpressure limit this feed enforces on a slow consumer. Chapter 13 defines this site's own 4000-series codes for exactly those cases, instead of overloading 1008 for every application-level rejection and leaving the client to parse a reason string to find out which rule it broke.

## Subprotocols and extensions

Two negotiation fields ride in the same handshake as the Upgrade itself, and they solve different problems that are easy to conflate on a first read.

**`Sec-WebSocket-Protocol`** is application-level negotiation: the client lists the message formats or application protocols it can speak, in preference order, as a comma-separated header value — something like `Sec-WebSocket-Protocol: handling-events.v1, handling-events.v0`. The server picks one it also supports and echoes back exactly that one value, unquoted, as its own `Sec-WebSocket-Protocol` response header. If the server supports none of the offered values, RFC 6455 requires it to fail the handshake rather than fall back to an undeclared default without telling the client — a client that asked for a specific protocol and got a connection with no protocol header back doesn't know what it's receiving. This site registers a versioned subprotocol token per the AsyncAPI contract Chapter 5 builds (`handling-events.v1` is the first one), so a client and server that disagree about message shape fail at connection time with a clear signal, instead of failing later when a field the client doesn't understand arrives inside an otherwise-successful connection.

**Extensions**, negotiated via `Sec-WebSocket-Extensions`, modify the framing itself rather than the application payload format. The one in wide production use is **permessage-deflate** (RFC 7692), which compresses each message's payload with DEFLATE before it's framed, using RSV1 to signal a compressed frame to a receiver that negotiated the extension. It earns real bandwidth savings on repetitive JSON payloads — a handling-event message re-sending the same field names (`"eventType"`, `"containerId"`, `"location"`) on every push compresses well — but it costs CPU per frame, memory proportional to connection count for per-connection compression state, and carries a known attack class against TLS-plus-compression (CRIME-style, trading a compression ratio side channel for secret recovery), so it needs an explicit decision rather than a default-on flag on a connection carrying anything sensitive. Chapter 20 measures its throughput effect on this site's own message shapes rather than taking the tradeoff on faith.

Both fields are negotiated once, during the handshake, exactly like `Sec-WebSocket-Version`. A connection's subprotocol and extension set don't change mid-connection — a client that wants a different protocol version opens a new connection and runs the handshake again.

## TLS, proxies, and wss

Everything above describes framing on top of a bare TCP connection, which is `ws://`. Production traffic runs `wss://` — WebSocket over TLS — for the same reason production HTTP traffic runs `https://`: without it, a handling-event payload, any bearer token used to authenticate the connection, and the Sec-WebSocket-Key dance itself all cross the network in plaintext, visible to anything positioned on the path. The TLS handshake happens first, exactly as it would for an HTTPS request to the same host, and the WebSocket upgrade request is the first HTTP request sent over that already-encrypted channel — there's no WebSocket-specific TLS behavior to learn beyond "upgrade happens after TLS, not instead of it." Browsers enforce a mixed-content rule here: a page loaded over `https://` is not permitted to open a `ws://` connection, only `wss://`; the browser blocks the connection attempt outright rather than downgrading it to plaintext, so a page served over TLS needs its socket endpoint served over TLS too.

Reaching the server at all depends on everything between the client and that server understanding, or at least not mangling, the Upgrade request. A plain HTTP/1.1 reverse proxy that doesn't know about WebSockets will typically treat `Connection: Upgrade` as a hop-by-hop header to strip, forward a connection-less proxied request, and never deliver the 101 back intact — the handshake fails outright, usually visible as the client receiving an ordinary `200` or `426` instead of `101`. Every major reverse proxy (nginx, Envoy, HAProxy) supports WebSocket proxying correctly, but requires it to be configured, not assumed: nginx needs explicit `proxy_set_header Upgrade $http_upgrade` and `proxy_set_header Connection "upgrade"` directives, because its default proxying behavior predates WebSockets. A load balancer in front of a fleet of server instances has a second concern once the handshake succeeds: a WebSocket connection is **sticky** by nature — every one of a connection's frames, for its entire lifetime, must reach the same backend instance that completed the handshake, because that instance alone holds the connection's in-memory state. Distributing by new-TCP-connection, the normal strategy for stateless HTTP, works here by default, since each WebSocket connection is exactly one TCP connection for its whole life; the failure mode shows up instead with connection-pooling layers that assume a single client-to-proxy connection can fan out across different backends per request, an assumption a WebSocket's single long-lived stream violates. Chapter 17 covers authentication and origin validation behind a public-facing proxy; Chapter 26 covers Kubernetes Ingress and Service configuration for this stickiness requirement when the handling-event feed runs on minikube.

A second TCP-level reality matters here, because it resurfaces at Chapter 12: a WebSocket connection has no backpressure signal above what the connection's own TCP send buffer already enforces. HTTP/2 (Chapter 6 of this site's gRPC sibling, for readers coming from that site) layers explicit per-stream flow-control windows on top of TCP; RFC 6455 defines no WebSocket-level equivalent. If a server writes handling-event frames faster than a slow client reads them, the only thing that eventually pushes back is the OS-level TCP send buffer filling up and the write call blocking or failing — there is no WebSocket frame that means "slow down." Living with that limit, rather than wishing it away, is the subject of Chapter 12.

## On the wire

Everything above is prose about RFC 6455. Here is a real handshake against a real socket.

A minimal Python server implementing only the handshake — no framework, raw sockets, computing `Sec-WebSocket-Accept` by hand — listening on `127.0.0.1:8765`:

```python
import socket, hashlib, base64

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def accept_value(client_key: str) -> str:
    digest = hashlib.sha1((client_key + GUID).encode()).digest()
    return base64.b64encode(digest).decode()
```

`curl` doesn't speak the WebSocket protocol, but the handshake itself is plain HTTP — `curl --include` can send the Upgrade request and show exactly what comes back, using the test vector RFC 6455 §1.3 publishes in the spec text itself (`Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==`, which decodes to the 16 bytes `the sample nonce`):

```bash
curl --include --http1.1 --max-time 2 \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  http://127.0.0.1:8765/handling-events
```

The server's response, captured off that real connection:

```text
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

`s3pPLMBiTxaQ9kYGzzhZRbK+xOo=` is the exact value RFC 6455 §1.3 documents for this key — proof the handshake logic above matches the spec, not only this chapter's description of it. `curl` then times out waiting for more, because its job stopped at reading one HTTP response; a `101` with no `Content-Length` and a connection that never closes isn't a request/response exchange `curl` knows how to continue, which is itself the clearest demonstration available that something has fundamentally changed about this connection.

A real client, after validating that same `Accept` value, sent one text frame carrying a handling-event payload. Captured raw off the socket:

{% raw %}
```text
81 93 8a a4 58 27 f1 86 3d 51 ef ca 2c 05 b0 86 19 75 d8 ed 0e 62 ce 86 25
```
{% endraw %}

Decoding it byte by byte, the same way a server implementation has to:

- `0x81` = `1000 0001` — FIN=1, RSV=0, opcode=`0x1` (text). One complete, unfragmented text frame.
- `0x93` = `1001 0011` — MASK=1, payload length = `0x13` = 19. Nineteen bytes fits the 7-bit length field directly, so there's no extended-length field to read.
- `8a a4 58 27` — the 4-byte masking key.
- The remaining 19 bytes are the masked payload. XORing byte *i* against mask-key byte `i mod 4` recovers:

{% raw %}
```text
{"event":"ARRIVED"}
```
{% endraw %}

Nineteen bytes in, nineteen characters out — a JSON handling-event notification, the exact shape Chapter 4 names formally and Chapter 5 puts under an AsyncAPI contract, carried here with no framework and no library, only the frame format this chapter describes applied by hand to real bytes off a real socket.

## Where this goes next

This chapter named the protocol; it said nothing about what rides inside the frames. Chapter 4 picks up the shipping/cargo domain this site shares with its REST and gRPC siblings and defines the handling-event vocabulary — the exact shape of the `{"event":"ARRIVED"}` payload this chapter decoded by hand — before Chapter 5 puts that vocabulary under an AsyncAPI 3 contract both stacks generate from. The pieces flagged along the way here get their own chapters rather than a paragraph each: Chapter 12 on backpressure past what TCP's send buffer alone provides, Chapter 13 on the 4000-series close codes this site defines for application-level rejections, Chapter 14 on turning ping/pong into an actual heartbeat policy, Chapter 17 on authenticating a connection running behind a public proxy, and Chapter 20 on measuring permessage-deflate against this site's real message shapes instead of assuming the tradeoff.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>This site's handling-event feed runs <code>wss://</code> only, never <code>ws://</code>, in every environment past a developer's own laptop against the Docker Compose lab — matching DRQ-007's runtime tiers, all three of which terminate TLS at the ingress. It negotiates the <code>handling-events.v1</code> subprotocol token via <code>Sec-WebSocket-Protocol</code> rather than leaving message-format agreement implicit, so a client built against a stale contract fails the handshake with a clear signal instead of connecting successfully and then choking on a field it doesn't recognize partway through a session. Close codes stay within RFC 6455's reserved ranges for transport-level conditions (1000, 1001, 1002, 1003, 1008, 1009, 1011) and move into this site's own 4000-series codes, defined in Chapter 13, for every handling-event-specific rejection — an unknown booking, an unauthorized subscription, a backpressure limit — rather than overloading 1008 for all of them and pushing callers to parse a reason string to find out which rule fired. permessage-deflate is left negotiable but off by default pending Chapter 20's measurement against this site's own payload shapes, rather than assumed free on the strength of its general reputation for shrinking repetitive JSON.</p></div>
