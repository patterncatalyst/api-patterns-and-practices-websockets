---
title: "Debugging WebSockets"
order: 22
part: "Testing, Debugging & Observability"
description: "Diagnosing a connection that drops without warning, hangs, or never upgrades."
duration: "17 min read"
---

Chapter 21 built automated assertions against this book's running examples — `assert_eq`, `schema_validate`, `ws_close_probe`, all of it scripted so `verify.sh` can print `PASS` with nobody watching. Debugging is the opposite situation: something is wrong, nobody wrote an assertion for it, and the real question isn't "what's broken" but "which tool actually shows me the layer where it broke." A WebSocket connection has no single place that surfaces that information the way an HTTP response's status line does — the upgrade handshake, the data frames, and the close each live at a different point in the connection's life, and a tool built for one of those points is often blind to the other two. `examples/_lib/lib.sh`'s own comments make this explicit for one tool in particular: `websocat` is this project's workhorse for scripted probing, and its docstring-level comments say outright that it cannot observe close codes reliably — which is why `examples/part4-connection/verify.sh` reaches for a second, purpose-built tool for exactly that one job. This chapter is a tour of five tools — `curl`, browser DevTools, `websocat`, `tcpdump`/Wireshark, and the small Python probe that exists because of that one blind spot — run against real traffic from this book's own Part 4, 5, and 6 examples, organized around where each tool taps the connection rather than which one is "best."

## The handshake: curl --include and the DevTools Network tab

Chapter 3 named the upgrade handshake as plain HTTP up until the `101` arrives — one `GET` with `Upgrade`, `Connection`, `Sec-WebSocket-Key`, and `Sec-WebSocket-Version` headers, answered with `101 Switching Protocols` and a `Sec-WebSocket-Accept` header derived from the key. Because that exchange is ordinary HTTP/1.1 up to the moment it isn't, the cheapest tool for inspecting it is the cheapest tool for inspecting any HTTP exchange: `curl --include`. It sends the Upgrade headers by hand, prints the full response — status line, every header, in order — and then naturally stops, because its own job description ends at "read one HTTP response" and a `101` with no `Content-Length` and a connection that never closes isn't something `curl` knows how to continue past. That stopping point is itself diagnostic: a `curl --include` against a working endpoint prints `101` and a `Sec-WebSocket-Accept` header and then sits there; a `curl --include` against a path that doesn't exist, a server that isn't listening, or a reverse proxy that stripped the `Connection: Upgrade` header prints something else entirely — a `404`, a `200`, a `426 Upgrade Required` — before `curl` exits immediately on its own, no manual Ctrl-C required. That difference in exit behavior is often the fastest signal available: if `curl` hangs, the upgrade is proceeding; if it exits clean with a normal status code, the server or something in front of it never agreed to switch protocols at all.

A browser's DevTools Network tab answers the identical question with less typing and more context, at the cost of needing an actual page open. Filtering the Network panel to `WS` shows every WebSocket connection the page opened, and clicking one surfaces a Headers tab with the same request/response pair `curl --include` would print — request `Upgrade`/`Connection`/`Sec-WebSocket-Key`/`Sec-WebSocket-Version`, response `101`/`Sec-WebSocket-Accept`, plus whatever `Sec-WebSocket-Protocol` was negotiated for Part 5's JSON-vs-Protobuf channel. The advantage over `curl` isn't the data — it's identical — it's that DevTools keeps the connection's full subsequent history attached to that same handshake: the Frames tab covered next, the connection's current status (open, closed, the close code once it ends), all in one place a developer debugging a page already has open. `curl --include` is the tool to reach for from a terminal, a CI log, or a server that isn't fronted by a browser at all; DevTools is the tool to reach for when the broken connection is already sitting in front of you in a tab.

## The frame inspector: text vs binary, in DevTools and on the command line

Once the handshake completes, Chapter 3's frame anatomy takes over — every subsequent byte belongs to a frame, tagged with an opcode that says whether it's text (`0x1`), binary (`0x2`), or one of the three control types. DevTools' Frames tab (sometimes labeled Messages, depending on browser) lists every frame a connection has sent or received, each one tagged with a small icon distinguishing text from binary and an arrow showing direction, and clicking a frame shows its decoded content — pretty-printed JSON for a text frame, a hex/ASCII split view for binary. This is the tool for the question "is my server actually sending what I think it's sending, frame by frame, in order" — not whether the connection exists, but what's actually riding on it.

