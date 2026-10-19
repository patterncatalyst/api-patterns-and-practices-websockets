---
title: "Optimizing Throughput"
order: 20
part: "Performance & Optimization"
description: "Tuning a socket server for throughput once it carries real load."
duration: "18 min read"
---

Chapter 19 proved Protobuf frames measure smaller than JSON frames for the same `HandlingEvent` and left one question open: does that size difference show up anywhere a server operator would notice it, and what else is sitting on the table once wire size stops being the only lever? `examples/part5-performance/k6/benchmark.js` answers the first half directly — it drives both encodings, plus a JSON-with-compression variant, against both stacks and prints bytes/frame, connects/sec, and success rate side by side. It also raises a question this chapter has to answer with precision: what can that benchmark prove, and where does its own tooling stop being able to see the thing it's measuring? This chapter walks four levers that bound a WebSocket server's throughput — encoding (recap from Ch19), batching, compression, and size limits — then closes with Chapter 12's backpressure as the ceiling all four sit under, and the k6 numbers that ground every claim in real, captured output rather than an assumed percentage.

## Encoding: a fixed, load-independent cost

Chapter 19's 40.7% figure (154.0B Protobuf vs. 259.7B JSON, averaged across every frame `benchmark.js` captured) is the first lever, and it's the simplest one to reason about because it doesn't move: `examples/part5-performance/README.md`'s own measured-numbers table states directly that "the bytes/frame column was identical across every run of this benchmark regardless of load — it's the fixture frame size, not a function of throughput." A server pushing one event per second and a server pushing ten thousand pay the identical per-frame cost difference between the two encodings; Protobuf's saving is a flat discount on every frame, not something that compounds or degrades under pressure. That's worth separating out before the levers below, because every other one interacts with load in ways encoding doesn't — batching changes shape as the queue backs up, compression's CPU cost scales with frame count, and size limits only bite once a payload is large enough to hit them. Encoding is the one number in this chapter you can multiply by frame count and trust at any scale.

## Batching and coalescing: fewer, larger frames

Every WebSocket frame carries overhead independent of its payload — framing bytes, a TCP/IP header on the wire below it, a syscall on each end to write and read it. For a channel pushing many small events in quick succession, sending each one in its own frame means paying that fixed cost once per event; batching several events into one frame means paying it once per batch. `contracts/handling-event.proto`'s `HandlingEvent` message has no wrapper for "many of these in one frame" today — this channel's own replay-3-then-idle shape (every chapter from Ch19 forward) sends the three fixture events as three separate frames, one `sendText`/`sendBinary` or `ws.send` call per event, the same granularity JSON used before it. A channel that pushed continuously, rather than three events and then idle, is where batching pays off: coalescing a window of events — by count, by a short time budget, or both — into one frame (a JSON array, or a repeated Protobuf field) amortizes the per-frame overhead across every event riding inside it.

That amortization isn't free, and the cost is latency, not bytes. A batch window of 50ms means the first event into a batch waits up to 50ms for its frame to go out, even if the channel has nothing else to send it with. For `HandlingEvent`s, where Chapter 1 already frames the domain as "a human on the other end of this socket, watching a shipment move," a 50ms hold is invisible; a control-plane channel reporting actuator state at kilohertz rates would feel that same window as unacceptable staleness. The decision is the same shape every time: batch when the events are small and frequent enough that per-frame overhead dominates the actual payload, and when the consumer can tolerate the hold; send each event immediately when a human or a downstream system needs it the moment it happens, even at the cost of more, smaller frames. This channel's design — three events on connect, immediate per-event delivery, no batching — is itself a choice, made the same way: correctness and immediacy over frame-count efficiency, because the three fixture events in this example are rare enough that batching them would save bytes nobody is short on.

## Compression: permessage-deflate, and the stack difference `benchmark.js` found live

