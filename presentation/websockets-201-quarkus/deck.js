// deck.js — "WebSockets with Quarkus" — 201 (Quarkus WebSockets Next).
// Companion deck to the published site: Part 3 (the endpoint) through Part 7
// (deploy), Quarkus-only depth. Every code slide transcribes a real file
// under examples/part{3,4,5,6}-*/quarkus/; every diagram slide uses a PNG
// rendered from assets/diagrams/<name>.svg and, where the chapter already
// names one, the chapter's own published figure caption.
// Red Hat house style, 16:9. Build: node deck.js

"use strict";

const H = require("./deck-helpers.js");
const {
  COLOR, FONT, W, PNG, ASSETS,
  newDeck, addFooter, addContentTitle, addBullets, addTwoColBullets,
  addStatusTable, addCaption, addCodeSlide, addDiagramSlide, addSectionDivider, addNotes,
} = H;

const OUT = "WebSockets_201_Quarkus-r1.0.pptx";
const REV = "r1.0";
const LANG = "Java · Quarkus WebSockets Next";

const pres = newDeck();
pres.title = "WebSockets with Quarkus — 201 (Quarkus WebSockets Next)";
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
function code(eyebrow, title, codeLines, caption, notes, opts) {
  const s = S();
  addCodeSlide(s, eyebrow, title, LANG, codeLines, caption, opts || {});
  addNotes(s, notes);
  return s;
}
function statusTable(eyebrow, title, rows, notes, opts) {
  const s = S();
  addContentTitle(s, eyebrow, title);
  addStatusTable(s, rows, opts || {});
  addNotes(s, notes);
  return s;
}

// ===== 1. COVER ================================================================
{
  const s = pres.addSlide();
  pageNum += 1; mainCount += 1;
  s.background = { color: COLOR.white };
  try { s.addImage({ path: `${ASSETS}/cover-panel.png`, x: 0, y: 0, w: W, h: 7.5 }); } catch (e) {}
  s.addText("WEBSOCKETS WITH QUARKUS · 201", { x: 6.00, y: 1.98, w: 6.90, h: 0.34,
    fontFace: FONT.title, fontSize: 13, bold: true, color: COLOR.red, charSpacing: 5, align: "left", valign: "middle" });
  s.addText([{ text: "Building the handling-event", options: { breakLine: true } },
             { text: "feed on WebSockets Next" }], {
    x: 5.95, y: 2.42, w: 6.95, h: 2.00, fontFace: FONT.title, fontSize: 34, bold: true, color: COLOR.ink, align: "left", valign: "top" });
  s.addText("The Quarkus-side implementation of this site's shipping handling-events feed: the endpoint, connection hardening, the backplane, binary performance, and operating it.",
    { x: 6.00, y: 5.10, w: 6.80, h: 0.75, fontFace: FONT.body, fontSize: 16, italic: true, color: COLOR.caption, align: "left", valign: "top" });
  s.addText(REV, { x: 11.85, y: 5.85, w: 0.95, h: 0.30, fontFace: FONT.mono, fontSize: 11, color: COLOR.caption, align: "right", valign: "middle" });
  try { s.addImage({ path: `${ASSETS}/logo-candidate-2.png`, x: 11.10, y: 6.80, w: 1.55, h: 0.37 }); } catch (e) {}
  addNotes(s, "This is the 201-Quarkus companion deck — the WebSockets Next implementation of the one channel this site builds everywhere: operations.receiveHandlingEvent from contracts/asyncapi.yaml, one connection per booking, server push only. It follows the chapters in build order, Part 3 through the deploy appendix, and every code slide is transcribed from a real file under examples/. The Python sibling app exists throughout and is named where the two stacks differ in a way that matters; this deck does not re-teach that side.");
}

// ===== 2. AGENDA ================================================================
{
  const s = S();
  addContentTitle(s, "201 · QUARKUS WEBSOCKETS NEXT", "Six sections, same order the chapters build in");
  addTwoColBullets(s,
    ["01 — The Quarkus Endpoint: @OnOpen, Multi, the record, the contract test (Ch08)",
     "02 — Connection Concerns: backpressure, errors, heartbeats, auth (Ch12/13/14/17)",
     "03 — Reconnect and the Backplane: stateless, Kafka, Redis, scale-out (Ch15/16/18)"],
    ["04 — Performance: Protobuf, field numbers, the throughput levers (Ch19/20)",
     "05 — Testing, Debugging, Observability (Ch21/22/23)",
     "06 — Deploy: Compose, minikube, OpenShift Local",
     { text: "Appendix — minikube/CRC manifests, the version matrix, lifecycle edge cases", muted: true }]);
  addNotes(s, "Six sections, in the order the chapters actually build the feed: get an endpoint open and pushing, harden the one connection, cross instances with a backplane, make the wire cheaper, prove and watch all of it, then run it somewhere real. Cross-references in the notes are by concept — the channel, the close code, the backplane mode — never by slide number, so trimming a section for time doesn't break a reference elsewhere in the deck.");
}

// ===== SECTION 01 — THE QUARKUS ENDPOINT (Ch08) ================================
divider("01", "The Quarkus Endpoint", "@OnOpen, a Multi, and the one operation the contract defines.",
  "Opens on the simplest possible version of the channel: one @WebSocket class, one @OnOpen method, no client-to-server message at all because the contract never defines one. Everything in sections 02-05 is this same endpoint, hardened one concern at a time — nothing here gets thrown away later.");

diagram("THE QUARKUS ENDPOINT · PART 3 AT A GLANCE", "One channel, two independently built stacks",
  "part3-architecture",
  "Neither stack reads the other's source; both push the identical RECEIVE/LOAD/CUSTOMS sequence, verified live by verify.sh.",
  "Quarkus on :8080, Python/FastAPI on :8081 (plus its own :8082 health port) — same contract (contracts/asyncapi.yaml), same shared fixture (fixtures/handling-events.json), same wire order. Quarkus gets there with WebSockets Next's @OnOpen-returns-Multi<HandlingEvent>; Python hand-keeps a Pydantic model to the same contract schema. The point this diagram makes before any code appears: parity is proven by running both stacks against the same fixture and diffing the frames, not by one stack importing the other's types.");

code("THE QUARKUS ENDPOINT · THE CLASS", "One @WebSocket class, one @OnOpen, a Multi drives the wire",
  ["@WebSocket(path = \"/ws/v1/bookings/{bookingId}/handling-events\")",
   "public class HandlingEventWebSocket {",
   "",
   "    @Inject",
   "    HandlingEventFeed feed;",
   "",
   "    @OnOpen",
   "    public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {",
   "        Log.infof(\"handling-events connection opened for bookingId=%s; \" +",
   "                  \"replaying %d fixture event(s)\",",
   "                bookingId, feed.events().size());",
   "        return Multi.createFrom().iterable(feed.events());",
   "    }",
   "}"],
  "examples/part3-handling-events/quarkus/src/main/java/.../handlingevents/HandlingEventWebSocket.java",
  "This is the whole endpoint — no onClose, no onTextMessage, because the contract's operations.receiveHandlingEvent declares exactly one direction. Returning Multi<HandlingEvent> directly from @OnOpen establishes a persistent server-push stream for the connection's lifetime; WebSockets Next serializes each emitted item to JSON and sends it as one text frame, in emission order. The fixture replay here is a stand-in for a live event source a later chapter swaps in — the endpoint shape doesn't change when that happens.");

diagram("THE QUARKUS ENDPOINT · THE LIFECYCLE", "One callback implemented, because the contract declares one operation",
  "08-ws-endpoint-lifecycle",
  "Figure 8.1 — one lifecycle callback implemented, because the contract declares one operation on this channel.",
  "@OnTextMessage and @OnClose are both absent from this version because the channel is receive-only per the contract, and no per-connection state is kept yet. connection.sendText exists on WebSocketConnection and is available, but this handler never calls it directly; the Multi return type handles serialization and the send loop on its own. Section 02 is exactly the slides where onTextMessage, onClose, and an explicit sendText all show up, once the connection actually needs guarding.");

