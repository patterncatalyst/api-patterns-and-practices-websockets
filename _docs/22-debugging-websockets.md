---
title: "Debugging WebSockets"
order: 22
part: "Testing, Debugging & Observability"
description: "Which tool taps which layer of a WebSocket connection, how to read close codes, and a symptom-to-tool path."
duration: "17 min read"
---

## Learning objectives

By the end of this chapter you can:

- Pick the cheapest tool that taps the layer a symptom points to: `curl --include` or DevTools for the handshake, DevTools' Frames tab or `websocat -t` and `-b` for frame content, `tcpdump` or Wireshark for the raw TCP stream.
- Read a close code that `websocat` can't expose, using a Python probe's `ws.close_code`.
- Interpret the close-code taxonomy (1008, 4400, 4290, 4408, 1011, 1001, 1006) and explain why 1006 is never sent on the wire.
- Recognize `tcpdump`'s blind spot on `wss://` traffic and where the browser's Network tab stays useful.
- Follow a symptom-to-tool path from "never upgrades" through "dies under sustained load", pivoting to a server's trace-id log line when a close code can't explain the failure.

## Why this matters

When something breaks and no one wrote an assertion for it, the question is which tool shows the layer where it broke. A WebSocket connection has no single place that surfaces that, the way an HTTP response's status line does. The upgrade handshake, the data frames and the close each live at a different point in the connection's life, and a tool built for one is often blind to the other two. `websocat`, the scripted workhorse here, can't reliably observe close codes, which is why `examples/part4-connection/verify.sh` carries a second, purpose-built tool for that one job.

| Tool | Taps | Sees | Blind to |
|---|---|---|---|
| `curl --include`, DevTools Network tab | Handshake | The `101` and every header | Frames, close codes (curl) |
| DevTools Frames tab, `websocat -t` / `-b` | Data frames | Frame content, opcode, direction | Close codes (`websocat`) |
| Python `websockets` probe | Close | `ws.close_code`, frame count | Handshake headers |
| `tcpdump`, Wireshark | TCP | Packets, resets, a missing `101` | Content on `wss://` |
| Server trace-id log line | Server side | Why the server stopped | Nothing from the client's view |

## The handshake: curl --include and the Network tab

The handshake is plain HTTP until the `101` arrives: one `GET` with `Upgrade`, `Connection`, `Sec-WebSocket-Key` and `Sec-WebSocket-Version` headers, answered with `101 Switching Protocols` and a `Sec-WebSocket-Accept` header derived from the key. `curl --include` sends the Upgrade headers by hand and prints the status line and every header. Then it stops being useful, because it reads one HTTP response and doesn't know the connection is now framed.

That stopping behavior is diagnostic. Against a working endpoint, `curl` prints `101` and `Sec-WebSocket-Accept` and then sits there. Against a missing path, a server that isn't listening, or a reverse proxy that stripped `Connection: Upgrade`, it prints a `404`, a `200` or a `426 Upgrade Required` and exits immediately. If `curl` hangs, the upgrade is proceeding. If it exits clean with a normal status, something never agreed to switch protocols.

The browser's Network tab, filtered to `WS`, shows the same request and response pair plus the negotiated `Sec-WebSocket-Protocol`. It also keeps the connection's later history attached to the handshake: the Frames tab and the connection status, including the close code once it ends. Use `curl --include` from a terminal, a CI log or a server with no browser in front of it. Use DevTools when the broken connection is already open in a tab.

## The frame inspector: text and binary

After the handshake, every byte belongs to a frame tagged with an opcode: text (`0x1`), binary (`0x2`) or one of three control types. DevTools' Frames tab (sometimes labeled Messages) lists each frame sent or received with a text or binary icon and a direction arrow. It pretty-prints a text frame as JSON and shows a binary frame as a hex and ASCII split.

`websocat` answers the same question from a terminal. The `ws_first_frame` helper in `examples/_lib/lib.sh` runs `websocat $WEBSOCAT_OPTS -1 -n -t "$url"`: `-1` reads exactly one message, `-n` sends nothing, and `-t` treats the stream as text. The performance example adds `--protocol` to negotiate a subprotocol and swaps `-t` for `-b` to read a Protobuf frame. The flag matters: `-t` on a binary frame or `-b` on a text one corrupts what's printed. Offering `handling-events.v1+json` returns JSON text frames and `handling-events.v1+protobuf` returns binary frames, so a client that assumes the wrong one decodes garbage even though the server did what it was asked.