Chapter 3 introduced permessage-deflate (RFC 7692) as an extension negotiated via `Sec-WebSocket-Extensions`, compressing each frame's payload with DEFLATE before it's framed, and flagged two costs alongside the bandwidth win: CPU per frame, memory per connection for compression state, and — on a connection carrying anything sensitive — a CRIME-adjacent attack class where an attacker who can influence part of a compressed, encrypted payload can use the resulting compression-ratio changes as a side channel to recover secrets it shares the stream with. Chapter 3 left the decision open, pending measurement against this site's own payload shapes. `k6/benchmark.js`'s `json_deflate` scenario is that measurement, and it surfaced something the chapter didn't expect going in: the two stacks don't even agree on whether compression gets negotiated at all.

Python's `websockets` library enables `compression="deflate"` as its own **default** — `serve()`'s signature in `websockets/asyncio/server.py` spells it out: `compression: str | None = "deflate"`, and the library's own docstring says "the permessage-deflate extension is enabled by default." `examples/part5-performance/python/app/ws_server.py`'s `create_server` never passes a `compression` argument at all, so it inherits that default without any code change announcing it — every connection to Python's `:8091` negotiates permessage-deflate unless a caller explicitly disables it. Quarkus WebSockets Next takes the opposite default: `WebSocketsServerRuntimeConfig.perMessageCompressionSupported()` is a server-level switch, off unless an application turns it on, and `examples/part5-performance/quarkus/src/main/resources/application.properties` never sets it. The result, confirmed across three separate `benchmark.js` runs against both stacks (the README's "permessage-deflate negotiation differed by stack" finding): Python negotiated the extension on `7908/7908` successful connects — 100% — while Quarkus negotiated it on `0` out of `11806`–`18292` connect attempts across the same three runs. Same client, same `compression: "deflate"` request on every scenario, two servers that disagree about whether to say yes, purely because one library ships the feature on and the other ships it off.

{% include codetabs.html langs="Quarkus|Python" %}

```properties
# examples/part5-performance/quarkus/src/main/resources/application.properties
# NOT set in this example — permessage-deflate is opt-in on WebSockets Next.
# To negotiate it, add:
quarkus.websockets-next.server.per-message-compression-supported=true
quarkus.websockets-next.server.compression-level=6
```
```python
# examples/part5-performance/python/app/ws_server.py's create_server() never
# passes `compression` — it inherits the websockets library's own default,
# "deflate", so every connection negotiates it unless told not to:
return serve(
    handler,
    host,
    port,
    subprotocols=SUPPORTED_SUBPROTOCOLS,
    select_subprotocol=_select_subprotocol,
    # compression="deflate" is the library default here — pass
    # compression=None explicitly to opt OUT instead.
)
```

{% include excalidraw.html file="20-bytes-per-frame" alt="A benchmark box runs three scenarios against the same channel and fixture: json measuring 259.7 bytes average, protobuf measuring 154.0 bytes average and 40.7 percent smaller, and json plus deflate measuring 259.7 bytes average, identical to plain json, with a ghost box noting k6/ws inflates compressed frames before the script sees the bytes so this row cannot show the win. Below, two sub boxes report the real permessage-deflate negotiation counts: Python on port 8091 negotiated it on 7908 of 7908 connects, 100 percent; Quarkus WebSockets Next on port 8090 negotiated it on 0 of 11806 to 18292 attempts across three runs, 0 percent. A ghost caption states this is the same stack difference reproduced across every run, not proof deflate does not help, proof k6/ws cannot see it." caption="Figure 20.1 — the measured bytes/frame comparison and the real stack difference in whether permessage-deflate gets negotiated at all; the deflate row's bytes/frame is a blind spot, not evidence against compression." %}

This is exactly the kind of finding a measurement chapter exists to surface rather than paper over: it isn't that deflate "doesn't work" on Quarkus, or that Python's default is wrong — it's that permessage-deflate support is a server-side opt-in on one framework and an opt-out on the other, and a team deploying the same logical feature on both stacks without reading each framework's defaults would end up compressing on one and not the other without ever deciding to. Whether to enable it at all still comes back to Chapter 3's two costs: a feed of small, repetitive JSON frames (`HandlingEvent`'s field names repeat on every push) is a reasonable compression candidate on bandwidth grounds alone, but a connection carrying anything where an attacker-influenced value and a secret share the same compressed stream is exactly the CRIME-adjacent shape Chapter 3 warned about, and compression on that connection needs an explicit decision, not an inherited library default discovered after the fact.