code("THE QUARKUS ENDPOINT · MULTI VS. EXPLICIT SENDTEXT", "Two ways to drive the wire — the contract doesn't force a choice",
  ["// part3 — HandlingEventWebSocket#onOpen: the Multi IS the wire",
   "@OnOpen",
   "public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {",
   "    return Multi.createFrom().iterable(feed.events());",
   "}",
   "",
   "// part4-connection — OutboundBackpressureGuard#sendOne: explicit sendText,",
   "// because this version needs to COUNT outstanding sends per connection",
   "pending.incrementAndGet();",
   "return connection.sendText(event)",
   "        .ifNoItem().after(sendTimeout).failWith(",
   "                () -> new TimeoutException(\"sendText exceeded \" + sendTimeout))",
   "        .onItemOrFailure().transformToUni((v, failure) -> {",
   "            pending.decrementAndGet();",
   "            return Uni.createFrom().voidItem();",
   "        });"],
  "HandlingEventWebSocket.java (part3) / OutboundBackpressureGuard.java (part4-connection)",
  "Returning a Multi is the right call when WebSockets Next's own per-item write loop is enough; explicit connection.sendText is the right call the moment something needs to observe or bound each individual send — here, an outstanding-sends counter for Chapter 12's backpressure guard. Both run under the same @OnOpen-scoped subscription Quarkus itself manages; the guard's Javadoc is explicit about why a Uni this code subscribes to manually, rather than returns, would run its completion on a raw Vert.x thread after the connection's @SessionScoped context had already torn down.");

code("THE QUARKUS ENDPOINT · THE RECORD", "HandlingEvent mirrors the contract schema field-for-field",
  ["@JsonInclude(JsonInclude.Include.NON_NULL)",
   "public record HandlingEvent(",
   "        String eventId,",
   "        String bookingId,",
   "        String cargoId,",
   "        HandlingEventType eventType,",
   "        String location,",
   "        Instant occurredAt,",
   "        Instant registeredAt,",
   "        String voyageNumber,",
   "        String amount) {",
   "}"],
  "examples/part3-handling-events/quarkus/src/main/java/.../handlingevents/HandlingEvent.java",
  "Jackson — pulled in transitively by quarkus-websockets-next, no extra dependency — serializes this record to the JSON text frame; @JsonInclude(NON_NULL) omits voyageNumber/amount entirely when absent, matching the contract's required list exactly. location and amount are plain Strings, not nested objects, because the contract defines both as type: string with a pattern (a UN/LOCODE, a decimal string like \"125.00\") — modeling amount as a float would be the wrong call for money on the wire.");

diagram("THE QUARKUS ENDPOINT · THE PUSH FLOW", "One Multi, three items, three ordered frames",
  "08-multi-push-flow",
  "Figure 8.2 — one Multi, three items, three ordered text frames; completion of the stream does not close the connection.",
  "Worth saying explicitly because it surprises people coming from HTTP: the Multi completing after the third fixture event does NOT close the WebSocket. The connection stays open with nothing left to push until a later chapter gives it something to push (live events, or a reconnect replay). Completion-of-stream and close-of-connection are two separate events on this channel, and conflating them is a common first mistake.");

content("THE QUARKUS ENDPOINT · WHY WEBSOCKETS NEXT", "Not legacy quarkus-websockets",
  ["WebSockets Next is Quarkus's newer, Vert.x-native WebSocket extension — the one with @OnOpen/@OnTextMessage/@OnBinaryMessage annotations, Multi/Uni return types, and a CDI-scoped WebSocketConnection, not the older JSR 356-style quarkus-websockets.",
   "It's the extension every example in this site uses on the Quarkus side; the two are not interchangeable and this deck never mixes them.",
   "OpenConnections, UserData, and CloseReason — all used in section 02 — are WebSockets Next types with no equivalent in the legacy extension."],
  "Name this distinction early so nobody searches the wrong Quarkus guide mid-build: quarkus-websockets (legacy) predates WebSockets Next and has a different, more JSR-356-shaped API. Every class this deck transcribes — HandlingEventWebSocket, OutboundBackpressureGuard, HeartbeatLivenessSweep — imports from io.quarkus.websockets.next, not the legacy package.");

code("THE QUARKUS ENDPOINT · THE CONTRACT-CONFORMANCE TEST", "Every emitted event validates against the generated schema",
  ["@Test",
   "void fixtureEventsValidateAgainstContractSchema() {",
   "    List<HandlingEvent> events = loadFixtureEvents();",
   "    assertFalse(events.isEmpty(), \"fixture must contain at least one event\");",
   "",
   "    for (HandlingEvent event : events) {",
   "        JsonNode node = MAPPER.valueToTree(event);",
   "        Set<ValidationMessage> errors = schema.validate(node);",
   "        assertTrue(errors.isEmpty(),",
   "                () -> \"schema violations for \" + event.eventId() + \": \" + errors);",
   "    }",
   "}"],
  "examples/part3-handling-events/quarkus/src/test/java/.../HandlingEventContractTest.java",
  "Plain JUnit, no @QuarkusTest — this exercises serialization of the production record types, not the running endpoint, so there's no container to boot. It validates against build/handling-event.schema.json, a generated artifact extracted from contracts/asyncapi.yaml (scripts/extract-message-schema.py) — the same classpath fixture HandlingEventFeed loads at runtime, so the test and the app agree on what 'the emitted events' are. This is the Quarkus half of the pyramid's bottom tier; section 05's test slide shows the full pyramid.");

// ===== SECTION 02 — CONNECTION CONCERNS (Ch12/13/14/17) =========================
divider("02", "Connection Concerns", "Backpressure, errors, heartbeats, and authentication — one connection, hardened.",
  "part4-connection forks part3's endpoint and adds the four concerns a single long-lived connection actually needs: who's allowed to open it (Ch17), what happens when it sends faster than the client reads (Ch12), what a client frame outside the contract gets back (Ch13), and how a silently-dead peer gets detected (Ch14). Same channel, same fixture, more guardrails.");

diagram("CONNECTION CONCERNS · PART 4 AT A GLANCE", "The same channel, now with an auth gate and two reject paths",
  "part4-connection-architecture",
  "Same shared JWT secret, same close codes on both stacks — verify.sh asserts a client can't tell them apart.",
  "Both stacks gain the identical shape: an auth gate at the handshake (Ch17), a guarded outbound path to the fixture replay (Ch12), a reject path for any client frame outside the contract (Ch13, close 4400), and a heartbeat loop pairing an auto-ping with an idle-timeout on Quarkus or ping_interval/ping_timeout on Python (Ch14). Nothing about the public path changes — a well-behaved, authenticated client sees exactly the same three-event replay as part3.");

diagram("CONNECTION CONCERNS · BACKPRESSURE", "A bounded outbound buffer between the producer and the socket",
  "12-outbound-buffer-policy",
  "Figure 12.2 — the bounded outbound buffer sitting between the producer and the socket write, and the two policies for what happens once one of the two trigger conditions fires.",
  "Two independent signals trip the policy: too many outstanding sends at once (a sustained rate mismatch — the producer outruns the client's drain rate), or a single sendText call exceeding example.backpressure.send-timeout (the client stopped reading entirely, so not even one frame gets out). WebSockets Next has no outbound queue to bound directly — max-pending-messages governs INBOUND messages only — so OutboundBackpressureGuard tracks outstanding sendText calls itself, mirroring the Python sibling's bounded asyncio.Queue.");