{% include excalidraw.html file="22-lifecycle-taps" alt="Three bands show where each tool taps a connection. In the handshake, a client GET with Upgrade headers meets a 101 response, inspected with curl --include or the DevTools Network tab. In the data frames, text (opcode 0x1) and binary (opcode 0x2) frames are inspected with the DevTools Frames tab or websocat -t and -b. At the close, a close frame or an abrupt reset is read by the Python ws_close_probe, which sees ws.close_code where websocat cannot. tcpdump and Wireshark tap underneath all three at the TCP layer." caption="Figure 22.1: where each tool taps a live connection, from the handshake through the data frames to the close." %}

## websocat's blind spot: the close code

Every frame-reading helper in `lib.sh` (`ws_first_frame`, `ws_frames_n`, `wait_for_ws`) is built on `websocat`, for good reason: it's a single self-downloading binary with no language runtime, and its flags cover the "connect, read N frames, done" shape. It doesn't give a script a reliable way to read the numeric close code a server sent. For the error taxonomy and the backpressure policy, which close with a specific code (4400 malformed frame, 4290 slow consumer), that's disqualifying: a harness that can't read the close code can't assert on what those features exist to produce.

`examples/part4-connection/verify.sh` solves it with a small Python probe, run through an ephemeral `uv run --with websockets` environment so nothing needs installing:

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
        # websockets 17.x raises ConnectionClosed(OK|Error) out of the
        # async-for loop itself once the server closes; catch it here so
        # ws.close_code is still readable afterward, rather than letting it
        # propagate and lose every frame already received.
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

The native `websockets` connection object exposes `ws.close_code` the moment the connection ends, populated from the close frame the library parsed off the wire. `websocat`'s command line has no equivalent. When the default tool can't observe what an assertion needs, the fix is a different tool built on a library that exposes the data, not harder flags on the same one. The same reasoning applies to a silent peer, which `websocat` and `websockets` can't produce because both answer pings automatically.

## tcpdump and Wireshark: the layer underneath

`curl` and `websocat` understand the handshake and framing. `tcpdump` and Wireshark capture raw TCP packets, which is what makes them useful for "did a frame cross the wire at all, and if not, where did it stop." Wireshark's WebSocket dissector recognizes the `Upgrade: websocket` request, and after the matching `101` it decodes later payload on that stream as frames, showing the FIN, opcode, mask and length. A masked client frame appears already unmasked.

This is also where proxy misconfiguration becomes provable. An Upgrade request whose `Connection: Upgrade` header a reverse proxy stripped looks like an ordinary HTTP/1.1 request out one side and a `200` back the other, with no `101` anywhere in the capture. That confirms the proxy before anyone touches the application. It also sees what neither WebSocket-aware tool can: a TCP `RST` mid-handshake, a `SYN` with no reply, a connection that hangs before any HTTP starts.

It can do nothing about `wss://`. TLS encrypts everything past its own handshake, so the capture shows packet sizes, timing and the SNI field, but the Upgrade request, the opcodes and every payload byte are opaque without the server's private key or an `SSLKEYLOGFILE` decrypt (Wireshark's general TLS mechanism, not a WebSocket feature). Production traffic is `wss://` only, so `tcpdump` is the plaintext local-dev tool. The browser decrypts its own traffic before DevTools sees it, so the Network tab's view of a `wss://` connection matches its view of `ws://`.

## Close codes: the protocol's built-in error channel

RFC 6455 gives a closing connection one structured signal, a 16-bit close code. The examples use two bands: the RFC's `1000` to `2999` range with its own meanings, and the `4000` to `4999` private-use range for codes this application defines. The Quarkus `CloseCodes.java` and its Python sibling use the same numbers:

| Code | Meaning | Where it fires |
|---|---|---|
| `1008` | Auth failure | Any JWT problem: missing, malformed, bad signature, expired |
| `4400` | Malformed client frame | The channel accepts no client-to-server messages, so any frame is a protocol error |
| `4290` | Slow consumer / backpressure | The outbound backpressure guard's `CLOSE` policy |
| `4408` | Liveness timeout (Quarkus) | `HeartbeatLivenessSweep` closing a peer that stopped answering pings |
| `1011` | Unexpected server error, or liveness timeout (Python) | An unmapped exception on either stack; also the `websockets` library's own keepalive-failure code |
| `1001` | Going away | Graceful server shutdown; every open connection gets this one |
| `1006` | Abnormal closure | Never sent on the wire; synthesized locally when no close frame arrived |

A code in the `4000`s is this application's convention and needs its table to decode. A code starting with `1` is an RFC 6455 standard that a generic client library may already interpret.