## What `benchmark.js` can't see: the deflate-size blind spot

The `json_deflate` scenario's bytes-per-frame numbers in the table above read **identical** to the plain `json` row — 259.7B average, 267.0B p90, on both stacks. That is not evidence that compression had no effect on the wire. `k6/ws` is built on `gorilla/websocket`, and gorilla **transparently inflates** a compressed frame before handing its bytes to the calling script — there is no `k6/ws` API that exposes the compressed, on-the-wire length. `benchmark.js`'s own header comment states this directly: the `json_deflate` scenario's `bytesTrend` "measures the same POST-INFLATION payload size as the plain json scenario by construction; it proves nothing about deflate's wire savings." What the script *can* observe with no inference required is whether the extension got negotiated at all, read from the echoed `Sec-WebSocket-Extensions` response header — which is exactly the 100%-vs-0% finding above, and the only deflate-related number this chapter treats as proven rather than inferred.

The lesson generalizes past this one script: before citing a measurement as proof an optimization works (or doesn't), check what the measuring tool is capable of observing at the layer being tested. A client library that handles a protocol feature transparently — decompression, redirect-following, automatic retry — is doing a client a favor in production and taking away exactly the visibility a benchmark needs to measure that feature's effect. `k6/experimental/websockets` or a packet capture below the TLS/TCP stack would see the compressed bytes directly; this project didn't reach for either, because the negotiation finding above was the more important result and didn't need them. A team that needs deflate's actual wire-size win measured, beyond its negotiation confirmed, needs a tool that doesn't inflate the frame before the measurement point.

## Size limits: bounding a single frame or message

Chapter 12 built a bounded *outbound queue* — how many not-yet-acknowledged sends a connection is allowed to carry before backpressure kicks in. A size limit is a different bound on the same kind of risk: how large a single frame or message is allowed to be, regardless of queue depth. Both stacks expose this, and both default to a real limit rather than "unbounded":

{% include codetabs.html langs="Quarkus|Python" %}

```properties
# quarkus.websockets-next.server.max-message-size and
# quarkus.websockets-next.server.max-frame-size (both OptionalInt —
# unset means no application-level cap beyond Vert.x/Netty's own defaults).
# Neither is set in this example; a production deployment accepting
# attacker-reachable messages would want an explicit value here rather
# than relying on the framework's own default ceiling.
quarkus.websockets-next.server.max-message-size=1048576
quarkus.websockets-next.server.max-frame-size=65536
```
```python
# websockets.asyncio.server.serve()'s own signature:
#   max_size: int | None | tuple[int|None, int|None] = 2**20   # 1 MiB
#   max_queue: int | None | tuple[int|None, int|None] = 16
# ws_server.py's create_server() doesn't override either — every
# connection inherits the library's 1 MiB max_size and depth-16
# max_queue, a real default, not "no limit", even though this example
# never names it explicitly.
return serve(
    handler,
    host,
    port,
    max_size=2**20,   # explicit here for clarity; same as the default
    subprotocols=SUPPORTED_SUBPROTOCOLS,
    select_subprotocol=_select_subprotocol,
)
```

`examples/part5-performance` never exercises either limit — the fixture's largest frame is 267 bytes, nowhere near either stack's default ceiling — but the limits exist in both frameworks for the same reason Chapter 12's queue bound exists: without one, a single oversized frame (malicious or merely buggy, a client or a misbehaving upstream service sending something enormous into one WebSocket message) consumes memory proportional to its own size before any application code gets a chance to reject it. A bound at the protocol layer — reject the frame, close the connection with 1009 (Message Too Big, RFC 6455's reserved code for exactly this) — is cheaper than discovering the same problem after the fact as a `HandlingEvent` a hundred megabytes deep into a feed that should never have payloads over a few hundred bytes. Python's `websockets` library picks 1 MiB as a sane global default; Quarkus WebSockets Next leaves both knobs unset by default, meaning the effective ceiling is whatever Vert.x/Netty's own configuration permits beneath it — a gap worth closing explicitly on any channel accepting payload sizes it hasn't bounded by contract.