code("CONNECTION CONCERNS · THE BACKPRESSURE GUARD", "Count outstanding sends; apply CLOSE or DROP when the bound trips",
  ["@ApplicationScoped",
   "public class OutboundBackpressureGuard {",
   "",
   "    public enum Policy { CLOSE, DROP }",
   "",
   "    @ConfigProperty(name = \"example.backpressure.max-pending-sends\", defaultValue = \"32\")",
   "    int maxPendingSends;",
   "",
   "    @ConfigProperty(name = \"example.backpressure.send-timeout\", defaultValue = \"5s\")",
   "    Duration sendTimeout;",
   "",
   "    private Uni<Void> applyPolicy(WebSocketConnection connection, String bookingId,",
   "            AtomicBoolean closeRequested, String detail) {",
   "        if (policy == Policy.DROP) {",
   "            Log.warnf(\"outbound backpressure %s: %s — dropping event\", bookingId, detail);",
   "            return Uni.createFrom().voidItem();",
   "        }",
   "        if (closeRequested.compareAndSet(false, true)) {",
   "            return connection.close(new CloseReason(CloseCodes.SLOW_CONSUMER,",
   "                    \"slow consumer: outbound buffer exceeded\"));",
   "        }",
   "        return Uni.createFrom().voidItem();",
   "    }",
   "}"],
  "examples/part4-connection/quarkus/src/main/java/.../connection/OutboundBackpressureGuard.java",
  "Default threshold (32) matches the Python sibling's OUTBOUND_QUEUE_MAXSIZE — same policy, same number, two independent implementations. compareAndSet(false, true) guards against double-closing when multiple in-flight sends trip the condition concurrently; only the first one issues the close. The default policy is CLOSE, not DROP — an unbounded count of slow clients each holding outstanding sends is a resource-exhaustion path, so closing the slow one is the safer default even though it drops the rest of that connection's replay.");

content("CONNECTION CONCERNS · CLOSE VS. DROP", "Picking a backpressure policy is a correctness decision, not a tuning knob",
  ["CLOSE (default): close the connection with 4290 SLOW_CONSUMER and stop sending the rest. Safer by default — an unbounded number of slow clients each holding outstanding sends is a resource-exhaustion path.",
   "DROP: skip the event that would exceed the threshold, log a warning, keep the connection open. Exists to demonstrate the trade-off, not because it fits this channel's semantics — a missed HandlingEvent is a correctness problem here, not a supersede-by-the-next-update one.",
   "The right default depends on what a missed message means: a live price tick tolerates DROP; a customs HandlingEvent does not."],
  "Push on this distinction if there's time for one question: DROP is in this codebase as a documented trade-off, not a recommendation for this channel. A feed where only the latest value matters (Ch15's stateless-reconnect framing in section 03 makes the same distinction from the other direction) is exactly the shape where DROP is the right call; a feed where every event is a discrete fact never fits it.");

diagram("CONNECTION CONCERNS · ERRORS VS. 1006", "The deliberate envelope-then-close, next to the one failure mode no code can carry",
  "13-error-flow-vs-1006",
  "Figure 13.2 — the deliberate envelope-then-close sequence this chapter builds, next to the one failure mode no close code can ever carry: a peer that vanished before any handshake could complete.",
  "Left path: the channel defines no client-to-server message, so ANY client frame is a protocol error — the server sends an ErrorEnvelope first, while the connection is still open, then closes with 4400 BAD_REQUEST. Right path: a killed process or a pulled cable leaves no FIN and no close frame at all; the client's own runtime synthesizes 1006 locally. 1006 is a reserved RFC 6455 value a server must never put in an actual close frame — it only ever shows up as a local, client-side observation that nothing arrived.");

code("CONNECTION CONCERNS · CLOSE CODES AND THE ERROR ENVELOPE", "A structured reason in-band, then the cheap close-code signal",
  ["public final class CloseCodes {",
   "    public static final int AUTH_FAILURE = 1008;            // Ch17, at @OnOpen",
   "    public static final int BAD_REQUEST = 4400;              // Ch13, app-range",
   "    public static final int SLOW_CONSUMER = 4290;             // Ch12, app-range",
   "    public static final int UNEXPECTED_SERVER_ERROR = 1011;",
   "    public static final int LIVENESS_TIMEOUT = 4408;          // Ch14, app-range",
   "}",
   "",
   "@JsonInclude(JsonInclude.Include.NON_NULL)",
   "public record ErrorEnvelope(ErrorBody error) {",
   "    public record ErrorBody(String code, String message) { }",
   "    public static ErrorEnvelope badRequest(String message) {",
   "        return new ErrorEnvelope(new ErrorBody(\"BAD_REQUEST\", message));",
   "    }",
   "}"],
  "CloseCodes.java / ErrorEnvelope.java — examples/part4-connection/quarkus/src/main/java/.../connection/",
  "4400 and 4290 sit in the 4000-4999 application range specifically so they can never be confused with an RFC 6455 standard code. ErrorEnvelope is only ever sent for BAD_REQUEST, the one case with a specific offending message worth annotating; the other three codes close before any data has streamed (auth, backpressure) or after the connection is already in an unknown state (an unmapped exception) — there's no protocol moment where an envelope would make sense for those, so the close code alone is the signal a reconnect loop keys off.");

diagram("CONNECTION CONCERNS · THE IDLE-TIMEOUT TRAP", "The server's own ping keeps resetting its own idle clock",
  "14-idle-timeout-trap",
  "Figure 14.1 — the idle-timeout trap (the server's own ping keeps resetting its own idle clock) versus the pong-tracked sweep that actually detects a silent peer.",
  "The gotcha to dwell on: Vert.x's HTTP idle-timeout resets on any read OR write activity, and the server's own outbound auto-ping is write activity on that same connection — so a peer that never answers a single ping never trips idle-timeout, because the server keeps resetting its own clock every auto-ping-interval regardless of whether the peer responds. Confirmed live against this exact example (examples/part4-connection/verify.sh's Ch14 stage) — idle-timeout alone cannot distinguish healthy from silently dead once auto-ping is on.");

code("CONNECTION CONCERNS · THE LIVENESS SWEEP", "A scheduled bean, not endpoint logic — it needs every connection at once",
  ["@ApplicationScoped",
   "public class HeartbeatLivenessSweep {",
   "",
   "    @Inject",
   "    OpenConnections openConnections;",
   "",
   "    @ConfigProperty(name = \"example.heartbeat.liveness-timeout\", defaultValue = \"45s\")",
   "    Duration livenessTimeout;",
   "",
   "    @Scheduled(every = \"${example.heartbeat.sweep-interval:5s}\",",
   "               concurrentExecution = ConcurrentExecution.SKIP)",
   "    void sweep() {",
   "        Instant now = Instant.now();",
   "        for (WebSocketConnection c : openConnections.findByEndpointId(",
   "                HandlingEventConnectionWebSocket.ENDPOINT_ID)) {",
   "            if (!c.isOpen() || Boolean.TRUE.equals(c.userData().get(CLOSE_REQUESTED))) continue;",
   "            Duration silentFor = Duration.between(lastSeen(c), now);",
   "            if (silentFor.compareTo(livenessTimeout) > 0) {",
   "                c.userData().put(CLOSE_REQUESTED, true);",
   "                c.close(new CloseReason(CloseCodes.LIVENESS_TIMEOUT,",
   "                        \"no pong received within the liveness window\")).subscribe().with(v -> {}, f -> {});",
   "            }",
   "        }",
   "    }",
   "}"],
  "examples/part4-connection/quarkus/src/main/java/.../connection/HeartbeatLivenessSweep.java",
  "Reads live connections straight off the injected OpenConnections registry rather than @Inject WebSocketConnection, because a @Scheduled method runs on its own worker thread with no WebSocket session context — an injected WebSocketConnection field would resolve to whatever connection happens to be active for the current request, meaningless on a scheduler thread. LAST_PONG_AT lives on each connection's UserData, stamped at @OnOpen and on every @OnPongMessage; a peer that never answers a ping simply never updates it.");

