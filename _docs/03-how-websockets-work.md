---
title: "How WebSockets Work"
order: 3
part: "Foundations"
description: "The HTTP upgrade handshake, frame layout, masking, close codes, subprotocols and extensions under RFC 6455."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Walk the HTTP `Upgrade` handshake, including how `Sec-WebSocket-Accept` derives from `Sec-WebSocket-Key` and a fixed GUID.
- Decode a frame's FIN, opcode, MASK and payload-length fields, and say why client frames are masked and server frames are not.
- Tell a clean close (opcode `0x8`, codes 1000 to 1011) from an abnormal closure (1006), and know the 4000 range is reserved for application codes.
- Say what `Sec-WebSocket-Protocol` and `Sec-WebSocket-Extensions` each negotiate, and what permessage-deflate costs.
- Explain why production needs `wss://` and a proxy that understands `Upgrade`, and why a WebSocket has no backpressure signal beyond TCP.

## Why this matters

Everything built later rests on three things: a handshake that runs once, a frame format that every later byte belongs to, and control frames that keep a connection alive or end it. The surrounding stack (TLS, proxies, load balancers) has opinions about a connection that refuses to close, and most "the socket won't connect" failures are those opinions.

## The upgrade handshake

A WebSocket starts as an ordinary HTTP/1.1 request on an ordinary TCP connection, with no separate port or listener. The client adds:

- `Upgrade: websocket`: stop speaking HTTP on this connection after this response.
- `Connection: Upgrade`: required alongside it, because `Upgrade` alone is hop-by-hop and a proxy may drop it.
- `Sec-WebSocket-Version: 13`: the only version RFC 6455 defines. A server that doesn't support it answers `426 Upgrade Required` and lists the versions it does.
- `Sec-WebSocket-Key`: a random base64-encoded 16-byte value, fresh per connection.

A server that accepts replies `101 Switching Protocols` with `Upgrade: websocket`, `Connection: Upgrade` and `Sec-WebSocket-Accept`. That value is derived, not echoed: the server concatenates the client's key with the fixed GUID `258EAFA5-E914-47DA-95CA-C5AB0DC85B11`, takes the SHA-1 digest and base64-encodes it. The client repeats the computation and compares.

This is not authentication, since the GUID is public. It proves the other end ran RFC 6455's handshake logic, and is not a cache or misconfigured intermediary replaying a request it didn't understand. After the client validates it, the connection carries no more HTTP. Every byte is a WebSocket frame, in both directions, until one side closes. The handshake runs once, so its cost is amortized over every frame that follows.

{% include excalidraw.html file="03-upgrade-handshake" alt="Sequence diagram: the client sends an HTTP GET with Upgrade, Connection and Sec-WebSocket-Key headers, the server derives Sec-WebSocket-Accept from the key and a fixed GUID and answers 101 Switching Protocols, and both sides then exchange frames on the same TCP connection." caption="Figure 3.1: One HTTP request becomes a long-lived socket. The 101 response is the whole handshake." %}

## Frame anatomy

An application sends messages, and the wire carries frames. A message can span several frames. The first two bytes of a frame hold most of what a receiver needs:

- **FIN** (1 bit): set on the last frame of a message. A fragmented message sets FIN=0 on every frame but the last, which lets a sender start before the whole message is serialized and lets control frames interleave. Most messages here fit one frame.
- **RSV1-3** (3 bits): reserved for negotiated extensions. permessage-deflate uses RSV1.
- **Opcode** (4 bits): `0x0` continuation, `0x1` text, `0x2` binary, `0x8` close, `0x9` ping, `0xA` pong.
- **MASK** (1 bit): the payload is XOR-masked. Every client frame sets it and no server frame does.
- **Payload length** (7 bits, extending to 7+16 or 7+64): up to 125 fits directly. 126 means the real length is the next 16 bits, and 127 means the next 64 bits.
- **Masking key** (4 bytes, only when MASK=1) and **payload data**.

Masking is not confidentiality: the key travels in the same frame, and the RFC says so. It defends intermediaries. Before masking was mandatory, a malicious page could build a payload that, byte for byte, looked like a second HTTP request to a proxy that didn't understand WebSocket framing, and smuggle a request the proxy would attribute to a trusted origin. An unpredictable per-frame key means the attacker can't control the literal bytes on the wire. The attack runs from the browser, where uncontrolled script executes, so server frames go unmasked.