## Backpressure bounds every lever above it

Chapter 12 built the mechanism this section leans on without repeating it: `OutboundBackpressureGuard` (Quarkus) and the bounded `asyncio.Queue` (Python) cap how many outstanding sends a single slow connection is allowed to accumulate before the server closes it (policy `CLOSE`) or starts dropping (policy `DROP`). Every lever this chapter has covered so far — a smaller Protobuf frame, a larger batched frame, a compressed frame, a size-capped frame — produces *something* that still has to go out over one connection's send path, and Chapter 12's bound governs that send path regardless of which encoding, batch size, or compression state produced the bytes. A Protobuf-encoded, deflate-compressed, tightly batched frame that a slow client's TCP receive window can't drain still blocks on the same `sendText`/`send()` call Chapter 12's timeout watches, and still trips the same `maxPendingSends`/`QUEUE_MAXSIZE` bound if enough of them queue up behind it.

That interplay runs in both directions. A smaller frame (Protobuf) or a compressed one (deflate) reduces the bytes a slow consumer's TCP window has to drain per message, which means more messages fit before backpressure trips — the same queue depth buys more actual throughput once each queued item costs less. Batching cuts the other way: fewer, larger frames reduce per-frame overhead, but each individual item in the bounded queue now represents more accumulated work, so a queue that trips at the same depth trips after less total *event* throughput than it would with unbatched, smaller sends. None of the four levers in this chapter changes whether backpressure exists or what triggers it — they only change how much useful work a connection gets through before hitting the ceiling Chapter 12 already built. A deployment reaching for Protobuf or compression purely to raise sustained throughput, without checking whether the outbound queue bound (`maxPendingSends`/`QUEUE_MAXSIZE`, both defaulting to 32) is still appropriately sized for the new, smaller per-item cost, is leaving part of that gain unclaimed.

{% include excalidraw.html file="20-levers" alt="A band labeled one HandlingEvent pushed over one connection contains four lever boxes. Lever one, encoding from Chapter 19, an accent box reading JSON versus Protobuf fixed per frame cost 40.7 percent smaller deterministic. Lever two, batching and coalescing, amortize per frame overhead, fewer larger frames adds latency. Lever three, permessage deflate RFC 7692, per connection DEFLATE state CPU per frame, Python on by default Quarkus opt in zero percent here. Lever four, size limits, max message size and max frame size on Quarkus, max size and max queue on Python. Below all four, a wide ink emphasis box labeled backpressure from Chapter 12 bounds all of the above under a slow consumer, a full queue or a stalled sendText caps effective throughput regardless of encoding or compression. A ghost caption below states k6 measures connection churn here not a sustained push rate." caption="Figure 20.2 — four throughput levers, one shared ceiling: Chapter 12's bounded outbound queue governs every byte every lever above it produces." %}

## Measuring with discipline: ratios over host-dependent absolutes

`examples/part5-performance/README.md` draws a line this chapter has followed throughout: `smoke.js` is gated CI, fast and deterministic; `benchmark.js` is comparative and local-only, explicitly excluded from any CI threshold because "absolute throughput is host-dependent, which would make a flaky CI threshold." The numbers cited in this chapter back that line up directly. The connects/sec figures — 2114.2/s and 2123.4/s for Quarkus's json and protobuf scenarios, 1703.9/s and 1701.9/s for Python's — moved across different runs on the same project's own dev box: the README documents a Quarkus run measuring 100%/100%/100% connect success on a freshly booted container, and a separate run measuring as low as 2/6108 after back-to-back heavy runs exhausted the host's ephemeral TCP port range (`TIME_WAIT` sockets from roughly 55,000 prior connections left no ports free to accept new ones). Citing "2114 connects/sec" as a property of Quarkus WebSockets Next would be citing a number that depends more on how recently the container restarted than on anything the framework does.