diagram("CONNECTION CONCERNS · THE PONG-SWEEP TIMELINE", "From last pong to the close the peer never acknowledges",
  "14-pong-sweep-timeline",
  "Figure 14.2 — the real timeline from last pong to the TCP socket actually closing: detection at the liveness timeout, then up to ten more seconds of closing-handshake grace before onClose observes 1006.",
  "Closing a WebSocket is itself a two-way handshake: the server sends a close frame and waits for the peer's own close frame before tearing down TCP. A peer this sweep has just proven isn't responding won't send that acknowledgment either, so Vert.x forcibly terminates after its own closing-timeout grace (~10s) elapses — confirmed live: onClose sees the connection's final CloseReason as 1006, NOT 4408, because the requested close never completed its handshake. That's standard WebSocket behavior for an unresponsive peer, not a bug in the sweep.");

diagram("CONNECTION CONCERNS · AUTHENTICATE AT THE UPGRADE", "Both stacks accept, then validate as the first thing the handler does",
  "17-auth-upgrade-flow",
  "Figure 17.1 — both stacks accept the handshake, then validate the token as the first thing the handler does, closing 1008 before any fixture frame goes out; Python's process_request hook exists but runs too early to issue that close code.",
  "The token travels as a ?token= query parameter — the contract's servers.local.bindings.ws — because WebSockets Next doesn't parse query parameters for the caller (no @PathParam-style injection for them; the reference guide points at handshakeRequest().query() directly). Missing, malformed, badly signed, and expired tokens are all indistinguishable to an attacker probing the channel, so all four collapse to the identical 1008 AUTH_FAILURE rejection, before a single fixture event is sent — never a distinguishing reason that would help an attacker narrow down which check failed.");

code("CONNECTION CONCERNS · HS256 AT THE HANDSHAKE", "Verify the token; collapse every failure mode to one close code",
  ["public static VerificationResult verify(String token, String secret) {",
   "    if (token == null || token.isBlank()) return VerificationResult.rejected(\"missing token\");",
   "    String[] parts = token.split(\"\\\\.\", -1);",
   "    if (parts.length != 3) return VerificationResult.rejected(\"malformed token\");",
   "    byte[] expected = hmac(parts[0] + \".\" + parts[1], secret);",
   "    byte[] actual = URL_DECODER.decode(parts[2]);",
   "    if (!MessageDigest.isEqual(expected, actual)) return VerificationResult.rejected(\"bad signature\");",
   "    // ... exp claim checked here, see JwtHs256.java",
   "    return VerificationResult.ok(sub == null ? null : sub.toString());",
   "}",
   "",
   "// HandlingEventConnectionWebSocket#onOpen",
   "String token = QueryParams.get(connection.handshakeRequest().query(), \"token\");",
   "JwtHs256.VerificationResult auth = JwtHs256.verify(token, jwtSecret);",
   "if (!auth.valid()) {",
   "    return connection.close(new CloseReason(CloseCodes.AUTH_FAILURE, \"authentication failed\"));",
   "}"],
  "JwtHs256.java / QueryParams.java — examples/part4-connection/quarkus/src/main/java/.../connection/",
  "Not quarkus-smallrye-jwt here — that extension is built around RS256/JWKS and a key-rotation endpoint, the right shape for a multi-service-audience token but overkill for one shared-secret HS256 token. javax.crypto (HMAC-SHA256) plus Jackson, both already present, are the only two things this needs. MessageDigest.isEqual does the signature comparison in constant time, closing a timing-attack side channel a plain byte[].equals would leave open.");

// ===== SECTION 03 — RECONNECT AND THE BACKPLANE (Ch15/16/18) ===================
divider("03", "Reconnect and the Backplane", "What a dropped connection loses, and what a shared broker gets back.",
  "part4-backplane moves from one connection to multiple server instances. Stateless mode (Ch15) is the starting baseline: a gap is lost. Kafka (Ch16) makes the gap replayable from afterEventId. Redis (Ch18) buys live fan-out across instances with no replay at all. Same channel, same fixture seed, three delivery strategies selected by one enum.");

diagram("RECONNECT & BACKPLANE · PART 4-BACKPLANE AT A GLANCE", "Two instances, an inject endpoint, and a mode-selected fan-out path",
  "part4-backplane-architecture",
  "Both stacks implement this identically — PROTOCOL.md is the single source of truth.",
  "verify.sh's own topology: a client connects to instance A, a test harness POSTs an inject onto instance B, and the backplane mode decides whether that event ever reaches A's client. Stateless: lost (no broker, no history). Kafka: replayed after reconnect via afterEventId, deduped by eventId. The inject endpoint (POST /internal/bookings/{bookingId}/handling-events) is not part of the public AsyncAPI contract — an internal/demo surface only, documented in PROTOCOL.md.");

diagram("RECONNECT & BACKPLANE · WHEN STATELESS IS FINE", "A fresh value supersedes a stale one, or a full resync is cheap",
  "15-when-stateless-ok",
  "Figure 15.2 — the decision: stateless reconnect is fine when a fresh value supersedes a stale one or a full resync is cheap, and not enough when every event is individually significant and the feed is the only record of it.",
  "This is the decision this whole section hangs on, stated before any code: a handling-event feed fails the 'stateless is fine' test on all three counts — every event is a discrete billable fact, there's no cheap REST endpoint to re-GET the gap from, and at-least-once delivery matters for an audit trail. That's precisely why Ch16's Kafka-backed mode exists, not because Kafka is the default choice for every WebSocket feed.");

code("RECONNECT & BACKPLANE · STATELESS MODE", "The default — afterEventId is accepted, and ignored",
  ["public enum BackplaneMode { STATELESS, KAFKA, REDIS }",
   "",
   "@ApplicationScoped",
   "public class StatelessBackplane implements Backplane {",
   "",
   "    @Inject",
   "    LocalDelivery localDelivery;",
   "",
   "    @Override",
   "    public List<HandlingEvent> replayFor(String bookingId, String afterEventId) {",
   "        return List.of();   // no history to resume from",
   "    }",
   "",
   "    @Override",
   "    public void publish(String bookingId, HandlingEvent event) {",
   "        localDelivery.deliver(bookingId, event);   // THIS instance's local connections only",
   "    }",
   "}"],
  "StatelessBackplane.java / BackplaneMode.java — examples/part4-backplane/quarkus/src/main/java/.../backplane/",
  "This is the Ch15/Ch18 baseline and the default: an injected event reaches only local connections on the instance that received the inject call, never persisted — a client disconnected at injection time loses it permanently. That's the visible gap the Kafka mode (next few slides) is built to close, not a bug in this class.");

diagram("RECONNECT & BACKPLANE · TOPIC-OFFSET RESUME", "Injected events are keyed by bookingId; the seed never touches Kafka",
  "16-topic-offset-resume",
  "Figure 16.1 — the topic/offset/resume model: the seed never touches Kafka, only injected events are keyed into the topic by bookingId, and an afterEventId that names a seed id always falls back to replaying everything currently in the topic.",
  "The fixture seed is sent separately and unconditionally, outside this replay path — the Kafka topic carries ONLY injected events. That's why a client's afterEventId naming a fixture-seed id (the expected Ch15 gap scenario, right after connecting) always misses the search and replays the entire injected history, rather than replaying nothing: fixture ids never appear in the topic buffer at all.");