`websocat`, this project's command-line equivalent, answers the same question from a terminal or a script. `examples/_lib/lib.sh`'s `ws_first_frame` helper calls `websocat $WEBSOCAT_OPTS -1 -n -t "$url"` — `-1` for exactly one message, `-n` to send nothing of its own, `-t` to treat the stream as text — and part5-performance's `verify.sh` uses the identical flag with `--protocol` added to negotiate a specific subprotocol, then swaps `-t` for `-b` (binary) when reading a Protobuf frame instead of a JSON one. The distinction matters past a flag choice: a server that returns different content depending on which subprotocol a client offers needs a tool that can read either representation faithfully, and `-t` on a binary frame (or `-b` on a text one) would corrupt what gets printed. Part 5's negotiation table makes the opcode choice an observable contract, not an implementation detail — offering `handling-events.v1+json` gets JSON text frames back, `handling-events.v1+protobuf` gets Protobuf binary frames, and a client that assumes the wrong one before reading will decode garbage even though the server did exactly what it was asked.

{% include excalidraw.html file="22-lifecycle-taps" alt="Three horizontal bands top to bottom. HANDSHAKE band: CLIENT box (GET plus Upgrade, Connection, Sec-WebSocket-Key, Version 13 headers) arrows to a SERVER box (101 Switching Protocols plus Sec-WebSocket-Accept), which arrows to a TAP box reading curl --include slash browser DevTools Network tab -- see the 101 plus every header. DATA FRAMES band: a TEXT frame box (opcode 0x1, JSON) and a BINARY frame box (opcode 0x2, Protobuf) both arrow, labeled inspect, to a TAP box reading DevTools Frames tab (per connection) slash websocat -t (text) or -b (binary). CLOSE band: a CLOSE frame box (code plus optional reason, or: peer vanishes, no frame) arrows via close handshake to a TCP teardown box (two-way close handshake, or abrupt reset to 1006), which arrows via an amber arrow labeled the blind spot to a TAP box reading python ws_close_probe (websockets lib) reads ws.close_code directly -- websocat CANNOT see this. A caption below reads: tcpdump/Wireshark taps underneath all three phases at the TCP layer -- full visibility on ws, only encrypted length and timing on wss." caption="Figure 22.1 — where each tool taps a live connection: the handshake, the data frames, and the close, plus the TCP layer every one of them sits on top of." %}

## websocat's blind spot: why the close code needs a different tool

Every helper in `examples/_lib/lib.sh` that reads frames — `ws_first_frame`, `ws_frames_n`, `wait_for_ws` — is built on `websocat`, and for good reason: it's a single self-downloading binary (`ensure_websocat` pulls a pinned release if nothing's on `PATH`), it needs no language runtime, and its `-1`/`-n`/`-t`/`-b` flags cover the common "connect, read N frames, done" shape this project's harnesses need over and over. What it doesn't expose is a reliable way to read the numeric close code a server sent — the CLI's own documented behavior gives a script no clean path to the two bytes RFC 6455 reserves for exactly that purpose. For reading frame content, that's not a problem `examples/part4-connection` needs to solve at all. For Chapter 13's error taxonomy and Chapter 12's backpressure policy — both of which close a connection with a specific numeric code the whole point is to distinguish (`4400` malformed frame, `4290` slow consumer) — it's disqualifying: a test harness that can't read the close code can't assert on the one piece of information those chapters' features exist to produce.

`examples/part4-connection/verify.sh` solves this with a small, purpose-built Python probe, `ws_close_probe`, run through an ephemeral `uv run --with websockets` environment so it needs no pre-installed dependency:

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

The difference from `websocat` isn't effort — it's API surface. The native `websockets` library's connection object exposes `ws.close_code` as a plain Python attribute the instant the connection ends, populated from the close frame the library parsed off the wire itself; there's no equivalent read available through `websocat`'s command-line interface, only through a library that was built with that attribute as a first-class part of its object model. This is the same reasoning Chapter 14's `raw_silent_client_close_wait` probe used for a different gap: when the tool everyone defaults to can't observe the one thing a test needs to assert on, the fix isn't harder flags on the same tool, it's a different tool built on a library that actually exposes the data.

