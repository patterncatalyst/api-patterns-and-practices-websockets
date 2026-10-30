---
title: "Choosing the Right Tool"
order: 2
part: "Foundations"
description: "WebSockets vs Server-Sent Events vs long-polling vs webhooks, a decision table, and when each one wins."
duration: "21 min read"
---

## Learning objectives

By the end of this chapter you can:

- Compare WebSockets, Server-Sent Events, long-polling, webhooks, and gRPC server-streaming across direction, duplex, ordering, backpressure, proxy/firewall behavior, browser support, and reconnection.
- Apply the decision framework's ordered questions (does it need live updates, who has to send, who's receiving) to pick a transport for a given interaction.
- Diagnose when a WebSocket is the wrong answer, even on a site built around WebSockets.
- Trace the handling-event feed's worked decision end to end, from "does it need live updates" to the final transport choice.

## Why this matters

Push already made its case over pull in general; it said nothing about which push mechanism to reach for. This chapter builds the decision: five transports solve some version of the same problem, they disagree on direction, duplex, ordering, backpressure, and reconnection, and the one new idea is that "needs push" doesn't resolve to "open a WebSocket" by default, even on a site about WebSockets.

The booking confirmation page opens a WebSocket the moment it loads and keeps the connection open for the life of the tab, even though the booking it watches changes status twice a day at most. A customs broker's integration wants to know the instant a container clears, but the broker's system exposes no public endpoint and can't hold a connection open from its side either: polling a REST endpoint every thirty seconds is the only option it has, and it burns a request on a status that hasn't moved in hours. A warehouse dashboard needs a feed of handling events for every active shipment on the yard floor: dozens of updates a minute, one direction only, nothing the dashboard ever needs to send back. Three interactions, three different shapes, and a site about WebSockets has a built-in bias toward answering all three the same way.

That bias is the wrong starting point. Request/response already fell short once a client is watching something change rather than asking a question once; this chapter argues that "falls short" doesn't resolve to "open a WebSocket" by default. Five transports solve some version of the push problem (WebSockets, Server-Sent Events (SSE), HTTP long-polling, webhooks, and gRPC server-streaming) and they disagree on direction, connection lifetime, ordering, and who is allowed to initiate a message. Naming those disagreements here means every later chapter that reaches for a socket can say why the other four lost, instead of treating the choice as already settled by the table of contents. The protocol itself comes next, once this chapter rules it in.

## The contenders

A **WebSocket** is a single TCP connection that starts as an HTTP request, upgrades in place, and from that point carries framed messages in both directions for as long as the connection stays open. Neither side waits for the other to finish speaking: the booking confirmation page can send a message asking to watch a different booking while a handling-event frame from the previous one is still arriving. That's the capability this site is built around, and it's expensive exactly where the other four transports are cheap.

**Server-Sent Events** push data one way, server to client, over a plain HTTP response whose body never ends. The browser's built-in `EventSource` opens the connection, parses a simple text framing out of the response as it streams, and reconnects on its own if the connection drops. There's no client-to-server channel beyond the original request: a dashboard that only displays handling events never needs one.

**Long-polling** fakes a push by holding a request open: the client sends a normal HTTP request, the server waits to respond until it has something to say or a timeout expires, and the client immediately sends the next request the moment the response arrives. Every update costs a full request/response cycle and a fresh connection setup, but the wire format is nothing more exotic than HTTP, which is why it survives paths that reject anything stranger.

A **webhook** inverts who initiates. The event source calls the receiver's own HTTP endpoint the moment something happens, and the call is done: no connection held between deliveries. A partner's booking system that exposes a public HTTPS endpoint and wants to know the moment a shipment clears customs is the webhook case exactly, the opposite posture from the broker in the opening paragraph, who can neither host an endpoint nor hold a connection open and is left polling as the fallback of last resort.

**gRPC server-streaming** is a stream over HTTP/2 between two services, typically two your own organization runs, each generated from the same Protobuf contract. The internal analytics service aggregating handling events across the fleet talks to the event source this way, not over a WebSocket, because neither end is a browser, both already speak Protobuf, and the call gets typed messages and HTTP/2 flow control without anyone writing either by hand. The gRPC sibling site covers this shape from the other direction; this site only needs to know it exists and when it beats a raw socket for service-to-service traffic.

## Dimensions that matter

