---
title: "Choosing the Right Tool"
order: 2
part: "Foundations"
description: "WebSockets, Server-Sent Events, long-polling, webhooks and gRPC streaming compared on seven dimensions, with an ordered decision rule."
duration: "15 min read"
---

## Learning objectives

By the end of this chapter you can:

- Compare WebSockets, Server-Sent Events, long-polling, webhooks and gRPC server-streaming on direction, duplex, ordering, backpressure, proxy behavior, browser support and reconnection.
- Pick a transport by asking whether the interaction needs live updates, who has to send and who is receiving.
- Recognize when a WebSocket is the wrong answer.
- Trace the handling-event feed from "does it need live updates" to its transport.

## Why this matters

Needing push does not mean opening a WebSocket. Five transports solve some version of the problem, and they disagree on who may send, how long a connection lives, whether order holds and who retries.

Three interactions show the spread:

- A booking confirmation page opens a socket on load and holds it for the life of the tab, though the booking changes status twice a day at most.
- A customs broker wants to know the moment a container clears, but its system exposes no public endpoint and can't hold a connection open. It polls a REST endpoint every thirty seconds.
- A warehouse dashboard shows dozens of handling events a minute for every active shipment on the yard floor. It only reads.

A site about WebSockets is biased toward answering all three the same way. Each one needs a different answer.

## The contenders

A **WebSocket** is one TCP connection that starts as an HTTP request, upgrades in place, and then carries framed messages in both directions until it closes. The booking page can ask to watch a different booking while a handling-event frame for the previous one is still arriving.

**Server-Sent Events** (SSE) push data one way over an HTTP response whose body never ends. The browser's `EventSource` parses the text framing, reconnects on its own and sends `Last-Event-ID` so the server can resume. The client has no channel back beyond the original request.

**Long-polling** holds a request open until the server has something to say or a timeout expires, and the client sends the next request the moment a response arrives. Every update costs a full request cycle, often on a fresh connection. The wire format is plain HTTP, so it survives paths that reject anything stranger.

A **webhook** inverts who initiates: the event source calls the receiver's HTTPS endpoint when something happens, and no connection is held between deliveries. It fits a partner system with a public endpoint. It does not fit the customs broker.

**gRPC server-streaming** is a typed stream over HTTP/2 between two services generated from the same Protobuf contract. An internal analytics service consuming handling events fits it: neither end is a browser, and HTTP/2 flow control comes with it.

## Dimensions that matter

- **Direction.** A WebSocket lets either side send at any time. SSE allows the server only. Long-polling always has the client ask first. A webhook reverses the roles. gRPC follows the RPC declared in the `.proto`.
- **Duplex.** Only a WebSocket (and bidirectional gRPC) carries both directions at once. Long-polling and webhooks are request/response pairs. SSE has no client half to interleave.
- **Ordering.** A WebSocket and SSE are one ordered stream, so delivery is FIFO. Long-polling preserves order if the client waits for each response. Webhooks don't: a sender that retries one delivery and not another can reorder them, so a receiver that cares carries a sequence number or `occurred_at` and reorders itself.
- **Backpressure.** A WebSocket has only TCP flow control, so the server watches its own send queue (or the browser its `bufferedAmount`) and decides whether to drop, buffer or disconnect a slow client. SSE has the same gap with less visibility, since `EventSource` exposes no queue state. gRPC is the one transport with backpressure in the protocol, through HTTP/2 flow-control windows. Long-polling and webhooks are bounded per call.
- **Proxies and firewalls.** The `Upgrade` handshake is what breaks: proxies and older load balancers built for request/response HTTP strip `Connection: Upgrade` or refuse the 101. SSE is an ordinary long HTTP response that most proxies relay. Long-polling and webhooks are plain HTTP. gRPC needs HTTP/2 end to end, which is easy inside a cluster you run and a constraint beyond it.
- **Browsers.** `WebSocket` and `EventSource` are native. Long-polling is a hand-written `fetch` loop. A browser can't speak gRPC streaming directly and needs grpc-web or a proxy. A webhook receiver is a server.
- **Reconnection.** SSE reconnects and resumes by specification. A WebSocket has no equivalent: every reconnect, resume cursor and backoff policy is application code. Long-polling heals by construction. A webhook sender owns retries with backoff, and the receiver needs idempotency.