## tcpdump and Wireshark: the layer underneath everything else

Both `curl` and `websocat` are WebSocket-aware — they understand the handshake and the framing and present a client-level view. `tcpdump` and Wireshark don't; they capture raw TCP packets and leave interpretation to whoever's reading the capture, which is exactly what makes them useful when the question is "did a frame cross the wire at all, and if not, where did it stop." Wireshark's WebSocket dissector recognizes the handshake's `Upgrade: websocket` header and, once it sees the matching `101`, starts decoding subsequent TCP payload on that stream as WebSocket frames automatically — the same FIN/opcode/MASK/length breakdown Chapter 3 worked through by hand on a captured frame, done for every frame in the capture without re-deriving it. A masked client frame shows up in Wireshark's frame detail pane already unmasked into readable payload, the same XOR-by-mask-key arithmetic Chapter 3's "On the wire" section did manually, just automated.

This is also the layer where Chapter 3's proxy and load-balancer warnings become something you can actually confirm instead of suspect. An Upgrade request that a misconfigured nginx reverse proxy strips `Connection: Upgrade` from looks, in a packet capture, like an ordinary HTTP/1.1 request going out one side and an ordinary `200` coming back the other — no `101` anywhere in the capture, which confirms the proxy configuration is the problem before anyone touches the application code behind it. The one thing `tcpdump`/Wireshark sees that `curl` and `websocat` don't is a connection that never got a chance to send an HTTP response at all: a TCP `RST` arriving mid-handshake, a `SYN` with no reply, a connection that hangs at the TCP level before any HTTP ever starts — failures below the layer either WebSocket-aware tool can describe.

The one thing this layer cannot do anything about is `wss://`. TLS encrypts everything past the TLS handshake itself, and from `tcpdump`'s point of view a `wss://` connection is ciphertext: packet sizes, timing, and the TLS handshake's own SNI field are visible, but the HTTP Upgrade request, the frame opcodes, and every byte of payload are opaque without either the server's private key or a `SSLKEYLOGFILE`-based decrypt (the same mechanism Wireshark supports for decrypting any TLS session, not a WebSocket-specific feature). Since this book's examples run `ws://` locally and the Decision callout at the end of Chapter 3 commits production traffic to `wss://` only, `tcpdump` is the plaintext-local-dev tool in this lineup — blind on anything running with TLS in front of it, which is also exactly when a browser's DevTools Network tab stays useful: the browser decrypts its own traffic before DevTools ever sees it, so the Network tab's view of a `wss://` connection is identical to its view of a `ws://` one.

## Close codes: the protocol's only built-in error channel, read correctly

Chapter 13 built the taxonomy this chapter now uses from the outside: RFC 6455 gives a closing connection exactly one structured signal beyond "it's closing," a 16-bit close code, and this book's examples place every code they use into one of two bands — the RFC's own `1000`-`2999` range reused with the RFC's own meaning, or the `4000`-`4999` private-use range for codes this application invented. `CloseCodes.java` and its Python sibling agree on the same numbers:

| Code | Meaning | Where it fires |
|---|---|---|
| `1008` | Auth failure | Any JWT problem — missing, malformed, bad signature, expired (Ch17) |
| `4400` | Malformed client frame | This channel accepts no client-to-server messages; any frame is a protocol error (Ch13) |
| `4290` | Slow consumer / backpressure | The outbound backpressure guard's `CLOSE` policy (Ch12) |
| `4408` | Liveness timeout (Quarkus) | `HeartbeatLivenessSweep` closing a peer that stopped answering pings (Ch14) |
| `1011` | Unexpected server error, or liveness timeout (Python) | An unmapped exception on either stack; also the `websockets` library's own hardcoded keepalive-failure code |
| `1001` | Going away | Graceful server shutdown — every open connection gets this one |
| `1006` | Abnormal closure | *Never sent on the wire* — synthesized locally when no close frame arrived at all |

Once a close code is in hand — from `ws_close_probe`, from a browser's `WebSocket.onclose` event handler, or from Wireshark's decoded close frame — this table is the thing it gets checked against, and the checking itself carries information a bare number doesn't: a code in the `4000`s is this application's own convention and needs this chapter or the README's table to decode, while a code starting with `1` is an RFC 6455 standard a generic client library might already know how to interpret without any project-specific documentation at all.