`1006` needs the most care. RFC 6455 forbids placing it in a close frame; it's a value a client API may report locally when the connection ended with no close handshake. A killed server process, a network partition, a pulled cable, or Vert.x forcibly tearing down a connection after its roughly 10-second closing-handshake grace expires on a dead peer that never acknowledged the close: all produce `1006` at the client, and none produce a close frame `tcpdump` could show. In this one case the code says only "something ended badly", and the investigation moves to server logs.

## Server logs: the trace-id bridge

Every tool above observes from outside. The observability example adds a structured log line the server writes, in the same shape on both stacks, when a connection opens:

```text
otel.trace_id=<32-hex-trace-id> span=ws.handling-events.connection bookingId=<bookingId> instance=part6-observability-<stack>
```

A close code answers what happened to the connection. The trace id answers what the server was doing while it happened: it keys into the server's logs, metrics and, once the pipeline is wired, a queryable distributed trace. A session that only asks the first question stalls at `1006`.

## A debugging path: symptom to tool

The cheapest tool that taps the right layer beats a more powerful one that doesn't. `curl --include` answers "did the handshake happen" in one request, so firing up Wireshark for that is wasted effort.

| Symptom | First tool | Leading suspect |
|---|---|---|
| Never upgrades, no `101` | `curl --include` the Upgrade request | A proxy stripped `Connection: Upgrade`, or a wrong path or headers |
| `101`, then silence or a hang | DevTools Frames tab, or `websocat -t` on the same URL | A post-upgrade rejection: the auth gate closes after a successful `101`, which a client that only checked for `101` misses |
| A frame arrives but won't parse | The binary or text icon, or `websocat -b \| xxd` | Opcode mismatch: a `+json` client reading `+protobuf` binary frames as text, or the reverse |
| Drops with no obvious reason | `ws_close_probe` or the browser's `onclose`, checked against the table | `1006` means go straight to server logs for the trace id |
| Fine, then dies under sustained load | `tcpdump` or Wireshark plus server logs over the same window | Backpressure (4290) or the liveness sweep (4408 or 1011) firing once enough volume or silence accumulates |

{% include excalidraw.html file="22-symptom-to-tool" alt="A root box asking what symptom a live connection shows fans out to five columns, each pairing a symptom with its first tool and likely cause: no 101 (curl --include, proxy), 101 then silence (Frames tab or websocat -t, post-upgrade rejection), unparseable frame (binary or text icon, opcode mismatch), drop with no reason (ws_close_probe and trace-id logs, close code), and failure under sustained load (tcpdump plus server logs, backpressure or liveness sweep)." caption="Figure 22.2: five symptoms, five first tools: start at the cheapest tool that taps the layer the symptom points to." %}

> **Decision**
>
> Reach for the cheapest tool that taps the layer the symptom points to. `curl --include` or the Network tab for the handshake, the Frames tab or `websocat -t` and `-b` for frame content, `tcpdump` for what never reached HTTP (blind on `wss://`), and a `websockets` probe for the close code that `websocat` can't read. Treat `1006` as "no close frame arrived" and pivot to the server's `otel.trace_id` log line.

> **🤖 Explore with your agent**
>
> "Using `ws_close_probe` from `examples/part4-connection/verify.sh`, connect to the Quarkus (`:8080`) and Python (`:8081`) servers with a valid `?token=` minted the way the script mints `VALID_TOKEN`, send a malformed client frame such as `{"not":"valid"}`, and report the close code each returns. Then tell me, for each of 4400, 4290, 4408, 1011 and 1006, whether a `tcpdump` capture of a `ws://` connection would show that code on the wire, and what I should check next if the probe reports 1006."
>
> Check: both stacks report `"close_code": 4400` with `"envelope_bad_request": true`, and the reply says 1006 never appears on the wire and points to the server's trace-id log line.

## Build, run, observe

`verify.sh` in `examples/part4-connection` runs the probe against both stacks. A real run (2026-10-19) printed:

```text
lib.sh: quarkus error-taxonomy probe result: {"frames": 4, "envelope_bad_request": true, "close_code": 4400}
lib.sh: python error-taxonomy probe result: {"frames": 4, "envelope_bad_request": true, "close_code": 4400}
lib.sh: quarkus backpressure probe result: {"frames": 0, "envelope_bad_request": false, "close_code": 4290}
lib.sh: python backpressure probe result: {"frames": 0, "envelope_bad_request": false, "close_code": 4290}
lib.sh: quarkus heartbeat probe result: CLOSED:15.1
lib.sh: python heartbeat probe result: CLOSED:5.0
```