{% include excalidraw.html file="02-duplex-comparison" alt="Five horizontal bands, one per transport, showing who may send and when: WebSocket is bidirectional, SSE is server to client only, long-polling alternates a held request and a response, a webhook reverses the roles, and gRPC server-streaming opens a stream and pushes repeatedly." caption="Figure 2.1: The same push problem under five rules about who may send and when." %}

| Dimension | WebSocket | SSE | Long-polling | Webhook | gRPC streaming |
|---|---|---|---|---|---|
| Direction | Either side, anytime | Server to client only | Client-initiated cycles | Sender-initiated, roles reversed | Per the `.proto` contract |
| Duplex | Full | Half, server writes only | Half, request/response | Half, one-shot calls | Full on bidi, half on server-streaming |
| Ordering | FIFO per connection | FIFO per connection | Per request, client-serialized | Not guaranteed across deliveries | FIFO per HTTP/2 stream |
| Backpressure | App-managed, no protocol support | App-managed, less visibility than WS | Not applicable, bounded per call | Not applicable, bounded per call | Built in via HTTP/2 flow control |
| Proxy/firewall | Needs `Upgrade` support | Plain HTTP, broadly compatible | Plain HTTP, most compatible | Plain HTTP, most compatible | Needs HTTP/2 end to end |
| Browser support | Native (`WebSocket`) | Native (`EventSource`) | Hand-rolled fetch loop | Not a browser concept | Needs grpc-web or a proxy |
| Reconnection | Application writes it | Built in (`Last-Event-ID`) | Self-healing by construction | Sender retries with backoff | Application or library writes it |

## A decision framework

Ask in order:

1. **Does the interaction need live updates?** A page that reloads on a click, or a report generated daily, needs none of the five. Plain request/response avoids the connection state.
2. **Who sends?** If the client must send mid-stream, to switch which booking it watches, acknowledge a message or run its own heartbeat, a WebSocket is the only native duplex option.
3. **If only the server sends, who receives?** For a browser tab on a path that keeps streaming responses open, SSE gives native reconnection and proxy compatibility for less work than a socket. If the path buffers or truncates long-lived responses, as some corporate egress proxies do, long-polling degrades to plain request cycles.
4. **If another service receives, can it expose an endpoint?** If yes, use a webhook, which puts delivery on the sender's retry policy. If not, polling on a schedule is what's left, and it's a valid answer. If both ends are services you operate under one contract, use gRPC server-streaming.

{% include excalidraw.html file="02-transport-decision" alt="A decision tree. Live updates not needed leads to plain request/response. Both sides sending leads to WebSocket. Server-only push to a browser leads to SSE or long-polling. Service receivers lead to a webhook or gRPC server-streaming." caption="Figure 2.2: The decision questions as a tree, ending in one of five transports or none." %}

## When a socket is the wrong answer

A socket costs a file descriptor and server-side state for as long as the tab is open, whether or not anything arrives. Multiplied by every idle tab left open overnight, that is memory and connection-table pressure paid for subscriptions that rarely fire. It also brings an `Upgrade` handshake, no authentication beyond what the application puts in that handshake or the first message, and a load balancer that must keep a client on one backend for the connection's life.

If the client only consumes and a latency of a few seconds is acceptable, a WebSocket is the expensive option on this list.

## A worked decision: the handling-event feed

- **Live updates?** Yes. A customer watching a stale "in transit" status after the container cleared customs is the failure the feed exists to prevent.
- **Who sends?** Both. The page tells the server which booking to watch on connect, and sends a new subscribe to switch bookings without reopening. That alone rules out SSE, whose `EventSource` has no channel back.
- **Who receives?** A browser tab the team controls, so a webhook is out, and the sub-second latency rules out long-polling's per-update cost. gRPC streaming is out because one end is a browser.