code("RECONNECT & BACKPLANE · THE KAFKA BACKPLANE", "Every instance has its own consumer group — fan-out, not load-balancing",
  ["@Incoming(\"handling-events-in\")",
   "public void consume(HandlingEvent event) {",
   "    String bookingId = event.bookingId();",
   "    Set<String> seen = seenEventIds.computeIfAbsent(bookingId,",
   "            ignored -> ConcurrentHashMap.newKeySet());",
   "    if (seen.add(event.eventId())) {",
   "        injected.computeIfAbsent(bookingId, ignored -> new CopyOnWriteArrayList<>()).add(event);",
   "    }",
   "    localDelivery.deliver(bookingId, event);",
   "}",
   "",
   "@Override",
   "public void publish(String bookingId, HandlingEvent event) {",
   "    Message<HandlingEvent> message = Message.of(event)",
   "            .addMetadata(OutgoingKafkaRecordMetadata.<String>builder().withKey(bookingId).build());",
   "    emitter.send(message);",
   "}"],
  "examples/part4-backplane/quarkus/src/main/java/.../backplane/KafkaBackplane.java",
  "mp.messaging.incoming.handling-events-in.group.id is derived from each instance's own INSTANCE_ID, so every instance gets its OWN consumer group and receives EVERY record — the opposite of the usual shared-group load-balancing pattern, chosen because Ch18's proof needs instance A's client to see an event injected through instance B. auto.offset.reset=earliest means a freshly started instance replays the full topic into memory before any client connects, so replayFor always has the complete picture.");

diagram("RECONNECT & BACKPLANE · STICKY SESSIONS VS. A SHARED BACKPLANE", "A sticky session says nothing about where an event enters",
  "18-sticky-vs-backplane",
  "Figure 18.1 — a sticky load balancer pins the client to instance A, but the event enters at instance B; without a shared backplane the event never crosses the gap between them.",
  "This is the proof that motivates the whole section: a sticky session keeps a client on one instance, which is necessary for a long-lived WebSocket but solves nothing about where an event is PRODUCED. An inject that lands on instance B has nowhere local to go if A's client is the one that needs it — closing that gap is the backplane's entire job, independent of which broker does it.");

diagram("RECONNECT & BACKPLANE · KAFKA VS. REDIS", "Same fan-out outcome, different trade-off — no single winner",
  "18-kafka-vs-redis",
  "Figure 18.2 — Kafka and Redis both close the fan-out gap; the difference is what each one gives up to do it cheaply (Redis) or durably (Kafka), not whether the client gets the event.",
  "Kafka: durable, retained on disk, replayable — the same topic that powers Ch16's afterEventId resume, at the cost of topic/partition/offset bookkeeping per instance. Redis: a handling-events:{bookingId} Pub/Sub channel, live fan-out only — a dropped subscriber loses in-flight messages with nothing to catch back up, and afterEventId behaves exactly as stateless mode because there's no history. verify.sh proves identical cross-instance delivery on both; the choice is an operational trade-off, not a correctness one.");

code("RECONNECT & BACKPLANE · THE REDIS BACKPLANE", "Pub/Sub, subscribed once per booking, kept for the app's lifetime",
  ["@Override",
   "public void publish(String bookingId, HandlingEvent event) {",
   "    String json = MAPPER.writeValueAsString(event);",
   "    redis.pubsub(String.class).publish(channel(bookingId), json)",
   "            .subscribe().with(",
   "                    ignored -> { },",
   "                    failure -> Log.errorf(failure, \"redis publish failed bookingId=%s\", bookingId));",
   "}",
   "",
   "private void ensureSubscribed(String bookingId) {",
   "    if (!subscribedBookings.add(bookingId)) return;   // subscribe once, keep forever",
   "    redis.pubsub(String.class).subscribe(channel(bookingId))",
   "            .subscribe().with(message -> onMessage(bookingId, message),",
   "                    failure -> Log.errorf(failure, \"redis subscription failed\"));",
   "}"],
  "examples/part4-backplane/quarkus/src/main/java/.../backplane/RedisBackplane.java",
  "Events are plain JSON text on the channel — the same Jackson shape as the WebSocket wire frame — using a private ObjectMapper rather than the app's managed one, so this class has no CDI dependency on quarkus-websockets-next and stays testable in isolation. Redis Pub/Sub delivers to every subscriber including the publisher itself, which onMessage simply forwards to local connections — no special-casing for self-delivery needed.");

code("RECONNECT & BACKPLANE · THE INJECT SEAM", "One internal endpoint, routed to whichever mode is active",
  ["@Path(\"/internal/bookings/{bookingId}/handling-events\")",
   "public class HandlingEventInjectResource {",
   "",
   "    @Inject",
   "    BackplaneRouter router;",
   "",
   "    @POST",
   "    public Response inject(@PathParam(\"bookingId\") String bookingId, HandlingEvent event) {",
   "        Log.infof(\"inject bookingId=%s eventId=%s mode=%s\", bookingId, event.eventId(), router.mode());",
   "        router.publish(bookingId, event);",
   "        return Response.status(Response.Status.ACCEPTED).build();",
   "    }",
   "}"],
  "examples/part4-backplane/quarkus/src/main/java/.../backplane/HandlingEventInjectResource.java",
  "Not part of contracts/asyncapi.yaml — an internal/demo endpoint, documented in PROTOCOL.md's 'Inject endpoint' section, how tests and the Ch18 proof itself get an event onto the active backplane. Always 202 Accepted: publishing is fire-and-forget from the caller's side, regardless of whether delivery ends up local-only (stateless), durable (Kafka), or live-only (Redis) — BackplaneRouter is the one seam that routes to whichever mode application.properties selected.");

// ===== SECTION 04 — PERFORMANCE (Ch19/20) =======================================
divider("04", "Performance", "A second wire encoding, negotiated — and the four levers that bound throughput.",
  "part5-performance adds a choice between JSON and Protobuf, negotiated via Sec-WebSocket-Protocol on the SAME channel, then walks the throughput levers (encoding, batching, compression, size limits) that sit underneath Chapter 12's backpressure ceiling from section 02.");

diagram("PERFORMANCE · PART 5 AT A GLANCE", "Two wire encodings negotiated by subprotocol, decoded to identical values",
  "part5-performance-architecture",
  "Same contract, same fixture, two wire encodings — verify.sh proves field equality and the Protobuf size win live on both stacks.",
  "The client offers handling-events.v1+json or handling-events.v1+protobuf in Sec-WebSocket-Protocol; the server picks the first value it also supports and echoes it back on the 101 response. From there the endpoint either sendTexts a 247-byte JSON object or sendBinarys a 149-byte Protobuf message — a ~40% size difference for the identical RECEIVE event, decoded back to identical field values by verify.sh on both stacks.");

diagram("PERFORMANCE · TWO ENCODINGS, ONE MESSAGE", "The frame opcode tells the decoder which path was taken",
  "19-two-encodings-one-message",
  "Figure 19.1 — one HandlingEvent, two wire encodings negotiated by subprotocol; the frame opcode tells the receiving end which decoder to use before it reads a single byte.",
  "WebSockets Next's own dispatch machinery picks text-vs-binary wiring from an @OnOpen method's STATIC declared Multi return type, not from each item's runtime type — a single method can't declare 'Multi<HandlingEvent> OR Multi<byte[]> depending on negotiation.' That's exactly why HandlingEventPerformanceWebSocket calls connection.sendText/sendBinary explicitly rather than returning a Multi — both are plain Sender methods available regardless of how the connection was opened.");

code("PERFORMANCE · THE PROTOBUF PATH", "Map to the generated type, then branch on the negotiated subprotocol",
  ["static HandlingEventOuterClass.HandlingEvent toProto(HandlingEvent event) {",
   "    HandlingEventOuterClass.HandlingEvent.Builder builder =",
   "            HandlingEventOuterClass.HandlingEvent.newBuilder()",
   "                    .setEventId(event.eventId())",
   "                    .setBookingId(event.bookingId())",
   "                    .setEventType(toProtoEventType(event.eventType()))",
   "                    .setOccurredAt(event.occurredAt().toString());",
   "    // voyageNumber/amount set only when non-null; builder.build() below",
   "    return builder.build();",
   "}",
   "",
   "// HandlingEventPerformanceWebSocket#onOpen",
   "boolean useProtobuf = SUBPROTOCOL_PROTOBUF.equals(connection.subprotocol());",
   "chain = useProtobuf",
   "        ? chain.chain(() -> connection.sendBinary(",
   "                HandlingEventProtoMapper.toProto(event).toByteArray()))",
   "        : chain.chain(() -> connection.sendText(event));"],
  "HandlingEventProtoMapper.java / HandlingEventPerformanceWebSocket.java — examples/part5-performance/quarkus/src/main/java/.../handlingevents/",
  "occurredAt/registeredAt map via Instant#toString() — the identical ISO-8601 (RFC-3339) representation Jackson's JavaTimeModule produces on the JSON path, both built on DateTimeFormatter.ISO_INSTANT — so a client decodes the SAME string whether it reads the text frame or the binary one. The generated outer class is HandlingEventOuterClass because handling-event.proto's own HandlingEvent message collides with protoc's filename-derived class name; protoc's standard collision rule appends OuterClass.");