**Direction** asks who is allowed to originate a message. A WebSocket allows either side, at any time, for the life of the connection. SSE allows the server only: the client's one and only "send" is the initial GET. Long-polling always has the client ask first. A webhook flips the usual client/server relationship entirely: the party that would normally be called a "server" is the one dialing out. gRPC server-streaming follows whatever the `.proto` contract declares for that RPC: one direction for server-streaming, both for bidirectional streaming.

**Duplex** is a sharper version of the same question: can both directions carry traffic *at once*, or does one have to finish before the other starts? A WebSocket is full-duplex: nothing in the protocol makes one side wait for the other. Long-polling and webhooks are strictly half-duplex by construction: a request/response pair, then nothing, then another pair. SSE sits at one extreme of half-duplex, since the server-to-client half never stops but there's no client-to-server half to interleave with it at all.

**Ordering** matters once more than one update is in flight. A WebSocket guarantees FIFO delivery within a connection, because it's one ordered TCP stream wearing a framing layer. SSE gets the same guarantee for the same reason: one HTTP response, read in order. Long-polling preserves order as long as the client waits for each response before issuing the next request, which it normally does. Webhooks are the outlier: two deliveries for the same booking can arrive out of order if the sender retries one and not the other, so a receiver that cares has to carry its own sequence number or `occurred_at` timestamp and reorder on its own side: a correctness cost none of the other four impose by default.

