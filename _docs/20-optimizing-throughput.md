---
title: "Optimizing Throughput"
order: 20
part: "Performance & Optimization"
description: "Four throughput levers on a socket server: encoding, batching, permessage-deflate and size limits, and how to measure them."
duration: "18 min read"
---

## Learning objectives

By the end of this chapter you can:

- Measure Protobuf's frame-size discount against JSON and explain why it holds at any load.
- Decide when to batch events into fewer, larger frames, trading added latency for lower per-frame overhead.
- Check a stack's permessage-deflate default before assuming it's active.
- Bound a single frame or message with `max-message-size` and `max-frame-size` (Quarkus) or `max_size` (Python).
- Tell a reproducible ratio or negotiation outcome from a host-dependent absolute rate when citing a benchmark.

## Why this matters

Protobuf frames are smaller than JSON frames for the same `HandlingEvent`. Whether that matters to an operator, and what else limits throughput once wire size is settled, takes measurement. Four levers bound a WebSocket server's throughput: encoding, batching, compression and size limits. Backpressure is the ceiling all four sit under. A k6 benchmark drives both encodings, plus JSON with compression, against both stacks and prints bytes per frame, connects per second and success rate side by side.

| Lever | What it changes | Cost |
|---|---|---|
| Encoding | Bytes per frame, fixed | Schema and codegen |
| Batching | Per-frame overhead | Added latency |
| permessage-deflate | Bytes on the wire | CPU, per-connection memory, a compression side channel |
| Size limits | Worst-case memory per frame | Legitimate large messages are rejected |

## Encoding: a fixed, load-independent discount

Protobuf frames measure 40.7% smaller than JSON (154.0 bytes against 259.7 on average). The bytes-per-frame column is identical across every benchmark run regardless of load, because it's the size of the fixture frame, not a function of throughput. A server pushing one event per second and one pushing ten thousand pay the same per-frame difference. Encoding is the one number here you can multiply by frame count and trust at any scale. Every other lever interacts with load: batching changes shape as the queue backs up, compression's CPU cost scales with frame count, and size limits only bite on large payloads.

## Batching and coalescing: fewer, larger frames

Every frame carries overhead independent of its payload: framing bytes, TCP and IP headers, and a syscall on each end. Sending each small event in its own frame pays that cost once per event. Coalescing a window of events, by count, by a short time budget or both, into one frame (a JSON array, or a repeated Protobuf field) pays it once per batch.

The cost is latency, not bytes. A 50 ms batch window means the first event in a batch waits up to 50 ms for its frame to leave, even if nothing else is coming. For a human watching a shipment move, that hold is invisible. For a channel reporting actuator state at kilohertz rates, it's unacceptable staleness.

| Batch | Send immediately |
|---|---|
| Events are small and frequent enough that per-frame overhead dominates the payload | A person or downstream system needs each event the moment it happens |
| The consumer tolerates the hold | Events are rare, so there is little overhead to amortize |

The server sends its three events on connect as three separate frames, one per event. They're rare enough that batching would save bytes nobody is short on.

## Compression: permessage-deflate and the stack difference

permessage-deflate (RFC 7692) is negotiated through `Sec-WebSocket-Extensions` and compresses each frame's payload with DEFLATE. It costs CPU per frame and memory per connection for compression state. On a connection that carries secrets, it also opens a CRIME-style side channel: an attacker who can influence part of a compressed, encrypted payload can read compression-ratio changes to recover secrets sharing the stream.

The two stacks disagree on the default. Python's `websockets` enables `compression="deflate"` unless told otherwise, and `create_server` never passes the argument, so every connection to the Python server negotiates it. Quarkus WebSockets Next ships it off: `per-message-compression-supported` is a server-level switch, and the server here never sets it. With the same client requesting deflate in every scenario, Python negotiated the extension on 7,908 of 7,908 successful connects across a run, and Quarkus on none of 11,806 to 18,292 attempts across three runs.

{% include codetabs.html langs="Quarkus|Python" %}

```properties
# Add to application.properties to negotiate permessage-deflate
quarkus.websockets-next.server.per-message-compression-supported=true
quarkus.websockets-next.server.compression-level=6
```
```python
def create_server(host: str, port: int):
    """Returns the `websockets.asyncio.server.serve(...)` context manager;
    callers `async with` it (see app/main.py) to start/stop the listener.
    `subprotocols` advertises the three supported values; `select_subprotocol`
    overrides the library's default negotiation to also accept a client that
    offers none at all; see `_select_subprotocol`.
    """
    return serve(
        handler,
        host,
        port,
        subprotocols=SUPPORTED_SUBPROTOCOLS,
        select_subprotocol=_select_subprotocol,
    )
```

On the Python side, pass `compression=None` to `serve` to opt out. A team deploying the same feature on both stacks without reading each default compresses on one and not the other without ever deciding to. A feed of small, repetitive JSON frames, where `HandlingEvent` field names repeat on every push, is a reasonable candidate on bandwidth grounds. A connection where an attacker-influenced value and a secret share one compressed stream needs an explicit decision, not an inherited default.

