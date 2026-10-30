// deck.js — "WebSockets with Python — 201" companion deck.
// Building the handling-event feed on native websockets: the Part 3-6
// Python build, end to end, at just-enough-code depth. Red Hat house
// style, 16:9. Build: node deck.js
//
// Every code slide transcribes real source under examples/.../python/app/ —
// opened and read directly, not invented. Diagram captions are drawn from
// the published chapter figure alt-text/caption pairs (_docs/09 through
// _docs/23, _docs/00, _docs/11) where one exists; the five per-part
// architecture diagrams have no chapter-embedded caption (their README.md
// links the SVG with no alt/caption text), so their captions are built
// directly from the SVG's own closing summary line instead.

"use strict";

const H = require("./deck-helpers.js");
const {
  COLOR, FONT, W, PNG, ASSETS,
  newDeck, addFooter, addContentTitle, addBullets, addTwoColBullets,
  addStatusTable, addCaption, addCodeSlide, addDiagramSlide, addSectionDivider, addNotes,
} = H;

const OUT = "WebSockets_201_Python-r1.1.pptx";
const REV = "r1.1";
const LANG_PY = "Python · websockets / FastAPI";

const pres = newDeck();
pres.title = "WebSockets with Python: 201 (Building the handling-event feed on native websockets)";
let pageNum = 0;
let mainCount = 0;
let appendixCount = 0;

let inAppendix = false;
function S() { const s = pres.addSlide(); pageNum += 1; addFooter(s, pageNum); if (inAppendix) appendixCount += 1; else mainCount += 1; return s; }
function divider(code, title, subtitle, notes) {
  const s = pres.addSlide(); pageNum += 1; addSectionDivider(s, code, title, subtitle); addNotes(s, notes);
  if (inAppendix) appendixCount += 1; else mainCount += 1;
}
function content(eyebrow, title, bullets, notes, opts) {
  const s = S();
  addContentTitle(s, eyebrow, title);
  addBullets(s, bullets, opts || {});
  addNotes(s, notes);
  return s;
}
function diagram(eyebrow, title, png, caption, notes, opts) {
  const s = S();
  addDiagramSlide(s, eyebrow, title, png, caption, opts || {});
  addNotes(s, notes);
  return s;
}
function code(eyebrow, title, lang, codeLines, caption, notes, opts) {
  const s = S();
  addCodeSlide(s, eyebrow, title, lang, codeLines, caption, opts || {});
  addNotes(s, notes);
  return s;
}

// ===== COVER ===================================================================
{
  const s = pres.addSlide();
  pageNum += 1; mainCount += 1;
  s.background = { color: COLOR.white };
  try { s.addImage({ path: `${ASSETS}/cover-panel.png`, x: 0, y: 0, w: W, h: 7.5 }); } catch (e) {}
  s.addText("WEBSOCKETS WITH PYTHON · 201", { x: 6.00, y: 1.98, w: 6.90, h: 0.34,
    fontFace: FONT.title, fontSize: 13, bold: true, color: COLOR.red, charSpacing: 5, align: "left", valign: "middle" });
  s.addText([{ text: "Building the handling-event", options: { breakLine: true } },
             { text: "feed on native websockets" }], {
    x: 5.95, y: 2.42, w: 6.95, h: 2.00, fontFace: FONT.title, fontSize: 34, bold: true, color: COLOR.ink, align: "left", valign: "top" });
  s.addText("The Python build, end to end: the native `websockets` endpoint, connection concerns, the Kafka/Redis backplane, Protobuf performance, testing and observability, and deploy.",
    { x: 6.00, y: 4.80, w: 6.80, h: 1.00, fontFace: FONT.body, fontSize: 16, italic: true, color: COLOR.caption, align: "left", valign: "top" });
  s.addText(REV, { x: 11.85, y: 5.85, w: 0.95, h: 0.30, fontFace: FONT.mono, fontSize: 11, color: COLOR.caption, align: "right", valign: "middle" });
  try { s.addImage({ path: `${ASSETS}/logo-candidate-2.png`, x: 11.10, y: 6.80, w: 1.55, h: 0.37 }); } catch (e) {}
  addNotes(s, "This is the 201-Python: the code-level companion for engineers implementing the handling-events feed on Python's native websockets library rather than FastAPI's bundled WebSocket support. The main body runs just under 50 slides across six sections: the Part 3 endpoint, Part 4 connection concerns (backpressure, errors, liveness, auth), Part 4 reconnect and the backplane, Part 5 Protobuf performance, Part 6 testing/debugging/observability, and deploy. The Quarkus WebSockets Next sibling is cross-referenced by concept throughout, never by slide number.");
}

// ===== AGENDA ===================================================================
{
  const s = S();
  addContentTitle(s, "201 · THE PYTHON BUILD", "The handling-events feed, one section per part, plus an appendix");
  addTwoColBullets(s,
    ["01: The Python endpoint: native websockets, two listeners on one loop, the generated contract model",
     "02: Connection concerns: the bounded outbound buffer, envelope-then-close errors, the idle-timeout trap, JWT at the upgrade",
     "03: Reconnect and the backplane: stateless by default, Kafka-backed resume, Redis Pub/Sub, scale-out fan-out"],
    ["04: Performance: binary Protobuf as a second encoding, the levers that bound throughput",
     "05: Testing, debugging, observability: the test pyramid, symptom-to-tool, a hand-written span where no auto-instrumentation exists",
     "06: Deploy: Compose to minikube to OpenShift Local",
     { text: "Appendix: model-generation pipeline, the maxsize=0 behavior, dedup-by-eventId, Newman + k6, the drift gate, version matrix", muted: true }]);
  addNotes(s, "Six sections, the same order the chapters build in: the endpoint (Python native websockets), the four connection concerns (backpressure and flow control, error handling, liveness and heartbeats, security), reconnect and scale-out (stateless reconnect, Kafka-backed reconnect, scale-out and fan-out), performance (binary Protobuf over WebSockets, optimizing throughput), the toolbox (testing, debugging, observability), and deploy. Appendix carries the model-generation pipeline, a deeper look at the backpressure behavior, Kafka dedup, the Newman and k6 scripts, the drift-gate pipeline figure, and the version matrix. Cross-references to the Quarkus WebSockets Next sibling are by concept, 'the same close code on both stacks,' never by slide number, so the deck survives a trim.");
}

// ===== SECTION 01 — THE PYTHON ENDPOINT =========================================
divider("01", "The Python Endpoint", "Native websockets, not FastAPI's bundled WebSocket support.",
  "Opens with the Part 3 build (Python native websockets): one handler, one channel, pushing the fixture's three HandlingEvents on connect. The choice this whole section defends is using the raw `websockets` library instead of Starlette's bundled WebSocket support. That contrast is this section's throughline.");

diagram("THE PYTHON ENDPOINT · AT A GLANCE", "One channel, two stacks, the same fixture sequence",
  "part3-architecture",
  "Neither stack reads the other's source: both push the identical RECEIVE/LOAD/CUSTOMS sequence, verified by verify.sh.",
  "Quarkus implements the channel with @OnOpen returning a Multi<HandlingEvent>; Python implements it with the native websockets library's handler coroutine. Same channel path (/ws/v1/bookings/{id}/handling-events), same fixture, same order. This diagram is the orientation slide before the code.");

code("THE PYTHON ENDPOINT · THE HANDLER", "serve() + handler(ServerConnection): push the fixture, then idle",
  LANG_PY,
  ["# examples/part3-handling-events/python/app/ws_server.py",
   "async def handler(websocket: ServerConnection) -> None:",
   "    path = websocket.request.path",
   "    match = _CHANNEL_PATH.match(path)",
   "    if match is None:",
   "        await websocket.close(code=1008, reason=\"unknown channel path\")",
   "        return",
   "",
   "    booking_id = match.group(\"bookingId\")",
   "    try:",
   "        for frame in sequence_as_json():",
   "            await websocket.send(frame)",
   "        # fixture sequence is finite; a real feed would keep sending.",
   "        await websocket.wait_closed()",
   "    except ConnectionClosed:",
   "        logger.info(\"handling-events: client disconnected bookingId=%s\", booking_id)",
   "",
   "def create_server(host: str, port: int):",
   "    return serve(handler, host, port)"],
  "examples/part3-handling-events/python/app/ws_server.py: handler(ServerConnection) pushes the fixture, then holds the connection open",
  "websocket.request.path carries the full request-target; the channel regex is matched against it directly here (Part 4 later has to split off a query string for the token). sequence_as_json() reuses the same generated model the conformance test validates against: nothing hand-written sits between the contract and this send() call. No subprotocol is enforced yet: passing subprotocols= to serve() would reject any client that didn't offer one, breaking plain clients for no behavior this example implements. The security chapter is where that changes.");