{% include excalidraw.html file="03-frame-anatomy" alt="Byte-level diagram of the RFC 6455 frame: byte 0 holds FIN, RSV1-3 and a 4-bit opcode, byte 1 holds the MASK bit and a 7-bit payload length, then an optional extended length, a 4-byte masking key on client frames, and the payload. A captured client frame is annotated beside it." caption="Figure 3.2: Frame anatomy, decoded against a captured frame carrying one handling event." %}

Unmasking is one XOR per byte: payload byte *i* against mask-key byte `i mod 4`.

## Control frames and close codes

Ping, pong and close are control frames. They are never fragmented and carry at most 125 bytes, so an implementation can handle one in a single read while data frames are mid-flight.

**Ping and pong** (`0x9`, `0xA`) check liveness. Either side may ping, and the receiver must answer promptly with a pong carrying the same payload. A round trip shows the peer is still processing, not only that TCP is up: a TCP socket can sit half-open for minutes after the peer dies, since TCP keepalives are optional and slow.

**Close** (`0x8`) carries an optional 2-byte code and a UTF-8 reason. It is a miniature handshake: one side sends close, the other answers with its own, and only then does either tear down TCP. A peer that drops TCP with no close frame has caused an *abnormal closure*, which every implementation must handle as an ordinary case: in production it is far more common than a clean close exchange.

| Code | Name | Meaning |
|---|---|---|
| 1000 | Normal Closure | The purpose of the connection is complete. |
| 1001 | Going Away | The server is shutting down, or the client is navigating away. |
| 1002 | Protocol Error | The peer sent a frame that breaks RFC 6455 framing rules. |
| 1003 | Unsupported Data | A text-only endpoint received binary, or the reverse. |
| 1006 | Abnormal Closure | Reserved. Never sent on the wire. An implementation reports it when the connection dropped with no close frame. |
| 1008 | Policy Violation | A generic application rule, when nothing more specific fits. |
| 1009 | Message Too Big | A message exceeded the configured size limit. |
| 1011 | Internal Error | The server hit an unexpected condition. |
| 4000-4999 | Application-defined | Reserved for private use between a client and server. |

The standard codes say nothing about why a handling-event feed closed a connection: an unknown booking, an unauthorized subscription, a slow consumer. The 4000 range exists for those, so a client doesn't parse a reason string to learn which rule it broke. 1008 should not carry every application rejection.

## Subprotocols and extensions

Two fields in the same handshake solve different problems.

**`Sec-WebSocket-Protocol`** negotiates the application protocol. The client lists what it speaks in preference order (`handling-events.v1, handling-events.v0`), and the server echoes exactly one value it supports, unquoted, in its own `Sec-WebSocket-Protocol` header. If it supports none, it fails the handshake instead of silently choosing a default. A client and server that disagree about message shape then fail at connect time, not when an unknown field arrives mid-session.

**`Sec-WebSocket-Extensions`** modifies the framing. The one in wide use is **permessage-deflate** (RFC 7692), which compresses each message with DEFLATE and sets RSV1. It saves bandwidth on repetitive JSON, since field names repeat in every handling event. It costs CPU per frame and memory per connection for compression state, and compression over TLS has a known side-channel attack class (CRIME-style). Enable it as an explicit decision, not a default, on anything sensitive.

Both are negotiated once. A client that wants a different protocol version opens a new connection.

## TLS, proxies and wss

`ws://` is framing on bare TCP. Production runs `wss://`, or the payloads and any bearer token cross the network in plaintext. TLS completes first, and the upgrade is the first HTTP request on the encrypted channel. A page loaded over `https://` can't open a `ws://` connection: the browser blocks it rather than downgrading.

Every hop must pass the `Upgrade` request through. A reverse proxy that doesn't know WebSockets treats `Connection: Upgrade` as hop-by-hop, strips it and never delivers the 101, so the client sees an ordinary `200` or `426`. nginx, Envoy and HAProxy all support WebSocket proxying, but nginx needs `proxy_set_header Upgrade $http_upgrade` and `proxy_set_header Connection "upgrade"` because its defaults predate the protocol.