{% include excalidraw.html file="20-bytes-per-frame" alt="A benchmark runs three scenarios against one channel: JSON at 259.7 bytes per frame, Protobuf at 154.0 bytes (40.7 percent smaller), and JSON with deflate also at 259.7 bytes because k6 inflates frames before the script sees them. Below, the negotiation counts: Python negotiated deflate on 7908 of 7908 connects, Quarkus on none of 11806 to 18292 attempts." caption="Figure 20.1: measured bytes per frame and the permessage-deflate negotiation difference between the stacks; the deflate row's size is a measurement blind spot, not evidence against compression." %}

### What the benchmark can't see

The `json_deflate` row reads 259.7 bytes on average and 267.0 at p90, identical to plain JSON on both stacks. That says nothing about compression's wire savings. `k6/ws` is built on `gorilla/websocket`, which transparently inflates a compressed frame before handing it to the script, and no `k6/ws` API exposes the on-the-wire length. What the script can observe is whether the extension was negotiated, read from the echoed `Sec-WebSocket-Extensions` response header. That is the only deflate number here to treat as proven.

Before citing a measurement as proof that an optimization works, check what the tool can observe at the layer under test. A client library that handles a feature transparently (decompression, redirects, retries) helps in production and hides exactly what a benchmark needs. To measure deflate's actual wire savings, use a tool that doesn't inflate before the measurement point, such as `k6/experimental/websockets` or a packet capture below TLS.

## Size limits: bounding a single frame

A bounded outbound queue limits how many sends a connection can carry. A size limit bounds something different: how large one frame or message may be, regardless of queue depth. Without one, a single oversized frame, from a malicious client or a buggy upstream, consumes memory proportional to its size before any application code can reject it. A limit at the protocol layer rejects the frame and closes the connection with 1009 (Message Too Big), which is cheaper than discovering a `HandlingEvent` a hundred megabytes deep.

| | Quarkus | Python (`websockets`) |
|---|---|---|
| Message limit | `max-message-size` | `max_size`, default 1 MiB |
| Frame limit | `max-frame-size` | Second element of a `max_size` tuple, `(message, fragment)`; unset by default |
| Inbound buffer | `max-pending-messages` | `max_queue`, default 16 messages |
| Default | Unset, so whatever the Vert.x and Netty layers beneath permit | A real 1 MiB message ceiling |

Neither server sets these. To bound them, add the Quarkus properties, or pass `max_size` (an integer, or a `(message, fragment)` tuple) to Python's `serve`:

```properties
quarkus.websockets-next.server.max-message-size=1048576
quarkus.websockets-next.server.max-frame-size=65536
```

Neither limit is exercised: the largest fixture frame is 267 bytes. Any channel that accepts payloads not bounded by contract should set the Quarkus values explicitly.

## Backpressure bounds every lever

Every lever produces bytes that still leave through one connection's send path, and the backpressure bound governs that path whatever produced them. A Protobuf-encoded, compressed, batched frame that a slow client's TCP window can't drain still blocks the same send call and still trips the same queue bound when enough of them stack up.

The levers pull in different directions on that bound:

- A smaller frame (Protobuf) or a compressed one means each queued item costs a slow consumer's window fewer bytes, so more messages fit before the bound trips.
- A batched frame means each queue slot holds more events, so the same queue depth trips after less total event throughput than unbatched sends.

None of the four levers changes whether backpressure exists or what triggers it. They change how much work a connection completes before reaching it. If you adopt Protobuf or compression to raise sustained throughput, recheck that the outbound queue bound (`example.backpressure.max-pending-sends` on Quarkus, `OUTBOUND_QUEUE_MAXSIZE` on Python, both 32 by default in `examples/part4-connection`) still suits the smaller per-item cost.

{% include excalidraw.html file="20-levers" alt="One HandlingEvent pushed over one connection passes through four lever boxes: encoding (Protobuf 40.7 percent smaller, deterministic), batching (fewer, larger frames, adds latency), permessage-deflate (CPU per frame, on by default in Python, opt-in on Quarkus) and size limits. A wide box beneath them labeled backpressure caps effective throughput regardless of the levers above." caption="Figure 20.2: four throughput levers share one ceiling, the bounded outbound queue." %}

## Measuring with discipline: ratios over absolute rates

The k6 `smoke.js` script is a gated CI check: fast, deterministic, every check wired into a threshold that fails the run. The `benchmark.js` script is comparative and local only, excluded from any CI threshold because absolute throughput depends on the host. Quote its output in prose; never assert a pass or fail threshold against it.

The connects-per-second figures moved between runs on the same machine. One Quarkus run on a freshly booted container measured 100% connect success on every scenario. A later run after back-to-back heavy runs measured as low as 2 of 6,108, because roughly 55,000 prior connections left the ephemeral port range full of `TIME_WAIT` sockets. Citing "2,114 connects per second" as a property of a framework would report how recently the container restarted.

What is stable and safe to cite:

- Protobuf's 40.7% size reduction, identical across every run.
- Python negotiating permessage-deflate on every connect and Quarkus on none, reproduced across three runs.
- Within one run, JSON, Protobuf and JSON+deflate success rates track each other, so encoding doesn't change the local accept ceiling even as that ceiling drifts between runs.