content("WHY NOT FASTAPI/STARLETTE'S BUNDLED WEBSOCKET", "The chapter's own contrast, stated directly",
  ["Starlette's WebSocket support is exactly what this chapter is contrasting against: this example runs the raw `websockets` library instead, on its own asyncio listener, side by side with a small FastAPI app that owns only HTTP and lifecycle.",
   "The two servers run as two coroutines on one event loop, not two processes: `asyncio.gather(_run_ws(), _run_http())` in app/main.py, each awaited forever.",
   "That split keeps the WebSocket surface on the library built specifically for the protocol, while FastAPI keeps doing what it's good at: `/healthz`, `/`, and (from Part 4 on) the HTTP inject seam."],
  "This is an architectural choice worth defending out loud: `websockets` is a focused, asyncio-native library built for exactly one protocol, with direct control over ping/pong, subprotocol negotiation, and close codes, all of which this deck's later slides lean on directly (liveness's ping_interval/ping_timeout as a serve() kwarg, security's close-code-only auth rejection). FastAPI/Starlette's bundled WebSocket support exists, but it isn't what this series is teaching.");

diagram("TWO LISTENERS, ONE EVENT LOOP", "The WS server and the FastAPI app, as coroutines",
  "09-two-listeners-one-loop",
  "Figure 9.1. app/main.py runs the websockets server and FastAPI side by side as two coroutines on one asyncio event loop.",
  "Neither listener blocks the other: they're coroutines, not separate processes or threads, both reachable under the same `asyncio.run(main())`. The WS listener is on :8081 (8080 is reserved for the Quarkus sibling in Compose); the FastAPI app is on :8082, for a k8s probe's `GET /healthz`.");

code("THE PYTHON ENDPOINT · THE LISTENERS", "asyncio.gather on one loop; FastAPI owns only HTTP",
  LANG_PY,
  ["# examples/part3-handling-events/python/app/main.py",
   "async def _run_http() -> None:",
   "    config = uvicorn.Config(http_app, host=HTTP_HOST, port=HTTP_PORT, log_level=\"info\")",
   "    server = uvicorn.Server(config)",
   "    await server.serve()",
   "",
   "async def _run_ws() -> None:",
   "    async with create_server(WS_HOST, WS_PORT):",
   "        await asyncio.get_running_loop().create_future()  # run forever",
   "",
   "async def main() -> None:",
   "    await asyncio.gather(_run_ws(), _run_http())",
   "",
   "# examples/part3-handling-events/python/app/http_app.py",
   "app = FastAPI(title=\"handling-events-python\", ...)",
   "",
   "@app.get(\"/healthz\")",
   "async def healthz() -> dict:",
   "    return {\"status\": \"ok\"}"],
  "examples/part3-handling-events/python/app/main.py + app/http_app.py: two coroutines, one loop, two ports",
  "http_app.py is not where the WebSocket endpoint lives, by design: that's the whole point of this example. `await asyncio.get_running_loop().create_future()` is the idiom for 'run this context manager forever': it's a future nobody ever resolves, which is exactly what `async with create_server(...)` needs to stay open for the life of the process.");

diagram("GENERATING THE CONTRACT MODEL AT BUILD TIME", "contracts/asyncapi.yaml to a Pydantic model, with nothing hand-written in between",
  "09-model-generation-flow",
  "Figure 9.2. contracts/asyncapi.yaml becomes app/models_generated.py's Pydantic model at build time; nothing hand-written sits between the contract and the wire frame.",
  "Two generation steps, not one: extract-message-schema.py inlines the AsyncAPI document's $refs into a self-contained Draft 2020-12 JSON Schema (datamodel-code-generator's own AsyncAPI input support is unreliable against this document), then datamodel-codegen turns that schema into the Pydantic v2 model. app/feed.py and app/ws_server.py both import the generated model: one does validate-in, the other does serialize-out.");

code("THE GENERATED MODEL", "datamodel-codegen output: never hand-edited",
  LANG_PY,
  ["# generated by datamodel-codegen:",
   "#   filename:  handling-event.schema.json",
   "from enum import StrEnum",
   "from pydantic import AwareDatetime, BaseModel, Field, constr",
   "",
   "class EventType(StrEnum):",
   "    HANDLING_EVENT_TYPE_UNSPECIFIED = 'HANDLING_EVENT_TYPE_UNSPECIFIED'",
   "    RECEIVE = 'RECEIVE'",
   "    LOAD = 'LOAD'",
   "    UNLOAD = 'UNLOAD'",
   "    CUSTOMS = 'CUSTOMS'",
   "    CLAIM = 'CLAIM'",
   "    HOLD = 'HOLD'",
   "    DELIVERED = 'DELIVERED'",
   "",
   "class HandlingEvent(BaseModel):",
   "    bookingId: constr(pattern=r'^bkg_[0-9A-Za-z]{26}$') = Field(...)",
   "    cargoId: constr(pattern=r'^crg_[0-9A-Za-z]{26}$') = Field(...)",
   "    eventId: constr(pattern=r'^evt_[0-9A-Za-z]{26}$') = Field(...)",
   "    eventType: EventType = Field(...)",
   "    occurredAt: AwareDatetime = Field(...)",
   "    registeredAt: AwareDatetime = Field(...)",
   "    voyageNumber: str | None = Field(None)"],
  "examples/part3-handling-events/python/app/models_generated.py: the full generated Pydantic v2 model, trimmed to its field list for the slide",
  "The file's own first line is the warning: '# generated by datamodel-codegen'. The Containerfile and scripts/generate-models.sh both regenerate this file on every build, and it's gitignored. EventType's `_UNSPECIFIED` zero value is never sent by the server; it exists purely so deserialization always has a safe default, matching the `*_UNSPECIFIED` convention the series' gRPC enums use.");

code("THE CONFORMANCE TEST", "Round-trip fidelity: schema validation plus exact-value round-trip",
  "python · pytest",
  ["# examples/part3-handling-events/python/tests/test_contract.py",
   "def test_emitted_frames_validate_against_schema(validator):",
   "    frames = sequence_as_json()",
   "    for frame in frames:",
   "        doc = json.loads(frame)",
   "        errors = list(validator.iter_errors(doc))",
   "        assert not errors, f\"{frame} failed schema validation: {errors}\"",
   "",
   "def test_generated_model_round_trips_fixture_values_exactly():",
   "    for raw in load_fixture():",
   "        model = HandlingEvent.model_validate(raw)",
   "        dumped = json.loads(model.model_dump_json(exclude_none=True))",
   "        assert dumped == raw, f\"round-trip drift for {raw['eventId']}: {dumped} != {raw}\""],
  "examples/part3-handling-events/python/tests/test_contract.py: asserts both schema validity and exact-value round-trip fidelity",
  "Two different assertions, each answering a different question: schema validation proves the frame is a legal HandlingEvent; the round-trip test proves nothing drifted in translation, including the `Z` UTC suffix on timestamps, which Pydantic v2's datetime serialization preserves from the input rather than normalizing to `+00:00`. 'Still valid JSON' is not the bar this test holds; 'the exact same values' is.");

// ===== SECTION 02 — CONNECTION CONCERNS =========================================
divider("02", "Connection Concerns", "Backpressure, errors, liveness, and auth: four concerns on one connection.",
  "Walks the Part 4 connection example (backpressure, error handling, liveness, and security): the bounded outbound buffer, envelope-then-close error handling, the idle-timeout trap and the library's own ping/pong default, and JWT auth validated right after the upgrade completes.");