`1006` is the row that needs the most care, because it's structurally different from every other entry: RFC 6455 forbids a conforming implementation from ever placing `1006` in an actual close frame on the wire — it exists purely as a value a client-side API is permitted to report locally when the underlying connection ends with no close handshake at all. A killed server process, a network partition, a cable pulled mid-stream, or (as Chapter 14 showed concretely) Vert.x forcibly tearing down a connection after its ~10-second closing-handshake grace expires on a peer that was proven dead but never acknowledged its own close — all of these produce `1006` at the observing client, and none of them produce anything that `tcpdump` would show as a close frame on the wire, because there wasn't one. This is the one case in the whole taxonomy where the close code itself tells a debugger nothing beyond "something ended badly," and the investigation has to move to the next tool instead: server logs, which is where this chapter goes next.

## Server logs: the trace-id bridge to Chapter 23

Every other tool in this chapter observes the connection from outside — a client's own view of headers, frames, and close codes. `examples/part6-observability` adds the one source of truth that lives on the other side of the wire: a structured log line the server itself writes, in the identical shape on both stacks, the moment a connection opens:

```text
otel.trace_id=<32-hex-trace-id> span=ws.handling-events.connection bookingId=<bookingId> instance=part6-observability-<stack>
```

This line is the bridge between "the close code told me WHAT happened" and "here's WHERE in the server's own execution that decision got made" — a `1006` tells a debugger nothing about why the server stopped responding, but the trace id attached to that same connection's log line is a key into the server's own structured logs, metrics, and (once Chapter 23 wires the full pipeline) a queryable distributed trace, none of which any client-side tool in this chapter can see at all. A close code answers "what happened to this connection"; a trace id answers "what was the server doing while it happened," and a debugging session that only ever asks the first question stalls out exactly at `1006`, where the answer from the wire alone is "I don't know."

## A debugging decision path: symptom to tool

Five tools, five layers, and the practical question is which one to reach for first given only a symptom. The cheapest tool that taps the right layer beats a more powerful one that doesn't: `curl --include` answers "did the handshake even happen" in one request and an immediate exit code, which is a wasted step to skip in favor of firing up Wireshark for the same question. Five symptoms cover most of what shows up in practice:

- **Never upgrades, no `101` at all** — `curl --include` the Upgrade request first. If the response isn't `101`, a proxy between the client and the server is the leading suspect (stripped `Connection: Upgrade`, or the path/headers are wrong) — Chapter 3's proxy section names the exact misconfiguration this usually is.
- **`101` arrives, then silence or a hang** — DevTools' Frames tab, or `websocat -t` against the same URL from a terminal. If no frame ever lands, the next suspect is a post-upgrade rejection the handshake itself couldn't show — Chapter 17's auth gate closes after a successful `101`, so a client that only checked for `101` and stopped looking will miss it.
- **A frame arrives but won't parse** — the same tab's binary/text icon, or `websocat -b | xxd` from a terminal. This is almost always an opcode mismatch: a client built for `+json` reading a `+protobuf` connection's binary frames as text, or the reverse, exactly the negotiation Part 5 makes explicit via `Sec-WebSocket-Protocol`.
- **The connection drops with no obvious reason** — `ws_close_probe` (or a browser's `onclose` handler) for the close code, cross-referenced against this chapter's table; `1006` specifically means pivot straight to server logs for the trace id, because the code itself has nothing more to say.
- **Works fine, then dies under sustained load** — `tcpdump`/Wireshark on the raw TCP stream alongside server logs over the same window, correlating close timing against the trace-id lines. This is the shape Chapter 12's backpressure guard and Chapter 14's liveness sweep both produce: a condition that only trips after enough volume or enough silence has accumulated, which neither a single `curl` request nor a single frame read will ever catch in isolation.

{% include excalidraw.html file="22-symptom-to-tool" alt="A root box at top reads Symptom on a live connection? with five arrows fanning down to five columns. Column 1: Never upgrades (no 101 at all) -- curl --include the Upgrade request -- Proxy stripped Connection: Upgrade, or wrong path/headers. Column 2: 101 arrives, then silence or hang -- DevTools Frames tab or websocat -t -- Auth gate rejected post-upgrade (Ch17), or subprotocol mismatch. Column 3: Frame arrives, wrong shape or won't parse -- DevTools binary/text icon, websocat -b piped to xxd -- Opcode mismatch, binary negotiated but client expects text (Ch19). Column 4: Connection drops, no obvious reason -- python ws_close_probe plus server trace-id logs -- close_code says WHY: 4400, 4290, 4408, 1008; 1006 means no code arrived. Column 5: Works, then dies after sustained load -- tcpdump/Wireshark on TCP plus server logs over time -- Backpressure (4290) or liveness sweep (4408/1011) firing under pressure. A caption below reads: reach for the cheapest tool that taps the right layer first -- curl before websocat, websocat before tcpdump." caption="Figure 22.2 — five symptoms, five first tools: start at the cheapest tool that taps the layer the symptom points to." %}

## On the wire

Every number and log line in this section came off this book's own running examples, captured live rather than reconstructed from documentation.

A real `101` upgrade, `curl --include` against `examples/part6-observability`'s Quarkus app on `localhost:8080`:

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

`4Bhg3KQgaM1YwJmK7cF8GRCvLyY=` is the real SHA-1/GUID derivation Chapter 3 walked through by hand, computed here by the live Quarkus server against the random key this request sent — not the RFC's published test vector, a fresh key generated for this capture. Past that response, `curl` keeps reading raw bytes off the now-upgraded connection, and what comes through looks exactly like Chapter 3 predicted: frame-header bytes mixed in with readable JSON, because `curl`'s job stopped at the one HTTP response and it has no idea the rest of the stream is framed.

`examples/part4-connection/verify.sh`'s real run against both stacks, `ws_close_probe` output exactly as printed (2026-10-19):

```text
lib.sh: quarkus error-taxonomy probe result: {"frames": 4, "envelope_bad_request": true, "close_code": 4400}
lib.sh: python error-taxonomy probe result: {"frames": 4, "envelope_bad_request": true, "close_code": 4400}
lib.sh: quarkus backpressure probe result: {"frames": 0, "envelope_bad_request": false, "close_code": 4290}
lib.sh: python backpressure probe result: {"frames": 0, "envelope_bad_request": false, "close_code": 4290}
lib.sh: quarkus heartbeat probe result: CLOSED:15.1
lib.sh: python heartbeat probe result: CLOSED:5.0
```

The error-taxonomy run's `"frames": 4` is the 3-event fixture replay plus the `BAD_REQUEST` envelope — `ws_close_probe` counts every frame it receives before the close, not just the one that matters, which is exactly why the probe exists: `websocat` could show that same connection's text content, but not the `close_code: 4400` field this assertion actually checks. The backpressure run shows `"frames": 0` — the connection closed with `4290` before the fixture replay ever got a chance to send anything, the deterministic trip Chapter 12 built. The heartbeat timings are the measured gap Chapter 14 explains at length: Python's probe closed in 5.0 seconds because `ping_timeout` alone is the detector, while Quarkus took 15.1 seconds — the forced 5-second `liveness-timeout`, plus sweep latency, plus Vert.x's own closing-handshake grace waiting out an acknowledgment from a peer that was never going to answer.

Real frame bytes, JSON versus Protobuf, read with `websocat --protocol <name> -1 -n -b | xxd` against `examples/part5-performance`'s Quarkus app on `localhost:8090`:

{% raw %}
```text
# +json (247 bytes) — human-readable field names, quoted strings
00000000: 7b22 6576 656e 7449 6422 3a22 6576 745f  {"eventId":"evt_
00000010: 3031 485a 5933 4d31 5638 5834 4437 5136  01HZY3M1V8X4D7Q6
00000020: 4232 4e39 4330 5435 4538 222c 2262 6f6f  B2N9C0T5E8","boo

# +protobuf (149 bytes) — tag/length/value, no field names on the wire
00000000: 0a1e 6576 745f 3031 485a 5933 4d31 5638  ..evt_01HZY3M1V8
00000010: 5834 4437 5136 4232 4e39 4330 5435 4538  X4D7Q6B2N9C0T5E8
00000020: 121e 626b 675f 3031 485a 5933 4b58 3751  ..bkg_01HZY3KX7Q
```
{% endraw %}

The Protobuf dump's first two bytes, `0a 1e`, are a field tag and a length — field 1 (the generated `eventId` field), wire type 2 (length-delimited), length `0x1e` = 30 bytes — followed immediately by the field's raw UTF-8 bytes with no key name anywhere on the wire. The JSON dump spends its first 16 bytes on `{"eventId":"` before a single byte of actual data appears. `wc -c` against the same two captures measured `247` and `149` bytes respectively — a 39.7% reduction, matching part5-performance's committed measurement exactly, confirmed fresh rather than only cited from an earlier run.

And the trace-id log lines `examples/part6-observability` writes on connection open, captured from `docker compose logs` against both stacks after opening one connection to each:

```text
part6-observability-quarkus | otel.trace_id=d38fedb8fb9a461e72a0e7dc4a0dc96c span=ws.handling-events.connection bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A instance=part6-observability-quarkus
part6-observability-python  | otel.trace_id=feec2f834edf9f92f6e51fb43b2d7597 span=ws.handling-events.connection bookingId=bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A instance=part6-observability-python
```

Scraping the Quarkus app's own `/q/metrics` endpoint immediately after shows the same trace id attached to the counter the connection incremented:

```text
handling_events_delivered_total 6.0 # {span_id="2c4657118050d7fe",trace_id="d38fedb8fb9a461e72a0e7dc4a0dc96c"} 1.0 1792423019.334
```

That one trace id — `d38fedb8fb9a461e72a0e7dc4a0dc96c` — is present in the server's own log line and the server's own metrics exemplar for the identical connection; Chapter 23 is where this project wires the OTLP pipeline that turns the same id into a queryable trace in Tempo, instead of a string a debugger can only `grep` for by hand.

## Where this goes next

This chapter was a map of taps, not a map of fixes: five tools, five layers, and a rule for which one to reach for first given a symptom. `curl --include` and DevTools answer handshake questions in one request; DevTools' Frames tab and `websocat -t`/`-b` answer frame-content questions; `tcpdump`/Wireshark answer questions neither tool above can, at the cost of being blind on `wss://`; and `ws_close_probe` exists specifically because `websocat`'s one gap — the close code — is also the one piece of information Chapter 12's and Chapter 13's close-code taxonomy is built around. Chapter 23 picks up exactly where this chapter's last section left off: the trace-id log line is the thin end of a wedge this book has only used manually so far — `grep`ing a container's logs for one string — and Chapter 23 wires the OpenTelemetry pipeline that turns that same id into a distributed trace, queryable in Tempo, correlated automatically with every span a connection touched rather than hand-assembled from log lines across two services. Chapter 24's anti-patterns chapter revisits a few of this chapter's tools from the other direction — ways teams reach for the wrong one, or skip straight to the most expensive one, and what that costs in practice.

<div class="callout callout--safe"><p class="callout__title">Decision</p><p>No single tool observes a WebSocket connection end to end, because the connection itself has no single layer — reach for the cheapest tool that taps the layer a symptom points to, not the most powerful tool available. <code>curl --include</code> and a browser's DevTools Network tab answer handshake questions (did the <code>101</code> happen, what headers came back) in one request, before anything WebSocket-specific needs to run. DevTools' Frames tab and <code>websocat</code>'s <code>-t</code>/<code>-b</code> flags answer frame-content questions once the handshake succeeded. <code>tcpdump</code>/Wireshark answer questions neither of those can — a handshake that never got an HTTP response at all, a proxy silently mangling the Upgrade — but are blind on <code>wss://</code> past the TLS handshake, which is most of this book's traffic past a developer's own laptop. <code>websocat</code> cannot reliably read a close code, confirmed by its own documented behavior and the reason <code>examples/part4-connection/verify.sh</code> carries a small, purpose-built <code>ws_close_probe</code> using the native <code>websockets</code> library's <code>ws.close_code</code> attribute instead — real runs captured here closed with <code>4400</code>, <code>4290</code>, and (after real elapsed waits of 15.1s on Quarkus versus 5.0s on Python) a liveness-triggered close, exactly the three application conditions Chapters 12-14 built. <code>1006</code> is the one code no close-code tool can ever explain, because RFC 6455 forbids sending it on the wire at all — when it's the answer, the investigation has to move to server logs, where Chapter 23's OpenTelemetry pipeline turns this chapter's <code>otel.trace_id=...</code> log line into the queryable, cross-service answer a bare close code was never going to provide.</p></div>