What *is* stable, and worth citing without hedging, are the relative claims: Protobuf's 40.7% size reduction over JSON, measured identically across every run regardless of load. Python negotiating permessage-deflate on every connect against Quarkus negotiating it on none, reproduced across three separate runs. Within a single run, json/protobuf/json_deflate's connect-success rates track each other closely — encoding choice doesn't change the local host's accept-queue ceiling — even while the absolute ceiling itself drifts from run to run. That's the discipline this chapter asks of any throughput measurement: a ratio or a negotiation outcome, captured consistently across repeated runs, is a claim about the system; a raw rate captured once, on one host, in one state, is a claim about that host at that moment. `k6/benchmark.js` stays out of the CI gate for exactly that reason — its printed comparison is what a chapter cites, never what a pipeline asserts a pass/fail threshold against.

## On the wire

Two scripts under `examples/part5-performance/k6/`, both pinned to k6 2.3.0 (the same pin as every k6 script this site has used since Part 4): `smoke.js` is the gated CI check, `benchmark.js` is the local-only comparison this chapter has cited throughout. Run the benchmark from the repo root:

```bash
cd examples/part5-performance
docker compose up --build -d quarkus python

K6_WS_URL="ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
PART5_BENCH_VUS=2 PART5_BENCH_DURATION=8s \
  k6 run k6/benchmark.js
```

`PART5_BENCH_VUS` and `PART5_BENCH_DURATION` — not `K6_VUS`/`K6_DURATION`, which are k6-reserved env vars that discard this script's `options.scenarios` outright in favor of a single default scenario — control the per-scenario sustained-load window; the three scenarios (`json`, `protobuf`, `json_deflate`) run concurrently against whichever `K6_WS_URL` is pointed at. The captured table below is the one this chapter's levers section cites directly — Quarkus `:8090` and Python `:8091`, `PART5_BENCH_VUS=2`, `PART5_BENCH_DURATION=8s`, each stack freshly restarted and given time for the OS's ephemeral TCP range to drain `TIME_WAIT` before measuring:

| Stack | Encoding | bytes/frame (avg / p90) | connects (success %) | frames/sec |
|---|---|---:|---:|---:|
| Quarkus `:8090` | json | 259.7B / 267.0B | 9868/11967 (82.5%) | 2114.2/s |
| Quarkus `:8090` | protobuf | 154.0B / 157.0B | 9911/12001 (82.6%) | 2123.4/s |
| Quarkus `:8090` | json+deflate | 259.7B / 267.0B | 9718/11806 (82.3%) | 2082.0/s |
| Python `:8091` | json | 259.7B / 267.0B | 7952/7952 (100.0%) | 1703.9/s |
| Python `:8091` | protobuf | 154.0B / 157.0B | 7943/7943 (100.0%) | 1701.9/s |
| Python `:8091` | json+deflate | 259.7B / 267.0B | 7908/7908 (100.0%) | 1694.4/s |

Three things this table does and doesn't say, stated the way `benchmark.js`'s own `handleSummary` prints them: first, bytes/frame is the fixture's size, not a function of throughput — Protobuf's 40.7% reduction (154.0B vs. 259.7B avg) holds regardless of VU count or duration. Second, `json+deflate`'s bytes/frame reads identical to plain `json` on both stacks — that's the k6/ws inflate-before-measurement limitation described above, not evidence deflate failed; the separate `permessage-deflate negotiated` counter (7908/7908 on Python, 0 across 11806–18292 attempts on Quarkus) is the number this chapter treats as proven. Third, "frames/sec" is connection-churn throughput — this channel replays its 3 fixture events on connect and then stays idle, so each VU's loop is open-connection, read-3-frames, close, repeat, as fast as it can; it is not a sustained per-connection push rate, and the 82.5%-ish connect-success rate on Quarkus in this capture (versus 100% on Python, and versus 100%/100%/100% the README also records on a freshly booted Quarkus container before any other run had touched it) is this run's share of a local-host ephemeral-port ceiling, not a property either framework guarantees.