diagram("THE PART-4 CONNECTION APP", "Four concerns layered onto Part 3's plain replay",
  "part4-connection-architecture",
  "Same shared JWT secret, same close codes on both stacks: verify.sh asserts a client can't tell them apart.",
  "Four concerns layer onto the same channel path: an auth gate before any data streams (security), a bounded OutboundQueue feeding the replay (backpressure), a receive loop that rejects any client frame as a protocol error (error handling), and ping_interval/ping_timeout handed straight to the library (liveness). Every one of these is closed-source behavior on the Quarkus side too: same close codes, same shared secret.");

diagram("BACKPRESSURE: THE BOUNDED OUTBOUND BUFFER", "Two independent signals trip the policy",
  "12-outbound-buffer-policy",
  "Figure 12.2. the bounded outbound buffer sitting between the producer and the socket write, and the two policies for what happens once one of the two trigger conditions fires.",
  "Two signals, not one: the queue fills (a sustained rate mismatch) or a single send() hangs past the timeout (the peer's TCP receive window is full because it stopped reading entirely). Either one trips the configured policy: close (the safer default) or drop. This channel has its own semantics: a missed HandlingEvent is a correctness problem, not a superseded ticker value. That is exactly why close, not drop, is the default here.");

code("THE OUTBOUND BUFFER", "asyncio.Queue decouples the producer from the socket write",
  LANG_PY,
  ["# examples/part4-connection/python/app/outbound.py",
   "QUEUE_MAXSIZE = int(os.environ.get(\"OUTBOUND_QUEUE_MAXSIZE\", \"32\"))",
   "SEND_TIMEOUT_S = float(os.environ.get(\"OUTBOUND_SEND_TIMEOUT_S\", \"5.0\"))",
   "CLOSE_CODE_SLOW_CONSUMER = 4290",
   "",
   "class OutboundQueue:",
   "    def __init__(self, maxsize: int = QUEUE_MAXSIZE, policy: str = BACKPRESSURE_POLICY) -> None:",
   "        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)",
   "        self._policy = policy",
   "",
   "    def enqueue(self, frame: str) -> None:",
   "        try:",
   "            self._queue.put_nowait(frame)",
   "        except asyncio.QueueFull:",
   "            self._on_backpressure(f\"outbound queue full (maxsize={self._queue.maxsize})\")",
   "",
   "    async def drain(self, websocket) -> None:",
   "        while True:",
   "            frame = await self._queue.get()",
   "            try:",
   "                await asyncio.wait_for(websocket.send(frame), timeout=SEND_TIMEOUT_S)",
   "            except asyncio.TimeoutError:",
   "                self._on_backpressure(f\"send() exceeded {SEND_TIMEOUT_S}s\")"],
  "examples/part4-connection/python/app/outbound.py: the default QUEUE_MAXSIZE is 32, env-overridable; maxsize=0 means unbounded",
  "The detail the appendix goes deeper on: `asyncio.Queue(maxsize=0)` means unbounded, not zero-capacity, the opposite of the intuitive reading, and exactly the setting that defeats this whole mechanism if someone 'simplifies' the env default. CLOSE_CODE_SLOW_CONSUMER (4290) lives in the 4000-4999 private-use range so it can't be confused with an RFC 6455 standard code, and it's a convention shared with the Quarkus sibling.");

diagram("SLOW-CONSUMER TIMELINE", "A producer outrunning a consumer, without a bound",
  "12-slow-consumer-timeline",
  "Figure 12.1. a producer outrunning a consumer: the client's TCP window fills first, then the server's own send calls back up behind it, until one of the two signals trips the configured policy.",
  "Without a bound, t1 through t3 keep going forever: the buffer grows without limit and the server's own memory is what eventually fails, not the client. That's the resource-exhaustion path an unbounded queue (maxsize=0) opens: one slow client holding a full queue is a nuisance; an unbounded number of them is an outage.");

diagram("ERROR HANDLING: ENVELOPE-THEN-CLOSE", "Two signals, not one, for a client-caused protocol error",
  "13-error-flow-vs-1006",
  "Figure 13.2. the envelope-then-close sequence this chapter builds, next to the one failure mode no close code can ever carry: a peer that vanished before any handshake could complete.",
  "A close code alone tells the client that something went wrong, cheaply, but carries no human-readable detail and arrives after the connection is already gone. An in-band JSON error envelope sent before the close frame explains what was wrong, for a client developer debugging their own framing bug. 1006 is the contrast case: an RFC 6455 reserved value an implementation must never actually put in a close frame: it exists only for a local API to report 'no handshake happened at all.'");

code("CLOSE CODES AND THE ERROR ENVELOPE", "ConnectionClosed, and the channel's own protocol-error convention",
  LANG_PY,
  ["# examples/part4-connection/python/app/ws_server.py",
   "CLOSE_CODE_MALFORMED = 4400",
   "CLOSE_CODE_UNEXPECTED_ERROR = 1011",
   "CLOSE_CODE_UNKNOWN_CHANNEL = 1008",
   "",
   "async def _reject_malformed(websocket, reason: str) -> None:",
   "    await websocket.send(json.dumps(_error_envelope(reason)))",
   "    await websocket.close(code=CLOSE_CODE_MALFORMED, reason=\"malformed client message\")",
   "",
   "async def _receive_loop(websocket) -> None:",
   "    # server-push-only channel -- ANY client frame is a protocol error",
   "    async for message in websocket:",
   "        if not isinstance(message, str):",
   "            await _reject_malformed(websocket, \"binary frames are not supported on this channel\")",
   "            return",
   "        await _reject_malformed(websocket, \"this channel accepts no client-to-server messages\")",
   "        return"],
  "examples/part4-connection/python/app/ws_server.py: _reject_malformed sends the envelope, then closes 4400",
  "This channel defines no client-to-server operation at all, so the receive loop's job is simple: any inbound frame, of any shape, is by definition a protocol error. Auth (1008), backpressure (4290), and an internal error (1011) rely on the close code alone: none of them has a single offending frame to annotate, unlike the malformed-message case this slide shows.");

diagram("LIVENESS: THE IDLE-TIMEOUT TRAP", "A server's own ping can reset its own idle clock",
  "14-idle-timeout-trap",
  "Figure 14.1. the idle-timeout trap (the server's own ping keeps resetting its own idle clock) versus the pong-tracked sweep that actually detects a silent peer.",
  "The trap: if idle-timeout resets on any write, including the server's own outbound PING, a silent peer that never answers never trips it, because the server keeps resetting its own clock by pinging. The library's own pong-tracked approach (last_pong_at, swept on an interval) is what actually detects a peer that stopped responding, because it only looks at the client's last acknowledgment, never the server's own traffic.");

code("LIVENESS AS A LIBRARY DEFAULT", "ping_interval / ping_timeout, handed straight to serve()",
  LANG_PY,
  ["# examples/part4-connection/python/app/ws_server.py",
   "def create_server(host: str, port: int):",
   "    \"\"\"Ch14 heartbeats: ping_interval/ping_timeout are handed straight to",
   "    the `websockets` library, which sends a ping every ping_interval",
   "    seconds and closes the connection if no pong arrives within",
   "    ping_timeout seconds of that ping -- no code in this module",
   "    implements liveness detection; it is entirely the library's",
   "    responsibility.",
   "    \"\"\"",
   "    ping_interval = float(os.environ.get(\"WS_PING_INTERVAL_S\", \"20\"))",
   "    ping_timeout = float(os.environ.get(\"WS_PING_TIMEOUT_S\", \"20\"))",
   "    return serve(handler, host, port, ping_interval=ping_interval, ping_timeout=ping_timeout)"],
  "examples/part4-connection/python/app/ws_server.py: create_server's full liveness configuration, both env-overridable",
  "No sweep loop, no last-pong bookkeeping anywhere in this module: the entire liveness mechanism is two keyword arguments to serve(). That's the point worth making explicit against the Quarkus side, which implements its own HeartbeatLivenessSweep by hand: Python's native websockets library ships this as a built-in default behavior, not a pattern an application has to author itself.");