The warehouse dashboard answers differently: a browser tab, server push only, no per-booking subscription to renegotiate, and a data-center path that keeps streaming responses open. That is SSE. The customs broker answers "another service" and "no reachable endpoint", so it polls.

## On the wire

An SSE response is a `200 OK` whose body the server keeps writing:

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

event: handling_event
id: 48219
data: {"booking_id":"BKG-88213","type":"HOLD","location":"USLAX","occurred_at":"2026-10-18T14:02:11Z"}

event: handling_event
id: 48220
data: {"booking_id":"BKG-88213","type":"LOAD","location":"USLAX","occurred_at":"2026-10-18T14:05:47Z"}

```

Each event is plain text ending in a blank line. The `id` is what the browser echoes as `Last-Event-ID` on reconnect, and the client writes nothing after the original GET.

A WebSocket starts as HTTP and then stops being HTTP:

```http
GET /ws/bookings/BKG-88213/handling-events HTTP/1.1
Host: api.example.com
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==
Sec-WebSocket-Version: 13
```

```http
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=
```

After the `101`, both sides exchange frames and the frame header (two bytes at minimum) replaces HTTP headers. The page's first frame is one SSE has no channel for:

```json
{"action":"subscribe","booking_id":"BKG-88213"}
```

The server answers on the same connection with the event SSE would have sent as text:

```json
{"type":"handling_event","booking_id":"BKG-88213","event":"HOLD","location":"USLAX","occurred_at":"2026-10-18T14:02:11Z"}
```

> **Decision**
>
> The handling-event feed is a WebSocket. It needs live updates, so plain request/response is out. The client must send a subscribe and a resubscribe, so SSE's one-way channel is out. The receiver is a browser tab, so a webhook and gRPC streaming are out, and the sub-second latency rules out long-polling. If the client only consumed, SSE would win.

> **🤖 Explore with your agent**
>
> "Open `ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events` from `examples/part3-handling-events` and decide from `contracts/asyncapi.yaml` whether this channel needs a WebSocket. The operation is `action: receive` and the client sends nothing. Apply the rule: if the client only consumes and a few seconds of latency is acceptable, a WebSocket is the expensive option. Say what you would pick for the browser dashboard and what would change if the page had to send a subscribe message."
>
> Check: the reply should note that the channel is server-to-client only, and name the exact requirement (a client-to-server message) that would justify a socket over SSE.

## Build, run, observe

Start both stacks and read the first pushed frame (Docker Engine, from the repo root):

```bash
cd examples/part3-handling-events
docker compose up --build -d
source ../_lib/lib.sh
ws_first_frame "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
```

Quarkus listens on 8080 and Python on 8081. The first frame is the `RECEIVE` event, pushed without the client sending anything. The handling-events channel names the booking in its path and declares only a server-to-client operation, so on its own it is the one-way shape that makes SSE a candidate; a subscribe or resubscribe message from the page is what tips it to a socket. Run `./verify.sh` for the full check, which prints `PASS:` when both stacks agree. Tear down with `docker compose down -v`.

- Point `ws_first_frame` at port 8081: the same event arrives from the Python stack.

## For deeper coverage

- Dynowski, L. & Dulak, M., *Learning API Styles* (O'Reilly, 2025): comparing interaction styles on the dimensions used here.
- Gough, J., Bryant, D. & Auburn, M., *Mastering API Architecture* (O'Reilly, 2022): architectural trade-offs behind choosing a style per interaction.
- *Cloud Native Design Patterns*, "Communications" and "Protocols in Depth" chapters: the broader transport comparison.
- [RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455): the WebSocket protocol.
- [WHATWG: Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html): `EventSource`, automatic reconnection and `Last-Event-ID`.