The error run's 4 frames are the three fixture events plus the `BAD_REQUEST` envelope; the probe counts every frame before the close. The backpressure run shows 0 frames because the connection closed with 4290 before the fixture replay sent anything. Python's heartbeat probe closed in 5.0 seconds because `ping_timeout` alone detects the silent peer. Quarkus took 15.1 seconds: the forced 5-second `liveness-timeout`, plus sweep latency, plus Vert.x's closing-handshake grace for a peer that never answers.

Inspect a handshake against the observability example's Quarkus app on `:8080`:

```bash
curl --include --http1.1 --max-time 2 \
  -H "Upgrade: websocket" \
  -H "Connection: Upgrade" \
  -H "Sec-WebSocket-Key: PWzgJfnx8Z5GlgD+ebqsBA==" \
  -H "Sec-WebSocket-Version: 13" \
  "http://127.0.0.1:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events"
```

```text
HTTP/1.1 101 Switching Protocols
upgrade: websocket
connection: upgrade
sec-websocket-accept: 4Bhg3KQgaM1YwJmK7cF8GRCvLyY=
```

Past that response `curl` keeps printing raw bytes of the upgraded stream: frame-header bytes mixed with readable JSON, because it doesn't know the stream is framed.

Read the same event in both encodings from the performance example's Quarkus app on `:8090` with `websocat --protocol <name> -1 -n -b | xxd`:

{% raw %}
```text
# +json (247 bytes): human-readable field names, quoted strings
00000000: 7b22 6576 656e 7449 6422 3a22 6576 745f  {"eventId":"evt_
00000010: 3031 485a 5933 4d31 5638 5834 4437 5136  01HZY3M1V8X4D7Q6
00000020: 4232 4e39 4330 5435 4538 222c 2262 6f6f  B2N9C0T5E8","boo

# +protobuf (149 bytes): tag/length/value, no field names on the wire
00000000: 0a1e 6576 745f 3031 485a 5933 4d31 5638  ..evt_01HZY3M1V8
00000010: 5834 4437 5136 4232 4e39 4330 5435 4538  X4D7Q6B2N9C0T5E8
00000020: 121e 626b 675f 3031 485a 5933 4b58 3751  ..bkg_01HZY3KX7Q
```
{% endraw %}

The Protobuf frame starts `0a 1e`: field 1 (`eventId`), wire type 2 (length-delimited), length 30, then the raw UTF-8 bytes with no key name. The JSON frame spends its first 16 bytes on `{"eventId":"` before any data appears. The 247 and 149 byte totals are a 39.7% reduction.

The trace-id lines the observability example writes on connection open, captured with `docker compose logs` after one connection to each stack:

```text
part6-observability-quarkus | otel.trace_id=d38fedb8fb9a461e72a0e7dc4a0dc96c span=ws.handling-events.connection bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A instance=part6-observability-quarkus
part6-observability-python  | otel.trace_id=feec2f834edf9f92f6e51fb43b2d7597 span=ws.handling-events.connection bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A instance=part6-observability-python
```

Scraping the Quarkus `/q/metrics` right after shows the same trace id on the counter the connection incremented, so the id in the log line, the metric exemplar and the trace in Tempo are one key:

```text
handling_events_delivered_total 6.0 # {span_id="2c4657118050d7fe",trace_id="d38fedb8fb9a461e72a0e7dc4a0dc96c"} 1.0 1792423019.334
```

Experiments:

- Point the `curl` command at a path that doesn't exist: it exits immediately with a non-101 status instead of hanging.
- Read a Protobuf connection with `-t` instead of `-b`: the printed bytes are corrupted.

## For deeper coverage

- Charity Majors, Liz Fong-Jones & George Miranda, *Observability Engineering* (O'Reilly, 2022): diagnosing a live system from the outside, the same instinct behind picking a tool per layer.
- *Cloud Native Design Patterns*, "Observability" chapter: the broader observability toolkit the client-side tools sit alongside.
- *Cloud Native Design Patterns*, "Failure Modes" chapter: categorizing how a connection fails, the same shape as a close-code taxonomy.
- RFC 6455: the close-code ranges and frame format that these tools read off the wire.
- [Chrome DevTools: Network panel](https://developer.chrome.com/docs/devtools/network/) and [MDN: WebSockets API](https://developer.mozilla.org/en-US/docs/Web/API/WebSockets_API): the handshake and frame inspection a browser's DevTools expose for a live WebSocket connection.