diagram("SECURITY: AUTHENTICATE AT THE UPGRADE", "Validate the token before streaming anything",
  "17-auth-upgrade-flow",
  "Figure 17.1. both stacks accept the handshake, then validate the token as the first thing the handler does, closing 1008 before any fixture frame goes out; Python's process_request hook exists but runs too early to issue that close code.",
  "Rejection happens post-accept, not at the HTTP level: the library's process_request hook runs before the opening handshake completes and can only return an HTTP response, since no WebSocket connection (and no application close code) exists yet. Closing with 1008 immediately after accepting, before a single fixture frame goes out, delivers the same 'no data, unambiguous rejection' outcome while keeping the close code the auth failure deserves.");

code("JWT AUTH: validate_token, PYJWT, COLLAPSE TO 1008", "process_request vs. the handler; every failure mode collapses to one code",
  LANG_PY,
  ["# examples/part4-connection/python/app/auth.py",
   "JWT_ALGORITHM = \"HS256\"",
   "JWT_SECRET = os.environ.get(\"WS_JWT_SECRET\", \"dev-secret-change-me\")",
   "CLOSE_CODE_AUTH_FAILED = 1008",
   "",
   "def validate_token(token: str | None) -> dict:",
   "    if not token:",
   "        raise AuthError(\"missing token\")",
   "    try:",
   "        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])",
   "    except jwt.ExpiredSignatureError as exc:",
   "        raise AuthError(\"expired token\") from exc",
   "    except jwt.InvalidSignatureError as exc:",
   "        raise AuthError(\"bad signature\") from exc",
   "    except jwt.InvalidTokenError as exc:",
   "        raise AuthError(f\"invalid token: {exc}\") from exc",
   "",
   "# app/ws_server.py, called right after the upgrade, before any frame is sent:",
   "try:",
   "    auth.validate_token(token)",
   "except auth.AuthError as exc:",
   "    await websocket.close(code=auth.CLOSE_CODE_AUTH_FAILED, reason=\"authentication failed\")",
   "    return"],
  "examples/part4-connection/python/app/{auth.py,ws_server.py}: missing, malformed, bad signature, and expired all collapse to the same 1008",
  "Missing, malformed, badly signed, and expired are all indistinguishable to an attacker probing the channel, so they all collapse to the same generic rejection: the specific reason is logged server-side via str(exc) but never echoed back on the wire, to avoid handing a prober a signature oracle. HS256 with a shared secret is the scope here; an asymmetric-key/JWKS-endpoint multi-service-audience setup is named as out of scope, not forgotten.");

// ===== SECTION 03 — RECONNECT AND THE BACKPLANE =================================
divider("03", "Reconnect and the Backplane", "Stateless by default, durable and replayable with Kafka, simple with Redis.",
  "Walks stateless reconnect, Kafka-backed reconnect, and scale-out and fan-out: when stateless reconnect is fine, the Kafka-backed backplane that closes the gap a stateless mode leaves open, the Redis Pub/Sub alternative, and the scale-out problem: a sticky session says nothing about where an event is produced.");

diagram("THE PART-4 BACKPLANE APP", "Two instances, one shared fan-out mechanism",
  "part4-backplane-architecture",
  "Both stacks (Quarkus WebSockets Next, Python websockets+FastAPI) implement this identically: PROTOCOL.md is the single source of truth.",
  "A test harness injects an event at instance B while the client is connected to instance A: exactly the gap a sticky load balancer can't close on its own. Three backplane modes share one interface: stateless (in-process only, the stateless-reconnect chapter), kafka (durable and replayable, the Kafka-backed-reconnect chapter), redis (live fan-out only, the scale-out chapter).");

diagram("STATELESS RECONNECT: afterEventId IGNORED", "Fine when a fresh value supersedes a stale one",
  "15-when-stateless-ok",
  "Figure 15.2. the decision: stateless reconnect is fine when a fresh value supersedes a stale one or a full resync is cheap, and not enough when every event is individually significant and the feed is the only record of it.",
  "This channel's own events fail the stateless test on two of three counts: every HandlingEvent is a discrete fact (a missed one is a missed fact, not a stale value), and there's no cheap full resync: the feed is the record, with no REST endpoint to re-GET the gap from. That's exactly why the Kafka-backed resume exists as the next slide.");

code("THE STATELESS BACKPLANE", "In-process fan-out only; after_event_id accepted but always ignored",
  LANG_PY,
  ["# examples/part4-backplane/python/app/backplane/stateless_backplane.py",
   "class StatelessBackplane(Backplane):",
   "    def __init__(self) -> None:",
   "        self._subscribers: dict[str, set[asyncio.Queue[HandlingEvent]]] = defaultdict(set)",
   "",
   "    async def publish(self, booking_id: str, event: HandlingEvent) -> None:",
   "        queues = self._subscribers.get(booking_id)",
   "        if not queues:",
   "            logger.info(\"stateless backplane: no local subscribers ... dropped\")",
   "            return",
   "        for queue in list(queues):",
   "            queue.put_nowait(event)",
   "",
   "    async def subscribe(self, booking_id, after_event_id):",
   "        del after_event_id  # unused -- no history to replay",
   "        queue: asyncio.Queue[HandlingEvent] = asyncio.Queue()",
   "        self._subscribers[booking_id].add(queue)",
   "        try:",
   "            while True:",
   "                yield await queue.get()",
   "        finally:",
   "            self._subscribers[booking_id].discard(queue)"],
  "examples/part4-backplane/python/app/backplane/stateless_backplane.py: no broker, no shared state, scoped to this instance only",
  "This is the default profile, and the scale-out chapter's motivating contrast case: two instances behind a load balancer do not see each other's injected events. after_event_id is accepted purely for interface symmetry with the other two modes: this mode keeps no history at all, so a gap-era event is lost for a disconnected client, by design (PROTOCOL.md calls this the 'visible-gap proof').");

diagram("KAFKA-BACKED RESUME: TOPIC OFFSET TO afterEventId", "Durable + replayable, the resume mechanism itself",
  "16-topic-offset-resume",
  "Figure 16.1. the topic/offset/resume model: the seed never touches Kafka, only injected events are keyed into the topic by bookingId, and an afterEventId that names a seed id always falls back to replaying everything currently in the topic.",
  "The three fixture seed events never touch this topic: only injected events do, and every connection in every backplane mode gets the seed sequence delivered directly from app/feed.py regardless of broker state. That design choice is what keeps afterEventId=<the last seed event's id> meaningful even though that id was never produced to the topic: subscribe falls back to 'treat everything currently in the topic as after after_event_id' when the given id is never found.");

code("THE KAFKA BACKPLANE", "aiokafka producer/consumer; buffer-then-search for the replay-after case",
  LANG_PY,
  ["# examples/part4-backplane/python/app/backplane/kafka_backplane.py",
   "async def publish(self, booking_id: str, event: HandlingEvent) -> None:",
   "    await self._producer.send_and_wait(",
   "        self._topic,",
   "        key=booking_id.encode(\"utf-8\"),",
   "        value=event.model_dump_json(exclude_none=True).encode(\"utf-8\"),",
   "    )",
   "",
   "async def subscribe(self, booking_id, after_event_id):",
   "    consumer = AIOKafkaConsumer(bootstrap_servers=self._bootstrap_servers,",
   "                                 enable_auto_commit=False, auto_offset_reset=\"earliest\")",
   "    await consumer.start()",
   "    ...",
   "    if after_event_id is not None:",
   "        await consumer.seek_to_beginning(*topic_partitions)",
   "        end_offsets = await consumer.end_offsets(topic_partitions)",
   "        # buffer every record up to the snapshotted end offsets, THEN",
   "        # search for after_event_id's index -- streaming can't decide",
   "        # in time whether a record should ultimately be kept.",
   "        ...",
   "    async for record in consumer:",
   "        if record.key.decode(\"utf-8\") == booking_id:",
   "            yield HandlingEvent.model_validate_json(record.value)"],
  "examples/part4-backplane/python/app/backplane/kafka_backplane.py: publish keyed by bookingId; subscribe buffers history before deciding what to replay",
  "The buffer-then-search shape is deliberate, not an obvious choice: deciding skip-vs-yield while streaming can't know in advance whether after_event_id will ever show up, so it can't decide in time whether the record in front of it right now should be kept. Buffering the whole history first turns 'find after_event_id's index, or don't' into a simple list search.");