A ratio or a negotiation outcome reproduced across runs is a claim about the system. A raw rate captured once is a claim about that host at that moment.

The benchmark's "frames per second" is connection-churn throughput. The channel replays three fixture events on connect and then stays idle, so each virtual user opens a connection, reads three frames, closes and repeats. It is not a sustained push rate. A captured run with two virtual users for eight seconds:

| Stack | Encoding | bytes/frame (avg / p90) | connects (success %) | frames/sec |
|---|---|---:|---:|---:|
| Quarkus `:8090` | json | 259.7B / 267.0B | 9868/11967 (82.5%) | 2114.2/s |
| Quarkus `:8090` | protobuf | 154.0B / 157.0B | 9911/12001 (82.6%) | 2123.4/s |
| Quarkus `:8090` | json+deflate | 259.7B / 267.0B | 9718/11806 (82.3%) | 2082.0/s |
| Python `:8091` | json | 259.7B / 267.0B | 7952/7952 (100.0%) | 1703.9/s |
| Python `:8091` | protobuf | 154.0B / 157.0B | 7943/7943 (100.0%) | 1701.9/s |
| Python `:8091` | json+deflate | 259.7B / 267.0B | 7908/7908 (100.0%) | 1694.4/s |

> **Decision**
>
> Treat throughput as four levers under one ceiling. Encoding is a fixed per-frame discount, 40.7% here. Batch only when per-frame overhead dominates small, frequent events and the consumer tolerates the hold. Check each stack's permessage-deflate default (on in Python, opt-in in Quarkus) and decide explicitly on any connection that carries secrets. Set `max-message-size` and `max-frame-size` on Quarkus; Python's `max_size` already defaults to 1 MiB. Report ratios and negotiation outcomes reproduced across runs, never a bare rate from one host.

> **🤖 Explore with your agent**
>
> "In `examples/part5-performance`, make the Quarkus server negotiate permessage-deflate with `quarkus.websockets-next.server.per-message-compression-supported=true`, rebuild, and run `k6/benchmark.js` against `ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events` with `PART5_BENCH_VUS=2 PART5_BENCH_DURATION=8s`. Then report whether the `json_deflate` scenario's negotiated count changed and whether its bytes per frame changed, and say which of those two numbers can be trusted given that `k6/ws` inflates frames before the script sees them."
>
> Check: the `permessage-deflate negotiated` counter rises above 0 on `:8090` while the `json_deflate` bytes per frame still equals the plain `json` row.

## Build, run, observe

```bash
cd examples/part5-performance
./verify.sh
```

`verify.sh` brings up both stacks, replays the fixture over the JSON and Protobuf encodings negotiated through `Sec-WebSocket-Protocol`, and prints `PASS` once the decoded fields match across encodings and the Protobuf frame is smaller on both stacks (Quarkus on `:8090`, Python on `:8091`, Python HTTP health on `:8092`).

Run the gated smoke check and the local benchmark with k6 2.3.0:

```bash
docker compose up --build -d quarkus python

K6_WS_URL="ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
  k6 run k6/smoke.js

K6_WS_URL="ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
PART5_BENCH_VUS=2 PART5_BENCH_DURATION=8s \
  k6 run k6/benchmark.js
```

Point `K6_WS_URL` at `:8091` for the Python stack. Use `PART5_BENCH_VUS` and `PART5_BENCH_DURATION`, not `K6_VUS` or `K6_DURATION`: k6 reserves the latter, and setting them discards the script's scenarios. Let the container settle after startup and leave idle time between back-to-back runs so `TIME_WAIT` sockets drain. To send the metrics to the LGTM stack, add k6's OpenTelemetry output:

```bash
K6_OTEL_GRPC_EXPORTER_INSECURE=true K6_OTEL_GRPC_EXPORTER_ENDPOINT=localhost:4317 \
  k6 run -o opentelemetry k6/benchmark.js
```

Experiments:

- Run `benchmark.js` twice back to back with no pause: the connect success rate drops as `TIME_WAIT` sockets exhaust the port range, while bytes per frame stay the same.
- Set `K6_VUS` in the environment: k6 logs that env-level configuration overrode the scenarios and runs a single default scenario instead of `json`, `protobuf` and `json_deflate`.

## For deeper coverage

- Pekka Enberg, *Latency: Reduce delay in software systems* (Manning, 2025): the systems-level latency-versus-throughput tradeoffs behind the batching-adds-latency trade.
- Martin Kleppmann & Chris Riccomini, *Designing Data-Intensive Applications, Second Edition* (O'Reilly, 2026): bounded queues and backpressure as a throughput ceiling, the same shape as the outbound queue that bounds every lever.
- *Cloud Native Design Patterns*, "Stream Processing" chapter: batching and coalescing tradeoffs for a continuously-pushed feed.
- *Cloud Native Design Patterns*, "Caching Patterns" chapter: the same amortize-a-fixed-cost-across-more-work reasoning that applies to frame batching.
- RFC 7692: permessage-deflate, the compression extension.