A connection is also sticky by nature. Every frame for its lifetime must reach the instance that completed the handshake, because that instance holds the connection's state. Balancing by new TCP connection already does this. The failure shows up in layers that assume one client-to-proxy connection can fan out to different backends per request.

RFC 6455 defines no WebSocket-level backpressure. HTTP/2 adds per-stream flow-control windows, and a WebSocket has only the TCP send buffer. A server that writes faster than a client reads gets pushed back only when that buffer fills and the write blocks or fails. No frame means "slow down".

## On the wire

`Sec-WebSocket-Accept` is a few lines of Python:

```python
import socket, hashlib, base64

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def accept_value(client_key: str) -> str:
    digest = hashlib.sha1((client_key + GUID).encode()).digest()
    return base64.b64encode(digest).decode()
```

`curl` can't speak the protocol, but the handshake is plain HTTP, so `curl --include` shows what comes back. This uses the sample key from RFC 6455 section 1.3, which decodes to the 16 bytes "the sample nonce":

```bash
curl --include --http1.1 --max-time 2 \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  http://127.0.0.1:8765/handling-events
```

A compliant server answers:

```text
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

`s3pPLMBiTxaQ9kYGzzhZRbK+xOo=` is the value the RFC documents for that key. `curl` then times out, because a `101` with no `Content-Length` and a connection that never closes isn't an exchange it knows how to continue.

A client that validated that `Accept` sent one text frame. Captured raw:

{% raw %}
```text
81 93 8a a4 58 27 f1 86 3d 51 ef ca 2c 05 b0 86 19 75 d8 ed 0e 62 ce 86 25
```
{% endraw %}

Decoded the way a server must:

- `0x81` is `1000 0001`: FIN=1, RSV=0, opcode `0x1` (text), one complete frame.
- `0x93` is `1001 0011`: MASK=1, payload length `0x13` = 19. That fits the 7-bit field, so there is no extended length.
- `8a a4 58 27` is the masking key.
- The remaining 19 bytes XOR against the key (byte *i* against key byte `i mod 4`) to give:

{% raw %}
```text
{"event":"ARRIVED"}
```
{% endraw %}

> **Decision**
>
> Run `wss://` in every environment past a developer's laptop. Negotiate the `handling-events.v1` subprotocol so a client built against a stale contract fails at the handshake. Use the RFC's standard close codes (1000, 1001, 1002, 1003, 1008, 1009, 1011) for transport conditions and the 4000 range for handling-event rejections, instead of overloading 1008. Leave permessage-deflate negotiable but off until its cost is measured against real payloads.

> **🤖 Explore with your agent**
>
> "Using the Part 3 example in `examples/part3-handling-events`, send the RFC 6455 test key `dGhlIHNhbXBsZSBub25jZQ==` in an upgrade request to `http://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events` with `curl --include --http1.1 --max-time 2`, and confirm the status line and the `Sec-WebSocket-Accept` value. Then explain which close code the server should send for an unknown booking, applying the rule that transport faults use 1000 to 1011 and application rejections use 4000 to 4999."
>
> Check: the response is `101 Switching Protocols` with `Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`, and the agent names a 4000-range code, not 1008, for the unknown booking.

## Build, run, observe

The handshake runs against the Part 3 example. From the repo root:

```bash
cd examples/part3-handling-events
docker compose up --build -d
curl --include --http1.1 --max-time 2 \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  -H "Sec-WebSocket-Version: 13" \
  http://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events
docker compose down -v
```

The status line is `101 Switching Protocols` and `Sec-WebSocket-Accept` matches the RFC value. Quarkus is on 8080 and Python on 8081, so repeat against 8081 for the other stack. `./verify.sh` runs the full check and prints `PASS:` when both stacks agree.

## For deeper coverage

- Dynowski, L. & Dulak, M., *Learning API Styles* (O'Reilly, 2025): where a framed, full-duplex protocol sits among API styles.
- *Cloud Native Design Patterns*, "Protocols in Depth" and "WebSockets at Scale" chapters: the protocol comparison and the scaling concerns (stickiness, backpressure, fan-out).
- [RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455): the handshake, frame format, masking, opcodes and close codes.
- [RFC 7692](https://datatracker.ietf.org/doc/html/rfc7692): permessage-deflate.
- [MDN: WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket): the browser interface over this wire protocol.