diagram("SCALE-OUT: STICKY SESSIONS VS. A SHARED BACKPLANE", "A sticky session says nothing about where an event is produced",
  "18-sticky-vs-backplane",
  "Figure 18.1. a sticky load balancer pins the client to instance A, but the event enters at instance B; without a shared backplane the event never crosses the gap between them.",
  "This is the scale-out chapter's motivating picture: sticky sessions keep a client on one instance and nothing more: they say nothing about which instance an event is produced on. Without a backplane, instance A has no way to learn about something that happened at instance B. Only a shared Kafka topic or Redis channel crosses that gap.");

diagram("KAFKA VS. REDIS", "Same fan-out outcome, different trade-off: no single winner",
  "18-kafka-vs-redis",
  "Figure 18.2. Kafka and Redis both close the fan-out gap; the difference is what each one gives up to do it cheaply (Redis) or durably (Kafka), not whether the client gets the event.",
  "verify.sh proves the same cross-instance delivery on both brokers, for both stacks: this is a trade-off, not a ranking. Kafka: durable, retained on disk, replayable (powers the Kafka-backed reconnect), at the cost of topic/partition/offset bookkeeping. Redis: every subscriber gets every publish, live-only, no history; a dropped subscriber loses in-flight messages with nothing to catch it back up.");

code("THE REDIS PUB/SUB BACKPLANE", "Simplicity and latency, at the cost of any history",
  LANG_PY,
  ["# examples/part4-backplane/python/app/backplane/redis_backplane.py",
   "def _channel(booking_id: str) -> str:",
   "    return f\"handling-events:{booking_id}\"",
   "",
   "async def publish(self, booking_id: str, event: HandlingEvent) -> None:",
   "    await self._client.publish(_channel(booking_id), event.model_dump_json(exclude_none=True))",
   "",
   "async def subscribe(self, booking_id, after_event_id):",
   "    del after_event_id  # unused -- no history in Pub/Sub",
   "    pubsub = self._client.pubsub()",
   "    channel = _channel(booking_id)",
   "    await pubsub.subscribe(channel)",
   "    try:",
   "        async for message in pubsub.listen():",
   "            if message.get(\"type\") != \"message\":",
   "                continue",
   "            yield HandlingEvent.model_validate_json(message[\"data\"])",
   "    finally:",
   "        await pubsub.unsubscribe(channel)"],
  "examples/part4-backplane/python/app/backplane/redis_backplane.py: redis.asyncio Pub/Sub, after_event_id always ignored like stateless mode",
  "PROTOCOL.md states this contrast explicitly: 'In redis mode, afterEventId resume behaves as stateless (no history).' No topic/partition/offset bookkeeping at all: a message is published, every live subscriber gets it, and that's the entire durability story. The first message on a fresh subscribe() is always a control 'subscribe' confirmation, not an app payload, which is why this loop filters on message type.");

code("THE HTTP INJECT SEAM", "One endpoint feeds whichever backplane is active",
  LANG_PY,
  ["# examples/part4-backplane/python/app/http_app.py",
   "@app.post(\"/internal/bookings/{bookingId}/handling-events\", status_code=202)",
   "async def inject_handling_event(bookingId: str, event: HandlingEvent, request: Request) -> dict:",
   "    \"\"\"Publishes `event` to the active backplane (kafka topic / redis",
   "    channel) in broker modes, or delivers it to this instance's local",
   "    connections in stateless mode. Internal/demo endpoint, not part of",
   "    the public AsyncAPI contract.",
   "    \"\"\"",
   "    backplane = request.app.state.backplane",
   "    await backplane.publish(bookingId, event)",
   "    logger.info(\"injected eventId=%s bookingId=%s instance=%s\",",
   "                event.eventId, bookingId, request.app.state.instance_id)",
   "    return {\"status\": \"accepted\", \"eventId\": event.eventId, \"bookingId\": bookingId}"],
  "examples/part4-backplane/python/app/http_app.py: PROTOCOL.md's \"Inject endpoint\", shared across all three backplane modes",
  "One FastAPI route, one line that actually matters: `backplane.publish(bookingId, event)`. The polymorphism lives entirely behind the Backplane interface, so this endpoint has no idea whether it's talking to an in-process queue, a Kafka producer, or a Redis client. That's what lets tests and the scale-out chapter's demo script inject an event the same way regardless of which mode the instance was started in.");

// ===== SECTION 04 — PERFORMANCE =================================================
divider("04", "Performance", "Binary Protobuf as a second encoding, not a second contract.",
  "Walks binary Protobuf over WebSockets and optimizing throughput: negotiating a second wire encoding by subprotocol, why field numbers (not key names) are Protobuf's real contract, and the four levers that sit under the backpressure ceiling: encoding, batching, compression, size limits.");

diagram("THE PART-5 PERFORMANCE APP", "One channel, two wire encodings, negotiated by subprotocol",
  "part5-performance-architecture",
  "Same contract, same fixture, two wire encodings: verify.sh proves field equality and the Protobuf size win live on both stacks.",
  "This example drops Part 4's connection concerns entirely (no backpressure, no in-band errors, no auth, no heartbeat tuning) to isolate the encoding comparison: the same HandlingEvent, pushed either as a 247-byte JSON text frame or a 149-byte Protobuf binary frame, decoded both ways to prove the field values are identical.");

diagram("BINARY PROTOBUF: A SECOND ENCODING, NOT A SECOND CONTRACT", "One message, negotiated by Sec-WebSocket-Protocol",
  "19-two-encodings-one-message",
  "Figure 19.1. one HandlingEvent, two wire encodings negotiated by subprotocol; the frame opcode tells the receiving end which decoder to use before it reads a single byte.",
  "The opcode itself (0x1 text, 0x2 binary) is the signal: a receiver knows which decoder to reach for before it reads a single byte of payload. verify.sh decodes both and asserts the field values are identical: this is one contract wearing two different wire shapes, never two diverging message definitions.");

code("THE PROTO MAPPER", "Validated model to its Protobuf binary twin, and back",
  LANG_PY,
  ["# examples/part5-performance/python/app/mapper.py",
   "_PROTO_ENUM_PREFIX = \"HANDLING_EVENT_TYPE_\"",
   "",
   "def to_proto(event: HandlingEventModel) -> HandlingEventProto:",
   "    \"\"\"Validated model -> Protobuf message, field VALUES byte-for-byte",
   "    identical to the JSON encoding.\"\"\"",
   "    data = event.model_dump(mode=\"json\", exclude_none=True)",
   "    kwargs = {",
   "        \"event_id\": data[\"eventId\"],",
   "        \"booking_id\": data[\"bookingId\"],",
   "        \"event_type\": _event_type_to_proto(data[\"eventType\"]),",
   "        \"occurred_at\": data[\"occurredAt\"],",
   "    }",
   "    if \"amount\" in data:",
   "        kwargs[\"amount\"] = data[\"amount\"]",
   "    return HandlingEventProto(**kwargs)",
   "",
   "# app/ws_server.py -- subprotocol decides the encoding, once, at handshake:",
   "SUBPROTOCOL_PROTOBUF = \"handling-events.v1+protobuf\"",
   "if _is_protobuf(websocket):",
   "    await websocket.send(to_proto(event).SerializeToString())",
   "else:",
   "    await websocket.send(event.model_dump_json(exclude_none=True))"],
  "examples/part5-performance/python/app/{mapper.py,ws_server.py}: model_dump(mode=\"json\") first, so both encodings carry the exact same string values",
  "Both directions operate on plain JSON-mode values, not native Python types: every value placed into (or read back out of) the proto message is the exact same string the JSON encoding already carries, including RFC-3339 timestamps and decimal-string Money. That's what lets one JSON Schema validate a decoded Protobuf message with no second, proto-specific schema.");

diagram("FIELD NUMBERS ARE THE REAL CONTRACT", "A JSON key can be renamed freely; a Protobuf field number never moves",
  "19-field-numbers-vs-key-names",
  "Figure 19.2. a JSON key can be renamed freely because the string itself is the identity; a Protobuf field number can never move or be reused, because the integer tag, not the field's name, is the wire identity.",
  "check-proto-parity.py fails the build the moment either side adds, removes, or reorders a field the other side doesn't also carry: field numbers are additive-only, the same discipline the versioning-and-evolution chapter's JSON contract already enforces on key names, just enforced differently because the two encodings carry their contract in different places.");