**Backpressure** is what happens when a receiver can't keep up. Raw WebSockets give the application nothing here beyond TCP's own flow control; a server has to watch its own send queue (or the browser's `bufferedAmount`) and decide whether to drop, buffer, or disconnect a slow client: the gap closed for both stacks later, under backpressure and flow control. SSE has the same gap and less visibility into it, since `EventSource` exposes no send-queue state to application code. gRPC server-streaming is the one transport here with backpressure built into the wire protocol: HTTP/2's flow-control windows throttle the sender automatically when the receiver stops reading, one more reason a high-volume service-to-service feed reaches for gRPC streaming over a hand-rolled WebSocket. Long-polling and webhooks never hit this problem, because neither holds a channel open that the server has to keep pushing into: each delivery is its own bounded request.

**Proxy and firewall behavior** decides whether a transport survives a network path neither party controls. A WebSocket's opening `Upgrade` handshake is what breaks: corporate proxies, older load balancers, and anything built strictly for request/response HTTP will strip the `Connection: Upgrade` header or refuse the 101 response outright. SSE rides on an ordinary HTTP response, chunked or left open, which nearly every proxy already knows how to relay, making it the safer default behind network paths nobody has audited. Long-polling and webhooks are plain HTTP request/response, the most proxy-compatible shape there is. gRPC server-streaming needs HTTP/2 end to end: a non-issue inside a cluster you run, a real constraint the moment the path crosses infrastructure you don't.

**Browser support** separates what ships natively from what has to be built. `new WebSocket(url)` and `new EventSource(url)` are both plain browser APIs, no library required. A long-polling client is hand-written `fetch` code in a loop. gRPC streaming has no native browser transport: a browser can't speak HTTP/2 trailers-based gRPC directly, so anything browser-facing needs grpc-web or a proxy, itself an argument against putting gRPC streaming in front of a browser client. Webhooks aren't a browser concept at all; the "client" receiving one is a server.

**Reconnection** is the difference between a transport that heals itself and one that makes the application write the healing logic. `EventSource` reconnects automatically and sends a `Last-Event-ID` header the server can use to resume from where it left off: that behavior is in the spec, not something either stack has to implement. A WebSocket has no equivalent: every reconnect, every resume-from-a-cursor, every backoff policy is something the application writes, which is exactly what gets built for both stacks on the client side, later in the book. Long-polling heals itself by construction, since every cycle is a brand new request regardless of what happened to the last one. Webhooks push the reconnection problem onto the sender: a failed delivery has to be retried with its own backoff and an idempotency story on the receiving end, which is why webhook providers document a delivery and retry policy as carefully as they document the payload shape.

{% include excalidraw.html file="02-duplex-comparison" alt="Five horizontal bands, one per transport, showing who may send and when: WebSocket is bidirectional between browser and server; SSE is server-to-client only; long-polling alternates a held request and a response; webhook reverses the roles, event source calling your endpoint; gRPC server-streaming opens a stream and pushes repeatedly." caption="Figure 2.1: the same push problem, five different rules about who may send and when." %}

The dimensions above collapse into a single table worth keeping next to the decision framework that follows.

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

Running an interaction through the dimensions above, in order, resolves to one of the five transports, or to the sixth answer: nothing here is needed and plain request/response on demand is the right tool. Start with whether the interaction needs live updates at all. A page that reloads when the user clicks refresh, or a report generated once a day, never gets further than this question; forcing it onto any of the five transports below adds connection state for an update pattern that was never going to use it.

If live updates are needed, the next question is who has to send: one side only, or both. A booking page that only displays handling events as they arrive doesn't need to send anything after the initial subscribe: most of its lifetime is read-only from the client's point of view. But the moment the interaction needs the client to send something mid-stream, whether that's switching which booking it's watching, acknowledging a message, or sending a heartbeat the application controls itself rather than relying on protocol-level pings, duplex stops being optional and a WebSocket is the only one of the five that provides it natively.

When the server is the only side that ever sends, the branch depends on who's receiving. A browser tab you control is the straightforward case: check whether the network path between the two of you reliably keeps a streaming HTTP response open, and if it does, SSE gives you native reconnection and broad proxy compatibility for less implementation effort than a socket. If that same network path is known to buffer or truncate long-lived responses (some corporate egress proxies do exactly this), long-polling is the fallback that degrades to plain request/response cycles rather than failing outright.

When the receiver isn't a browser tab at all but another service, the question becomes whether that receiver can expose a reachable endpoint of its own. If it can, a webhook moves the delivery problem onto the sender's retry policy and keeps the receiver from holding anything open. If it can't, as with the customs broker case from the opening paragraph (no public endpoint and no held connection), polling on a schedule is what's left, a real answer rather than a failure state. And when both ends are services you operate, sharing a contract, gRPC server-streaming gets typed messages and real backpressure that a raw WebSocket or an SSE feed would otherwise approximate by hand.

{% include excalidraw.html file="02-transport-decision" alt="A decision tree: need live updates at all leads to plain request/response if not; who needs to send routes to WebSocket if both sides push; server-only push routes through browser-tab and streaming-friendly-path checks to SSE or long-polling; another-service receivers route through an endpoint-reachability check to webhook or gRPC server-streaming." caption="Figure 2.2: the same five questions, as a tree, resolving to one of five transports or to no transport at all." %}

## When a socket is the wrong answer

A WebSocket held open for a connection that sends one update a month costs a file descriptor and server-side connection state for the entire time that tab is open, whether or not anything ever arrives on it. Multiply that by every idle tab a customer leaves open overnight and the cost stops being theoretical: it's memory and connection-table pressure paid for subscriptions that rarely fire, the exact problem that surfaces later when fan-out reaches real scale. Reaching for a socket because "we want push" when the underlying data changes a handful of times a day is paying full duplex, continuously-open, application-managed-reconnection costs for an interaction that never needed any of the three.

A socket also carries its own attack surface: the `Upgrade` handshake, no built-in authentication beyond whatever the application puts into that handshake or the first message after it, and a load balancer that has to pin a client to one backend for the connection's life rather than routing each request independently: real costs covered in depth later, under security, none of them worth paying for an interaction that doesn't need low-latency duplex messaging held open continuously. This question comes back directly near the end of the book, with the fuller case built once later chapters have shown what a WebSocket costs to implement correctly; the short version belongs here too: if the client only consumes, and a latency of a few seconds is acceptable, a WebSocket is the expensive option on this list, not the obvious one.

## A worked decision: the handling-event feed

The booking confirmation page's handling-event feed is the example this site returns to, so running it through the framework by name grounds the abstract questions above before moving on. Does it need live updates at all? Yes: a customer staring at a stale "in transit" status while a container has already cleared customs is the exact failure the real-time problem opened with. Who needs to send: here the answer is both, not the server alone, because the page has to tell the backend which booking to watch the moment it connects, and because switching to a different booking without reopening a connection means sending a new subscribe message mid-stream. That single requirement is enough to rule out SSE regardless of how one-sided the rest of the traffic looks, since an `EventSource` has no channel back to the server at all.

Contrast that with the warehouse dashboard from the opening paragraph: a browser tab, server-pushed updates only, no per-booking subscription to renegotiate because it watches everything on the yard floor at once, and a known network path inside the company's own data center that keeps streaming responses open without interference. That interaction answers "server only" and "streaming-friendly path" and lands on SSE, with none of the connection-pinning or reconnection code a WebSocket would require for a client that never needed to send anything back. The customs broker's integration answers "another service" and "no reachable endpoint," which is why it polls rather than failing outright: not every real interaction gets a satisfying answer, and polling on a schedule is still the correct tool when the alternative isn't available on the other end.

## On the wire

The dimensions above are not abstract once you look at the bytes. An SSE response is still being written by the server when the browser starts reading it: a `200 OK` whose body never closes, carrying a simple text framing:

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive

event: handling_event
id: 48219
data: {"booking_id":"BKG-88213","type":"CUSTOMS_HOLD","location":"USLAX","occurred_at":"2026-10-18T14:02:11Z"}

event: handling_event
id: 48220
data: {"booking_id":"BKG-88213","type":"CONTAINER_LOADED","location":"USLAX","occurred_at":"2026-10-18T14:05:47Z"}

```

Every event is three lines of plain text ending in a blank line, the `id` field is what the browser echoes back as `Last-Event-ID` on reconnect, and the client never writes anything on this connection beyond the original GET. One HTTP response, one direction, no framing beyond what a text editor can read.

A WebSocket starts the same way every HTTP request does, then stops being HTTP entirely:

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

After the `101`, there is no more request/response: both sides exchange framed messages whenever they have one to send, and the frame's own header (a minimum of two bytes) is the only overhead HTTP's own headers used to carry. The booking page's first move after the upgrade is a client-to-server frame SSE has no channel for at all:

```json
{"action":"subscribe","booking_id":"BKG-88213"}
```

and the server answers, on the same connection, with the same event an SSE feed would have sent as plain text:

```json
{"type":"handling_event","booking_id":"BKG-88213","event":"CUSTOMS_HOLD","location":"USLAX","occurred_at":"2026-10-18T14:02:11Z"}
```

Same payload, same domain event, two different wires. One of them has a direction the other one never carries at all.

## Where this goes next

This chapter assumed a WebSocket's shape without explaining where it comes from: what the `Upgrade` handshake negotiates, how a frame's header encodes its length and type, what a close frame looks like, and why a proxy that doesn't understand any of that drops the connection instead of relaying it. The protocol itself opens next: the handshake in full, the frame format, text versus binary frames, control frames, and the parts of RFC 6455 every later chapter leans on without re-deriving. The shared domain comes back after that with the full handling-event shape this chapter only sketched, and the AsyncAPI contract puts that shape into a schema both stacks generate from.

Running the booking page's handling-event feed through the same questions gives the shape every later chapter's own version of this decision will take:

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>The booking page's handling-event feed is a WebSocket, not SSE, a long-poll, a webhook, or a gRPC stream. It needs live updates, ruling out plain request/response. It needs the client to send as well as receive (an initial subscribe naming the booking, and a resubscribe if the customer switches bookings without reloading the page), which rules out SSE's one-way channel regardless of how server-heavy the traffic looks. The receiver is a browser tab the team controls, which rules out a webhook, since nothing here can expose a public endpoint for someone else to call. And the volume and latency the customer expects (a status change reflected in under a second, not polled for) rule out both long-polling's per-update request cost and gRPC streaming's requirement that neither end be a browser. Every other interaction in this chapter's opening paragraph lands somewhere else on this same table, which is the point: the socket is correct here because the dimensions say so, not because this is a WebSockets site.</p></div>

## For deeper coverage

- Dynowski, L. & Dulak, M., *Learning API Styles* (O'Reilly, 2025): comparing interaction styles on the dimensions this chapter's decision framework formalizes.
- Gough, J. & Bryant, D. & Auburn, M., *Mastering API Architecture* (O'Reilly, 2022): architectural trade-offs behind choosing a style for a given interaction rather than defaulting to one.
- *Cloud Native Design Patterns*, "Communications" and "Protocols in Depth" chapters: the full comparison this chapter's transport table specializes for a push interaction.
- [RFC 6455](https://datatracker.ietf.org/doc/html/rfc6455): the WebSocket side of this chapter's comparison.
- [WHATWG: Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html): the `EventSource` behavior, including automatic reconnection and `Last-Event-ID`, this chapter compares against a socket.