diagram("PERFORMANCE · FIELD NUMBERS ARE THE REAL CONTRACT", "A JSON key can be renamed freely; a Protobuf tag never can",
  "19-field-numbers-vs-key-names",
  "Figure 19.2 — a JSON key can be renamed freely because the string itself is the identity; a Protobuf field number can never move or be reused, because the integer tag — not the field's name — is the wire identity.",
  "scripts/check-proto-parity.py fails the build the moment either side adds, removes, or reorders a field the other side doesn't also carry — the same additive-only discipline Chapter 7's JSON contract already enforces, just enforced on a different identity (an integer tag rather than a string key). HandlingEventProtoMapper's own enum-prefix stripping is this same discipline showing up as runtime code: the proto enum's HANDLING_EVENT_TYPE_ prefix has to agree with the bare Java enum on both sides.");

diagram("PERFORMANCE · THE THROUGHPUT LEVERS", "Four levers, one shared ceiling underneath all of them",
  "20-levers",
  "Figure 20.2 — four throughput levers, one shared ceiling: Chapter 12's bounded outbound queue governs every byte every lever above it produces.",
  "Encoding (Protobuf vs. JSON) is a fixed, load-independent per-frame discount. Batching trades latency for fewer, larger frames. permessage-deflate is a per-stack default difference, not a universal win — Python's websockets library enables compression=\"deflate\" by default; Quarkus WebSockets Next requires an explicit per-message-compression-supported=true to negotiate it at all. Size limits (max-message-size/max-frame-size) bound one frame independent of Chapter 12's queue depth. None of the four changes whether backpressure trips — they only change how much useful work a connection gets through before it does.");

code("PERFORMANCE · COMPRESSION AND SIZE LIMITS", "Illustrative Ch20 config — neither property is actually set in this example",
  ["# _docs/20-optimizing-throughput.md — Ch20's own config excerpt.",
   "# NOT present in examples/part5-performance/quarkus/.../application.properties:",
   "# that file never sets either property, which is itself this chapter's finding",
   "# (Quarkus defaults per-message-compression-supported to OFF; Python's",
   "# websockets library defaults compression=\"deflate\" to ON).",
   "quarkus.websockets-next.server.per-message-compression-supported=true",
   "quarkus.websockets-next.server.compression-level=6",
   "",
   "# max-message-size / max-frame-size: both OptionalInt, unset means no",
   "# application-level cap beyond Vert.x/Netty's own defaults.",
   "quarkus.websockets-next.server.max-message-size=1048576",
   "quarkus.websockets-next.server.max-frame-size=65536"],
  "_docs/20-optimizing-throughput.md (Ch20) — illustrative; not set in examples/part5-performance/quarkus/src/main/resources/application.properties",
  "A correction on this slide's own source: the actual application.properties for part5-performance sets neither property — that absence IS the Ch20 finding being illustrated, not an oversight in this deck. A production deployment accepting attacker-reachable messages would want an explicit max-message-size/max-frame-size rather than relying on the framework's own ceiling; the chapter's k6/benchmark.js measured the compression-negotiation gap live (0% on Quarkus vs. 100% on Python across three runs with the identical client request).");

diagram("PERFORMANCE · BYTES PER FRAME, MEASURED", "Protobuf's size win is real; deflate's is a measurement blind spot",
  "20-bytes-per-frame",
  "Figure 20.1 — the measured bytes/frame comparison and the real stack difference in whether permessage-deflate gets negotiated at all; the deflate row's bytes/frame is a blind spot, not evidence against compression.",
  "json averages 259.7 bytes; protobuf averages 154.0 bytes, a 40.7% reduction, measured identically regardless of load. json_deflate reads IDENTICAL to plain json on both stacks — not because compression failed, but because k6/ws (built on gorilla/websocket) transparently inflates a compressed frame before the script ever sees the bytes. What the script CAN observe without inference is whether the extension negotiated at all: Python 7908/7908 (100%), Quarkus 0 across 11806-18292 attempts (0%) — the one deflate number this chapter treats as proven.");

// ===== SECTION 05 — TESTING, DEBUGGING, OBSERVABILITY (Ch21/22/23) ==============
divider("05", "Testing, Debugging, Observability", "Proving a protocol you can't curl, then watching it run.",
  "Section 05 closes the implementation arc: the test pyramid this whole site's verify.sh corpus already is (Ch21), a symptom-to-tool map for live debugging (Ch22), and the one place Quarkus's auto-instrumentation stops and a manual span has to start (Ch23).");

diagram("TESTING · THE PYRAMID FOR A PROTOCOL YOU CAN'T CURL", "Five tools, four tiers, all gated on one contract-derived schema",
  "21-test-pyramid",
  "Figure 21.1 — the WebSocket test pyramid: five tools across four tiers, narrower and slower toward the top, all gated on the same contract-derived schema.",
  "Bottom-up: unit/conformance (pytest + Quarkus's HandlingEventContractTest, no socket, no container, milliseconds), live integration (verify.sh/lib.sh against real containers on both stacks), functional (Newman plus a close-code probe — websocat can't read a close code, so this tier exists specifically to cover that gap), and load (k6 — smoke.js gated in CI, benchmark.js local-only). The contract-drift gate underneath all four: regenerate the schema from contracts/asyncapi.yaml, re-run every layer that reads it, on every contract change.");

code("TESTING · THE CONFORMANCE TEST, RE-RUN AGAINST PART 6", "Same shape, re-verified against this part's own fixture",
  ["@Test",
   "void handlingEventTypeHasAllEightContractMembers() {",
   "    List<String> contractMembers = List.of(",
   "            \"HANDLING_EVENT_TYPE_UNSPECIFIED\", \"RECEIVE\", \"LOAD\", \"UNLOAD\",",
   "            \"CUSTOMS\", \"CLAIM\", \"HOLD\", \"DELIVERED\");",
   "",
   "    HandlingEventType[] actual = HandlingEventType.values();",
   "    assertEquals(8, actual.length, \"HandlingEventType must have exactly 8 members\");",
   "",
   "    List<String> actualNames = Arrays.stream(actual).map(Enum::name).toList();",
   "    assertEquals(contractMembers, actualNames,",
   "            \"HandlingEventType members must match the contract's enum, in order\");",
   "}"],
  "examples/part6-observability/quarkus/src/test/java/.../HandlingEventContractTest.java",
  "The same conformance shape from section 01's slide, re-authored against part6-observability's own fixture — every part that forks the endpoint carries its own copy of this test, because each part's HandlingEventType enum has to independently prove it still has exactly the contract's eight members, in order. A schema change that silently drops or reorders a member fails here before it fails anywhere downstream.");

diagram("DEBUGGING · SYMPTOM TO TOOL", "Reach for the cheapest tool that taps the right layer first",
  "22-symptom-to-tool",
  "Figure 22.2 — five symptoms, five first tools: start at the cheapest tool that taps the layer the symptom points to.",
  "Never upgrades at all → curl --include (a proxy likely stripped Connection: Upgrade). 101 then silence → DevTools Frames or websocat -t (check the auth gate from section 02, or a subprotocol mismatch). Wrong frame shape → the binary/text icon or websocat -b | xxd (an opcode mismatch — Ch19's negotiation gone wrong). Drops with no reason → the close_code itself: 4400/4290/4408/1008 each say why; 1006 means no code arrived at all. Dies under load → backpressure (4290) or the liveness sweep (4408) firing under pressure — both from section 02.");