diagram("OPTIMIZING THROUGHPUT: THE LEVERS", "Four levers, one shared ceiling",
  "20-levers",
  "Figure 20.2. four throughput levers, one shared ceiling: the bounded outbound queue governs every byte every lever above it produces.",
  "Encoding (Protobuf vs. JSON) is a fixed, load-independent discount: 40.7% smaller, identical at any connection rate. Batching trades latency for fewer, larger frames. Compression is a per-stack opt-in, not a universal default (next slide). Size limits bound a single frame regardless of queue depth. None of the four changes whether or when the backpressure bound trips: they only change how much useful work fits before hitting it.");

code("COMPRESSION AND SIZE LIMITS: BOTH LIBRARY DEFAULTS", "create_server() never sets either: it inherits both",
  LANG_PY,
  ["# examples/part5-performance/python/app/ws_server.py",
   "def create_server(host: str, port: int):",
   "    \"\"\"Returns the `websockets.asyncio.server.serve(...)` context",
   "    manager; callers `async with` it (see app/main.py) to start/stop",
   "    the listener. `subprotocols` advertises the three supported",
   "    values; `select_subprotocol` overrides the library's default",
   "    negotiation to also accept a client that offers none at all.",
   "    \"\"\"",
   "    return serve(",
   "        handler,",
   "        host,",
   "        port,",
   "        subprotocols=SUPPORTED_SUBPROTOCOLS,",
   "        select_subprotocol=_select_subprotocol,",
   "    )"],
  "examples/part5-performance/python/app/ws_server.py: create_server() passes no compression, max_size, or max_queue argument at all",
  "What isn't on screen is the point: serve()'s own signature defaults to compression=\"deflate\" and a real 1 MiB max_size, neither overridden here: every connection to Python's :8091 negotiates permessage-deflate unless a caller explicitly opts out. The optimizing-throughput chapter's own measurement found Quarkus WebSockets Next takes the opposite stance (off unless per-message-compression-supported=true is set): the same benchmark request negotiated deflate on 100% of Python's connects and 0% of Quarkus's.");

diagram("BYTES PER FRAME, MEASURED", "40.7% smaller, and a blind spot the benchmark tool can't see past",
  "20-bytes-per-frame",
  "Figure 20.1. the measured bytes/frame comparison and the real stack difference in whether permessage-deflate gets negotiated at all; the deflate row's bytes/frame is a blind spot, not evidence against compression.",
  "k6/ws is built on gorilla/websocket, which transparently inflates a compressed frame before the script ever sees its bytes: the json_deflate row reading identical to plain json is a measurement-tool blind spot, not proof deflate had no effect on the wire. What the benchmark can prove without inference is the negotiation outcome itself: Python 7908/7908 (100%), Quarkus 0 out of 11806-18292 across three runs (0%), the one number this chapter treats as proven rather than inferred.");

// ===== SECTION 05 — TESTING, DEBUGGING, OBSERVABILITY ===========================
divider("05", "Testing, Debugging, Observability", "A protocol you can't curl needs a different toolbox.",
  "Walks testing, debugging, and observability: the five-tool test pyramid behind every example in this series, a symptom-to-tool map for live debugging, and the hand-written OpenTelemetry span Python needs where Quarkus gets one through auto-instrumentation alone.");

diagram("THE TEST PYRAMID FOR A PROTOCOL YOU CAN'T CURL", "Five tools, four tiers, one contract-derived schema",
  "21-test-pyramid",
  "Figure 21.1. the WebSocket test pyramid: five tools across four tiers, narrower and slower toward the top, all gated on the same contract-derived schema.",
  "Bottom to top: unit/conformance (pytest test_contract.py, no socket, milliseconds), live integration (verify.sh + lib.sh, real containers, both stacks), functional (Newman plus a close-code probe, the HTTP seam and close codes websocat can't read), load (k6: smoke.js gated, benchmark.js local-only). The contract-drift gate sits underneath all four: regenerate the schema, re-run every layer that reads it, on every change to contracts/asyncapi.yaml.");

diagram("DEBUGGING: SYMPTOM TO TOOL", "Reach for the cheapest tool that taps the right layer first",
  "22-symptom-to-tool",
  "Figure 22.2. five symptoms, five first tools: start at the cheapest tool that taps the layer the symptom points to.",
  "Never upgrades at all → curl --include the upgrade request. 101 then silence → DevTools Frames tab or websocat -t. Wrong frame shape → websocat -b piped to xxd (an opcode mismatch, the binary-Protobuf chapter's JSON-vs-binary negotiation gone wrong). Drops with no obvious reason → python ws_close_probe plus the server's trace-id logs: the close code says why (4400, 4290, 4408, 1008; 1006 means no code arrived at all). Dies after sustained load → tcpdump plus server logs over time, looking for backpressure or the liveness sweep firing under pressure.");

diagram("OBSERVABILITY: NO AUTO-INSTRUMENTATION FOR NATIVE websockets", "Same span name, same trace-id log line, two different paths to get there",
  "23-auto-vs-manual",
  "Figure 23.1. Quarkus adds a manual child span under an auto-traced HTTP upgrade; Python has no auto-traced layer at all, so the whole connection span is hand-written with the SDK tracer directly.",
  "This is what this whole section exists to demonstrate: there is no opentelemetry-instrumentation-websockets package, and the native websockets library has no OTel hook of its own. A trace that only covered the HTTP side (which is auto-instrumented via opentelemetry-instrumentation-fastapi) would never show the WS connection at all, so this module starts the entire connection span by hand.");

code("THE MANUAL SPAN AND THE TRACE-ID LOG LINE", "tracer.start_as_current_span, a counter, and one required correlation line",
  LANG_PY,
  ["# examples/part6-observability/python/app/ws_server.py",
   "tracer = trace.get_tracer(\"part6-observability-python.ws_server\")",
   "CONNECTION_SPAN_NAME = \"ws.handling-events.connection\"",
   "",
   "def _log_trace_id(span, booking_id: str) -> None:",
   "    trace_id = format(span.get_span_context().trace_id, \"032x\")",
   "    logger.info(\"otel.trace_id=%s span=%s bookingId=%s instance=%s\",",
   "                trace_id, CONNECTION_SPAN_NAME, booking_id, INSTANCE_NAME)",
   "",
   "async def _replay(websocket, booking_id: str) -> None:",
   "    with tracer.start_as_current_span(CONNECTION_SPAN_NAME) as span:",
   "        span.set_attribute(\"bookingId\", booking_id)",
   "        _log_trace_id(span, booking_id)",
   "        for event in sequence():",
   "            frame = mapper.to_wire_frame(event)",
   "            await websocket.send(frame)",
   "            HANDLING_EVENTS_DELIVERED_TOTAL.inc()",
   "",
   "# examples/part6-observability/python/app/metrics.py",
   "HANDLING_EVENTS_DELIVERED_TOTAL = Counter(",
   "    \"handling_events_delivered_total\",",
   "    \"Total number of HandlingEvent frames delivered to a WebSocket client.\",",
   ")"],
  "examples/part6-observability/python/app/{ws_server.py,metrics.py}: one span per connection, one counter increment per frame",
  "`opentelemetry-instrument` has already configured the global TracerProvider and OTLP exporter before this module is ever imported, so trace.get_tracer(__name__) reads that configuration directly: only the span itself is hand-written, not the SDK setup. format(..., \"032x\") is the correct way to render a 128-bit trace id as the 32-hex-digit string Tempo's search expects: a plain str()/hex() would drop leading zero nibbles. The Counter registers in the default global registry at import time, so both this module and /metrics see the identical object with no wiring.");

// ===== SECTION 06 — DEPLOY ========================================================
divider("06", "Deploy.", "Compose, to minikube, to OpenShift Local.");