Push these metrics into the project's LGTM stack with k6's built-in OpenTelemetry output — no script change required:

```bash
K6_OTEL_GRPC_EXPORTER_INSECURE=true K6_OTEL_GRPC_EXPORTER_ENDPOINT=localhost:4317 \
  k6 run -o opentelemetry k6/benchmark.js
```

`smoke.js`, by contrast, is the fast, deterministic, gated half of this split — 3 VUs, 1 iteration each, every check wired into a `rate==1.0` threshold that fails the whole run (and the PR) the moment one assertion fails:

```bash
K6_WS_URL="ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
  k6 run k6/smoke.js
```

A passing `smoke.js` run was confirmed live against both stacks on this project's own CI runner (2026-10-19): 54/54 checks on Quarkus `:8090`, 54/54 on Python `:8091` — both JSON-as-TEXT and Protobuf-as-BINARY, on both stacks, every PR.

## Where this goes next

This chapter closes Part 5. Chapter 19 moved the wire format to Protobuf and measured the frame-size win; this chapter walked the remaining levers that shape throughput around that encoding choice — batching's latency-for-overhead trade, permessage-deflate's real stack-by-stack difference in whether it's even negotiated, size limits as the protocol-layer bound a connection needs regardless of payload shape, and Chapter 12's backpressure as the ceiling every one of those levers operates underneath. The measurement discipline running through all of it matters as much as any single number: a ratio or a negotiation outcome, reproduced across runs, is a claim about the system; a raw connects/sec figure captured once on one host is a claim about that host's ephemeral-port state at that moment, which is exactly why `k6/benchmark.js` stays local-only and `k6/smoke.js` is the one that gates a PR.

Part 6, Testing, Debugging & Observability, picks up from here with a different question: not how fast a channel can go, but how a team proves it still behaves correctly, finds out why it doesn't, and watches it in production once it's live. The k6 scripts this chapter leaned on are themselves half of that answer — a gated smoke test and a local comparative benchmark are both testing infrastructure, aimed at different questions — and the next chapters widen that lens to the rest of the toolbox: structured test suites across both stacks, the debugging workflow for a connection that's misbehaving in ways a log line alone doesn't explain, and the OpenTelemetry instrumentation this site has wired through every example's `OTEL_EXPORTER_OTLP_ENDPOINT` since Part 3 without yet asking what it's for.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>Treat throughput as four independent levers sitting on top of one shared ceiling, not one knob. Encoding (Ch19's Protobuf vs. JSON) is a fixed, load-independent per-frame discount — 40.7% smaller, measured identically at any connection rate. Batching trades latency for fewer, larger frames, and only pays off once per-frame overhead dominates a small, frequent payload. Compression is a per-stack opt-in, not a universal default: Python's <code>websockets</code> library negotiates permessage-deflate unless told not to, Quarkus WebSockets Next requires <code>quarkus.websockets-next.server.per-message-compression-supported=true</code> to negotiate it at all — this example's own benchmark measured 100% negotiation on Python against 0% on Quarkus with the identical client request, a real framework-default difference to check before assuming a feature is active on both stacks. Size limits (<code>max-message-size</code>/<code>max-frame-size</code> on Quarkus, <code>max_size</code>/<code>max_queue</code> on Python, the latter defaulting to a real 1&nbsp;MiB ceiling even when unset explicitly) bound a single frame the same way Chapter 12's queue bounds accumulated sends. Backpressure governs all four: a smaller or compressed frame buys more throughput for the same queue depth, a batched one buys less, but none of them changes whether or when the bound trips. Measure every claim as a ratio or a negotiation outcome reproduced across repeated runs — never as a bare connects/sec number from one host in one ephemeral-port state — which is exactly why <code>k6/benchmark.js</code> stays local-only and cited in prose, while <code>k6/smoke.js</code>'s deterministic checks are the ones that gate a PR.</p></div>