diagram("OBSERVABILITY · AUTO-TRACED UPGRADE, MANUAL PUSH SPAN", "Same span name, same trace-id log line, two different paths to get there",
  "23-auto-vs-manual",
  "Figure 23.1 — Quarkus adds a manual child span under an auto-traced HTTP upgrade; Python has no auto-traced layer at all, so the whole connection span is hand-written with the SDK tracer directly.",
  "quarkus-opentelemetry auto-instruments the HTTP upgrade itself — every request gets a span with zero code. @WithSpan on @OnOpen adds a CHILD span over the Multi it returns; the interceptor defers span.end() until that Multi completes, so the span covers the WHOLE push, not just the synchronous part of the method body. Python has no native websockets auto-instrumentation at all — its equivalent span is entirely hand-written with the SDK tracer, no parent to attach to.");

code("OBSERVABILITY · THE MANUAL SPAN AND THE DELIVERY COUNTER", "A child span, a trace-id log line, a Micrometer counter — once per event",
  ["@WebSocket(path = \"/ws/v1/bookings/{bookingId}/handling-events\", endpointId = \"handling-events\")",
   "public class HandlingEventObservabilityWebSocket {",
   "",
   "    public static final String CONNECTION_SPAN_NAME = \"ws.handling-events.connection\";",
   "",
   "    @OnOpen",
   "    @WithSpan(CONNECTION_SPAN_NAME)",
   "    public Multi<HandlingEvent> onOpen(@PathParam String bookingId) {",
   "        String traceId = Span.current().getSpanContext().getTraceId();",
   "        Log.infof(\"otel.trace_id=%s span=%s bookingId=%s instance=%s\",",
   "                traceId, CONNECTION_SPAN_NAME, bookingId, serviceName);",
   "",
   "        return Multi.createFrom().iterable(feed.events())",
   "                .invoke(event -> deliveredCounter.increment());",
   "    }",
   "}"],
  "examples/part6-observability/quarkus/src/main/java/.../observability/HandlingEventObservabilityWebSocket.java",
  "Span.current() is valid synchronously at the top of the method body because @WithSpan's interceptor has already made the span current before invoking it — that's what lets the trace id get read and logged in exactly the shape verify.sh greps for on both stacks. deliveredCounter (Micrometer → Prometheus) increments once per HandlingEvent as the Multi emits it, not once per connection — a metric that tracks actual delivered events, not opened sockets.");

// ===== SECTION 06 — DEPLOY ======================================================
divider("06", "Deploy", "Compose, minikube, OpenShift Local — one contract, three runtime tiers.",
  "Closes the main body with the same three-tier progression this site runs everywhere: Docker Compose for the inner loop, minikube (docker driver, containerd runtime) for a real cluster, OpenShift Local as a separate appendix. The Quarkus side of every example in this deck already runs on all three.");

diagram("DEPLOY · THREE TIERS, ONE CONTRACT", "Compose now, minikube and CRC later — same services either way",
  "00-tier-progression",
  "Figure 0.2 — Three tiers, one contract: Compose now, minikube and CRC later.",
  "Docker Compose is the fastest inner loop and where every example in this deck has been shown running; minikube (docker driver + containerd runtime — the podman path is not supported, DRQ-007) is the Kubernetes-shaped version of the exact same two-instance backplane topology from section 03; OpenShift Local is a separate appendix, never folded into the minikube path. All three run the identical contract and the identical fixture — nothing about the application changes tier to tier, only the manifests around it.");

content("201 · CLOSE", "One contract, one Quarkus build, from laptop to OpenShift",
  ["The endpoint, the four connection concerns, three backplane modes, two wire encodings, and the observability layer are all the same Quarkus WebSockets Next codebase this deck just walked — nothing here is a simplified teaching version of a 'real' implementation elsewhere.",
   "For the ideas and the protocol fundamentals at architect altitude, see the 101 deck; for the identical pattern set re-implemented on native websockets + FastAPI, see the 201-Python companion.",
   "The appendix carries the minikube ingress overlay, the OpenShift Route/AMQ Streams manifests, and the version matrix — reference depth, not a continuation of this narrative."],
  "This is the handoff slide. If the audience is building the Quarkus side, point them at the examples/ directories named throughout this deck — every one is independently runnable with its own README and verify.sh. If they're comparing stacks, the 201-Python deck covers the identical pattern set on native websockets + FastAPI, close code for close code.");

// ===============================================================================
// APPENDIX — overflow starts here. Slides below do NOT count against the
// ~50-slide MAIN cap (tracked separately as appendixCount).
// ===============================================================================
inAppendix = true;

divider("APP", "Appendix — Manifests, Edge Cases, Reference", "Keep this open in another window.",
  "The appendix carries platform manifests that didn't fit the main body's narrative arc (the minikube ingress overlay, the OpenShift Route and pinned AMQ Streams CSV), two lifecycle edge cases worth knowing before running this in production, and the version matrix every example in this deck is pinned against.");

code("APPENDIX · THE MINIKUBE INGRESS OVERLAY", "Raised proxy timeouts and an affinity cookie for a long-lived upgrade",
  ["# k8s/overlays/minikube/kustomization.yaml — retags images to the tag",
   "# verify-minikube.sh builds+loads, forces imagePullPolicy: Never",
   "images:",
   "  - name: part4-backplane-quarkus",
   "    newTag: minikube",
   "patches:",
   "  - target: { kind: Deployment, labelSelector: \"app.kubernetes.io/part-of=part4-backplane\" }",
   "    patch: |-",
   "      - op: replace",
   "        path: /spec/template/spec/containers/0/imagePullPolicy",
   "        value: Never",
   "",
   "# k8s/base/ingress.yaml — nginx's 60s proxy-read-timeout would otherwise",
   "# kill a long-lived upgraded connection that goes quiet",
   "annotations:",
   "  nginx.ingress.kubernetes.io/proxy-read-timeout: \"3600\"",
   "  nginx.ingress.kubernetes.io/proxy-send-timeout: \"3600\"",
   "  nginx.ingress.kubernetes.io/affinity: \"cookie\""],
  "examples/part4-backplane/k8s/overlays/minikube/kustomization.yaml + k8s/base/ingress.yaml",
  "No special 'websocket' annotation exists for ingress-nginx — it detects the Connection: Upgrade / Upgrade: websocket request headers and proxies the upgrade through automatically; only the timeouts need raising. The affinity cookie is a sticky session so a reconnecting client (Ch15/Ch16) keeps landing on the same pod — moot with one replica per instance here, but it documents the production-shape intent. verify-minikube.sh's idle-hold step is the live proof the raised timeout does what it says: hold past 60s, assert a late frame still arrives.");

code("APPENDIX · THE OPENSHIFT ROUTE AND PINNED KAFKA OPERATOR", "Edge-TLS at the router; a Manual-approval CSV pin for AMQ Streams",
  ["# openshift/helm/part4-backplane/templates/routes.yaml",
   "apiVersion: route.openshift.io/v1",
   "kind: Route",
   "spec:",
   "  tls:",
   "    termination: edge",
   "    insecureEdgeTerminationPolicy: Redirect",
   "  annotations:",
   "    haproxy.router.openshift.io/timeout: \"3600s\"",
   "",
   "# openshift/infra/amq-streams-subscription.yaml",
   "apiVersion: operators.coreos.com/v1alpha1",
   "kind: Subscription",
   "spec:",
   "  channel: amq-streams-3.2.x",
   "  startingCSV: amqstreams.v3.2.1-14",
   "  installPlanApproval: Manual"],
  "examples/part4-backplane/openshift/helm/part4-backplane/templates/routes.yaml + openshift/infra/amq-streams-subscription.yaml",
  "Only instance A of each stack gets a Route — instance B stays reachable in-cluster only, same 'A is the externally reachable one' split as the minikube ingress. installPlanApproval: Manual plus a pinned startingCSV means OLM proposes only this exact InstallPlan; a later upgrade OLM proposes on its own stays unapproved until this file is bumped as its own reviewed change. amqstreams.v3.2.1-14 supports Kafka 4.1.0/4.2.0 only — a recorded step-back from compose/minikube's 4.3.1, named on the next slide's version matrix rather than silently left inconsistent.");