diagram("THE RUNTIME PROGRESSION", "Three tiers, one contract",
  "00-tier-progression",
  "Figure 0.2. Three tiers, one contract: Compose now, minikube and CRC later.",
  "Docker Compose is the fastest inner loop, used throughout every chapter in this deck; minikube (docker driver + containerd runtime) is where the Part 4 backplane chart runs as a real Kubernetes Deployment; OpenShift Local is a separate appendix chapter, not a variant tucked into the minikube chapter.");

content("DEPLOYING PYTHON: THE OPENSHIFT PATH", "A Docker-strategy BuildConfig, because Python has no S2I builder of its own",
  ["Quarkus gets a binary S2I BuildConfig quarkus-openshift generates automatically; Python has no equivalent, so build-images.sh assembles a throwaway build-context directory mirroring the Containerfile's expected COPY paths and hands it to `oc start-build --from-dir` against a Docker-strategy BuildConfig.",
   "Both builds push an ImageStream tag the Helm chart deploys by name: no registry credentials, no `docker push`, no host container engine touched at any point.",
   "The image itself still runs under `restricted-v2` with no fixed UID: OpenShift assigns an arbitrary UID from the namespace's own range on admission, and the project's UBI-based Python image already tolerates that with no rebuild."],
  "Python's build path is structurally different from the Quarkus one because there's no S2I builder image for it, not because anyone chose a harder path by preference. The throwaway build-context directory exists to mirror the exact repo-root-relative paths the Containerfile's COPY lines expect, including the shared AsyncAPI contract and the schema-extraction script, none of which live inside python/ itself.");

diagram("ONE CONTRACT, TWO STACKS: CONVERGING ON IDENTICAL FRAMES", "Two different mechanisms, one file, no cross-reading",
  "11-contract-to-identical-frames",
  "Figure 11.1. One contract reaches two stacks by two different mechanisms, and verify.sh proves they converge on the same frame.",
  "Quarkus keeps a hand-kept HandlingEvent record checked by a contract test; Python generates its model at build time with datamodel-codegen. Neither stack reads the other's source: verify.sh's cross-stack agreement step is what actually proves convergence, asserting identical field values even though JSON key order differs between Jackson and Pydantic (which is fine; it's not part of the contract).");

content("201 · CLOSE", "One contract, one Python build, from laptop to OpenShift",
  ["The Python build covered the full arc: the native-websockets endpoint over FastAPI's bundled support, four connection concerns, a three-mode backplane, a second wire encoding, the test/debug/observability toolbox, and deploy through OpenShift Local.",
   "For the same build on Quarkus WebSockets Next, see the 201-Quarkus companion: same contract, same close codes, same backplane modes, a structurally different S2I build path on OpenShift.",
   "For the ideas and advantage case at architect altitude, why WebSockets over polling, why one contract across two stacks, see the 101 deck."],
  "This is the deck's actual closing slide. If a question goes past just-enough-code depth, the direct answer is usually 'open the file this slide named': every code slide in this deck points at a real path under examples/, runnable today. If the question is about the Quarkus side specifically, the 201-Quarkus companion covers the same ground stack-for-stack.");

// ===============================================================================
// APPENDIX
// ===============================================================================
inAppendix = true;

divider("APP", "Appendix", "The model-generation pipeline, the edge cases, the test scripts, and the version matrix.",
  "Reference material: the datamodel-codegen pipeline as a shell script, a deeper look at the maxsize=0 backpressure behavior, Kafka's dedup-by-eventId mechanism, the Newman and k6 scripts behind the test pyramid, the drift-gate pipeline figure, and the version matrix this deck's version claims are checked against.");

code("APPENDIX · THE MODEL-GENERATION PIPELINE", "generate-models.sh: extract the schema, then run datamodel-codegen",
  "bash",
  ["#!/usr/bin/env bash",
   "# examples/part3-handling-events/python/scripts/generate-models.sh",
   "SCHEMA=\"$REPO_ROOT/build/handling-event.schema.json\"",
   "",
   "python3 -I \"$REPO_ROOT/scripts/extract-message-schema.py\" \"$SCHEMA\"",
   "",
   "cd \"$PYTHON_DIR\"",
   "uv run datamodel-codegen \\",
   "  --input \"$SCHEMA\" \\",
   "  --input-file-type jsonschema \\",
   "  --output app/models_generated.py \\",
   "  --output-model-type pydantic_v2.BaseModel \\",
   "  --target-python-version 3.15 \\",
   "  --use-schema-description \\",
   "  --disable-timestamp \\",
   "  --formatters black isort",
   "",
   "# pyproject.toml [dependency-groups].dev",
   "# datamodel-code-generator>=0.86.0"],
  "examples/part3-handling-events/python/scripts/generate-models.sh + pyproject.toml: regenerated on every build, output gitignored",
  "datamodel-code-generator's own AsyncAPI input support is unreliable against this document, which is exactly why extract-message-schema.py exists first: it inlines the HandlingEventType/Location/Money $refs into one self-contained Draft 2020-12 document that datamodel-codegen consumes cleanly. app/models_generated.py is gitignored and regenerated by the Containerfile on every build; never hand-edited, by convention enforced only by the file's own generated-by comment.");

code("APPENDIX · THE maxsize=0 SETTING, DEEPER", "asyncio.Queue(maxsize=0) means unbounded, the opposite of the intuitive reading",
  LANG_PY,
  ["# examples/part4-connection/python/app/outbound.py",
   "QUEUE_MAXSIZE = int(os.environ.get(\"OUTBOUND_QUEUE_MAXSIZE\", \"32\"))",
   "",
   "class OutboundQueue:",
   "    def __init__(self, maxsize: int = QUEUE_MAXSIZE, policy: str = BACKPRESSURE_POLICY) -> None:",
   "        if policy not in (\"close\", \"drop\"):",
   "            raise ValueError(f\"unknown OUTBOUND_BACKPRESSURE_POLICY: {policy!r}\")",
   "        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)",
   "        self._policy = policy",
   "",
   "    def enqueue(self, frame: str) -> None:",
   "        try:",
   "            self._queue.put_nowait(frame)",
   "        except asyncio.QueueFull:",
   "            self._on_backpressure(f\"outbound queue full (maxsize={self._queue.maxsize})\")"],
  "examples/part4-connection/python/app/outbound.py: OUTBOUND_QUEUE_MAXSIZE=0 silently disables every bound this class exists to provide",
  "asyncio.Queue's own stdlib semantics: maxsize <= 0 means the queue size is infinite. An operator setting OUTBOUND_QUEUE_MAXSIZE=0 expecting 'zero capacity, reject everything' instead gets 'no capacity limit at all': put_nowait never raises QueueFull, _on_backpressure never fires, and this class's entire reason for existing is silently defeated. The fix this appendix recommends for any production fork: validate maxsize > 0 at construction, don't trust the stdlib's own permissive default.");

code("APPENDIX · DEDUP-BY-eventId", "At-least-once delivery, exactly-once effect, on the Kafka backplane",
  LANG_PY,
  ["# examples/part4-backplane/python/app/backplane/kafka_backplane.py",
   "# Ch16: the topic can double-deliver on a replay burst overlapping",
   "# the always-on live consumer -- the client resolves this by deduping",
   "# on eventId, not by trusting delivery to be exactly-once at the source.",
   "index = next((i for i, e in enumerate(history) if e.eventId == after_event_id), None)",
   "to_replay = history[index + 1 :] if index is not None else history",
   "for event in to_replay:",
   "    yield event",
   "# consumer position is now at (or past) the snapshotted end offsets --",
   "# the live loop below picks up exactly where replay left off, with no",
   "# gap and no re-delivery at the SERVER side.",
   "async for record in consumer:",
   "    if record.key.decode(\"utf-8\") == booking_id:",
   "        yield HandlingEvent.model_validate_json(record.value)"],
  "examples/part4-backplane/python/app/backplane/kafka_backplane.py: the server-side half; the client's eventId dedup is the other half of the contract",
  "The buffer-then-snapshot approach closes the server-side gap between replay and live delivery with no double-send from Kafka itself, but PROTOCOL.md still documents a replay burst and the always-on live consumer as able to double-deliver the same event under some timing. The resolution is client-side: dedupe on eventId, the same discipline the project's idempotent-consumer pattern uses everywhere else a redelivery is possible.");