content("APPENDIX · COMPOSE PROFILES VS. BACKPLANE_MODE", "One env var selects the mode; a compose profile brings up the matching broker",
  ["compose.yaml's three profiles (default/kafka/redis) each bring up exactly the infrastructure the matching BACKPLANE_MODE needs — no profile brings up a broker the app isn't configured to use.",
   "BACKPLANE_MODE=STATELESS (default, no profile) boots with no broker at all; KAFKA and REDIS each need their own profile flag to start the matching container alongside the app.",
   "Ch25 keeps this pairing explicit rather than always starting every broker — a stateless-mode run with a Kafka container sitting idle nearby would be a confusing demo, not a safer one."],
  "The point to make here: BACKPLANE_MODE and the compose profile are two separate selectors that have to agree, not one flag doing double duty. Getting them out of sync — KAFKA mode with no kafka profile running — is exactly the scenario the next appendix slide's hard-fail receipt documents.");

code("APPENDIX · THE NO-RESOLVABLE-BOOTSTRAP HARD-FAIL", "An unresolvable Kafka hostname crashes Quarkus at startup — a receipt, not a guess",
  ["# examples/part4-backplane/verify.sh",
   "#",
   "# compose.yaml's KAFKA_BOOTSTRAP_SERVERS/REDIS_URL default to",
   "# localhost:9092 / redis://localhost:6379/0 -- resolvable-but-unreachable,",
   "# which both apps' READMEs document as safe even in stateless mode. Only",
   "# point them at the real broker hostname for the stage that actually",
   "# brings that broker up -- confirmed live: handing Quarkus's always-wired",
   "# Kafka consumer an UNRESOLVABLE hostname crashes the app at startup",
   "# with `ConfigException: No resolvable bootstrap urls`, a hard failure,",
   "# not the soft \"unreachable but resolvable\" case.",
   "local kafka_servers=\"localhost:9092\" redis_url=\"redis://localhost:6379/0\"",
   "if [[ \"$profile\" == \"kafka\" ]]; then",
   "  kafka_servers=\"kafka:9092\"",
   "elif [[ \"$profile\" == \"redis\" ]]; then",
   "  redis_url=\"redis://redis:6379/0\"",
   "fi"],
  "examples/part4-backplane/verify.sh",
  "The distinction this comment draws is the whole point: 'unreachable but resolvable' (localhost:9092 with nothing listening) is a soft failure the app tolerates in stateless mode; an UNRESOLVABLE DNS name is a hard CDI configuration failure that crashes startup outright. verify.sh only ever points kafka_servers at the real in-network hostname for the profile that actually starts that container — getting this wrong is exactly how a stateless-mode smoke test would accidentally crash on a Kafka DNS name that only exists in the kafka profile.");

content("APPENDIX · DEDUP-BY-EVENTID IS A BENIGN RACE", "A replayed Kafka record and the live consumer can both deliver the same event",
  ["KafkaBackplane#consume dedupes with a per-booking Set<String> of seen eventIds before appending to the in-memory history — a redelivered or replayed record never gets counted twice in replayFor's search.",
   "The race this guards is between a replay burst (on instance startup, auto.offset.reset=earliest) and the always-on live consumer: both can observe the same record, and only the first one to call seen.add(...) wins the append.",
   "This is a benign race, not a bug to eliminate: the client-side contract is 'dedupe by eventId,' so a client that receives the same event twice over the wire (the seen.add race doesn't prevent delivery, only double-counting history) is already expected to tolerate it."],
  "Worth being precise about what this guard does and doesn't do: it prevents the in-memory injected history from growing duplicate entries, which would otherwise corrupt replayFor's afterEventId search. It does NOT guarantee a connected client never sees the same HandlingEvent delivered twice over the wire in a narrow replay-vs-live race — that's exactly why every consumer on this channel, client included, is expected to dedupe by eventId rather than assume delivery is exactly-once.");

code("APPENDIX · LIFECYCLE EDGE CASES", "SKIP overlapping sweeps; close every connection with a stated reason on shutdown",
  ["@Scheduled(every = \"${example.heartbeat.sweep-interval:5s}\",",
   "           concurrentExecution = ConcurrentExecution.SKIP)",
   "void sweep() { /* HeartbeatLivenessSweep — see section 02 */ }",
   "",
   "@ApplicationScoped",
   "public class ConnectionLifecycleShutdown {",
   "",
   "    @Inject",
   "    OpenConnections openConnections;",
   "",
   "    void onShutdown(@Observes ShutdownEvent event) {",
   "        for (WebSocketConnection connection : openConnections.listAll()) {",
   "            if (connection.isOpen()) {",
   "                connection.closeAndAwait(",
   "                        new CloseReason(CloseCodes.GOING_AWAY, \"server shutting down\"));",
   "            }",
   "        }",
   "    }",
   "}"],
  "HeartbeatLivenessSweep.java / ConnectionLifecycleShutdown.java — examples/part4-connection/quarkus/src/main/java/.../connection/",
  "concurrentExecution = SKIP is a backstop against overlapping sweep runs piling up while one run is still in flight closing connections in the ~10s Vert.x closing-handshake grace from section 02. ConnectionLifecycleShutdown uses the BLOCKING closeAndAwait, not close(...).subscribe(), because a CDI ShutdownEvent observer runs synchronously on the shutdown thread with no Quarkus-managed subscription for a deferred callback to complete in later — every open connection gets a deliberate 1001 GOING_AWAY instead of an abrupt socket drop a client would see as 1006.");

statusTable("APPENDIX · VERSION MATRIX", "What every example in this deck is pinned against",
  [
    { code: "Quarkus", name: "3.40.0", purpose: "WebSockets Next ships with Quarkus — not a separately versioned artifact" },
    { code: "JDK", name: "25.0.4 (Temurin)", purpose: "Ch0 pin, current LTS line patch" },
    { code: "Kafka", name: "4.3.1", purpose: "compose + minikube (KRaft, apache/kafka image)" },
    { code: "Kafka (CRC)", name: "4.2.0", purpose: "AMQ Streams step-back — amqstreams.v3.2.1-14 supports 4.1/4.2 only; a weaker proof than minikube's own 4.3.1 run" },
    { code: "Redis", name: "8.10.2-alpine", purpose: "same pin across compose, minikube, and the CRC Helm chart" },
    { code: "minikube", name: "v1.39.0 (floor)", purpose: "docker driver + containerd runtime only — the podman path is not supported" },
    { code: "CRC", name: "2.64.0 / OCP 4.22.14", purpose: "verified live headless 2026-10-19" },
  ],
  "Pulled directly from _plans/version-matrix.md, not restated from memory — check that file before citing a version from this deck. Repeat this hedge every time CRC's Kafka version comes up: 4.2.0 is a recorded step-back from 4.3.1 because the AMQ Streams operator doesn't yet support 4.3.x, and the CRC idle-hold proof is weaker than minikube's own run for that reason — the wire behavior Ch16/Ch18 exercise is identical on both versions, but the version pin itself is not.",
  { colW: [2.5, 2.0, 7.59] });

pres.writeFile({ fileName: OUT })
  .then(p => console.log("WROTE", p, "slides:", pageNum, "main:", mainCount, "appendix:", appendixCount))
  .catch(e => { console.error(e); process.exit(1); });