code("APPENDIX · NEWMAN: FUNCTIONAL HTTP AROUND THE SOCKET", "The HTTP seam and close codes a WebSocket client can't exercise",
  "json · newman",
  ["// examples/part6-testing/newman/collection.json (item names)",
   "Health > python-a /healthz -> 200 {status: ok}",
   "Health > python-b /healthz -> 200 {status: ok}",
   "Inject - Python (native websockets + FastAPI) >",
   "  python-a inject schema-valid HandlingEvent -> 202",
   "Inject - Python (native websockets + FastAPI) >",
   "  python-a inject malformed body (bad bookingId + eventType) -> 422",
   "Inject - Quarkus (WebSockets Next) >",
   "  quarkus-a inject schema-valid HandlingEvent -> 202",
   "Inject - Quarkus (WebSockets Next) >",
   "  quarkus-a inject malformed body (invalid eventType) -> 400"],
  "examples/part6-testing/newman/collection.json. The HTTP surfaces: health probes and the inject endpoint, both stacks",
  "Newman's whole reason for being in this stack: it only ever exercises HTTP, the health probes and the backplane's inject endpoint, because those are REST surfaces a Postman-style collection can drive directly. Everything WebSocket-shaped (the upgrade itself, a close code, a binary frame) is explicitly out of Newman's reach and falls to verify.sh/lib.sh and the Python close-code probe instead: that division of labor is the testing chapter's test-pyramid functional tier.");

code("APPENDIX · k6 WS SMOKE LOAD", "A gated CI check, not the benchmark: one VU, both encodings, one iteration",
  "javascript · k6",
  ["// examples/part5-performance/k6/smoke.js",
   "// DRQ-023/DRQ-027 -- GATED k6 smoke load for Part 5's JSON-vs-Protobuf",
   "// example. SMOKE-level by design: a handful of VUs, one short",
   "// iteration each, no ramping -- a fast CI gate, not a load test.",
   "import ws from \"k6/ws\";",
   "import { check } from \"k6\";",
   "",
   "export const options = {",
   "  scenarios: {",
   "    smoke: { executor: \"per-vu-iterations\", vus: 3, iterations: 1 },",
   "  },",
   "};",
   "// Each VU opens the SAME channel TWICE in one iteration:",
   "//   1. offering handling-events.v1+json -- asserts 101, echoed",
   "//      subprotocol, 3 TEXT frames, well-formed JSON.",
   "//   2. offering handling-events.v1+protobuf -- asserts 101, echoed",
   "//      subprotocol, 3 BINARY frames (ArrayBuffer), non-empty."],
  "examples/part5-performance/k6/smoke.js: pinned to k6 2.3.0, 3 VUs, 1 iteration each, gated on every PR",
  "benchmark.js (k6/benchmark.js) is the comparative, local-only sibling this script is not. The README draws the line directly: smoke.js is fast and deterministic, gated in CI; benchmark.js's absolute throughput numbers are host-dependent, which would make a flaky CI threshold if gated the same way. k6/ws (gorilla/websocket-backed) dispatches a distinct binaryMessage event for binary frames, confirmed against the pinned k6 2.3.0 source. No need for k6/experimental/websockets here.");

diagram("APPENDIX · THE DRIFT GATE", "Four independent CI checks, one merge-allowed decision",
  "11-drift-gate-pipeline",
  "Figure 11.2. The drift gate: four independent checks, and a merge only happens when all four agree the contract still holds.",
  "A PR editing contracts/asyncapi.yaml fans out to four jobs: validate (asyncapi validate), breaking (asyncapi diff -t all plus a jq filter, its own breaking classification misses payload-schema changes, so the filter closes that gap itself), drift (extract the schema, regenerate the Python model, run both conformance tests), and the examples matrix (verify.sh per discovered example, three retries). All four green is the only path to merge-allowed.");

{
  const s = S();
  addContentTitle(s, "APPENDIX · VERSION MATRIX", "Pinned, surveyed versions behind this deck's claims");
  addStatusTable(s, [
    { code: "Python", name: "3.15.0", purpose: "Current stable; matches every example's requires-python" },
    { code: "websockets", name: ">=17.2", purpose: "pyproject.toml pin across Part 3-6; serve()'s own default is compression=\"deflate\"" },
    { code: "FastAPI", name: ">=0.146.0", purpose: "HTTP/lifecycle surface, side by side with the native WS listener" },
    { code: "PyJWT", name: "2.15.1", purpose: "Ch17 JWT auth, HS256 shared-secret" },
    { code: "aiokafka", name: ">=0.14.0", purpose: "Ch16 Kafka backplane; Kafka itself pinned 4.3.1 (KRaft)" },
    { code: "Redis", name: "8.10.2-alpine", purpose: "Ch18 Redis Pub/Sub backplane (redis.asyncio client)" },
    { code: "k6 / Newman", name: "2.3.0 / 6.2.3", purpose: "Load smoke + functional HTTP, both pinned and gated in CI" },
  ], { colW: [2.2, 2.0, 7.89] });
  addNotes(s, "Every version here is checked against _plans/version-matrix.md, which is itself a live-surveyed document dated 2026-10-19 for the rows this deck cites, not a representative placeholder. One step-back called out rather than glossed over: on OpenShift Local/CRC specifically, the AMQ Streams operator caps Kafka at 4.2.0 (the compose/minikube path runs 4.3.1), a recorded floor tied to the operator's own supported-version list, not a regression in this project's code. Wire behavior is identical across both versions.");
}


/* --- Scan to explore (QR codes) --- */
{
  const s = S();
  addContentTitle(s, "SCAN TO EXPLORE", "Take it with you");

  // Left QR: the site
  s.addImage({ path: `${ASSETS}/qr-websockets-site.png`, x: 2.30, y: 1.78, w: 3.10, h: 3.10 });
  s.addText("The site", { x: 1.55, y: 4.98, w: 4.60, h: 0.40,
    fontFace: FONT.title, fontSize: 18, bold: true, color: COLOR.ink, align: "center", valign: "middle" });
  s.addText("Chapters, the AsyncAPI contracts, and both-stack runnable examples", { x: 1.45, y: 5.40, w: 4.80, h: 0.72,
    fontFace: FONT.body, fontSize: 13, italic: true, color: COLOR.caption, align: "center", valign: "top" });
  s.addText("patterncatalyst.github.io/api-patterns-and-practices-websockets", { x: 1.45, y: 6.12, w: 4.80, h: 0.32,
    fontFace: FONT.mono, fontSize: 10, color: COLOR.red, align: "center", valign: "middle" });

  // Right QR: the hub
  s.addImage({ path: `${ASSETS}/qr-hub.png`, x: 7.93, y: 1.78, w: 3.10, h: 3.10 });
  s.addText("Workshops & Tutorials", { x: 7.18, y: 4.98, w: 4.60, h: 0.40,
    fontFace: FONT.title, fontSize: 18, bold: true, color: COLOR.ink, align: "center", valign: "middle" });
  s.addText("The whole series: every workshop, tutorial, and deck in one place", { x: 7.08, y: 5.40, w: 4.80, h: 0.72,
    fontFace: FONT.body, fontSize: 13, italic: true, color: COLOR.caption, align: "center", valign: "top" });
  s.addText("patterncatalyst.github.io/patterncatalyst-workshops-tutorials-list", { x: 7.08, y: 6.12, w: 4.80, h: 0.32,
    fontFace: FONT.mono, fontSize: 9, color: COLOR.red, align: "center", valign: "middle" });

  addNotes(s, "This is the Python implementation deck, so the left code takes you to the runnable Python example and contract, the right to the whole series. On the left, the site: the chapters, the AsyncAPI contracts, and the runnable both-stack examples, all public. On the right, the Workshops and Tutorials hub: every workshop, tutorial, and deck in the series in one place. Scan whichever is useful; both are on the Pattern Catalyst GitHub organization.");
}


pres.writeFile({ fileName: OUT })
  .then(p => console.log("WROTE", p, "slides:", pageNum, "main:", mainCount, "appendix:", appendixCount))
  .catch(e => { console.error(e); process.exit(1); });
