// deck.js — "Real-Time APIs with WebSockets" — 101 (the ideas).
// Concept-forward companion: push over pull, the WebSocket protocol, the
// shared shipping/cargo domain, giving a socket a contract, and the nine
// production concerns a long-lived connection makes you own. No stack-
// specific code — that lives in the Quarkus and Python 201 deep dives.
// Red Hat house style, 16:9. Build: node deck.js
//
// Mined from Parts 0-2 (Ch0-7) and the judgment chapters (Ch12-14, 16-19,
// 23-24, 27). Six acts: A The Real-Time Problem / B How WebSockets Work /
// C The Shared Domain / D The Contract Story / E Production Concerns /
// F Runtime & Judgment.

"use strict";

const H = require("./deck-helpers.js");
const {
  COLOR, FONT, W, PNG, ASSETS,
  newDeck, addFooter, addContentTitle, addBullets, addTwoColBullets,
  addStatusTable, addCaption, addCodeSlide, addDiagramSlide, addSectionDivider, addNotes,
} = H;

const OUT = "WebSockets_101-r1.1.pptx";
const REV = "r1.1";

const pres = newDeck();
pres.title = "Real-Time APIs with WebSockets: 101 (the ideas)";
let pageNum = 0;
let mainCount = 0;

function S() { const s = pres.addSlide(); pageNum += 1; addFooter(s, pageNum); return s; }
function divider(code, title, subtitle, notes) {
  const s = pres.addSlide(); pageNum += 1; addSectionDivider(s, code, title, subtitle); addNotes(s, notes);
}

// ---- local stub helpers (thin wrappers over the bundled deck-helpers) -----
function content(eyebrow, title, bullets, notes, opts) {
  const s = S();
  addContentTitle(s, eyebrow, title);
  addBullets(s, bullets, opts || {});
  addNotes(s, notes);
  return s;
}
function twoCol(eyebrow, title, left, right, notes) {
  const s = S();
  addContentTitle(s, eyebrow, title);
  addTwoColBullets(s, left, right);
  addNotes(s, notes);
  return s;
}
function diagram(eyebrow, title, png, caption, notes, opts) {
  const s = S();
  addDiagramSlide(s, eyebrow, title, png, caption, opts || {});
  addNotes(s, notes);
  return s;
}
function table(eyebrow, title, rows, notes, opts) {
  const s = S();
  addContentTitle(s, eyebrow, title);
  addStatusTable(s, rows, opts || {});
  addNotes(s, notes);
  return s;
}

// ===== COVER ==================================================================
{
  const s = pres.addSlide();
  pageNum += 1;
  s.background = { color: COLOR.white };
  try { s.addImage({ path: `${ASSETS}/cover-panel.png`, x: 0, y: 0, w: W, h: 7.5 }); } catch (e) {}
  s.addText("REAL-TIME APIS WITH WEBSOCKETS · 101", { x: 6.00, y: 1.98, w: 6.90, h: 0.34,
    fontFace: FONT.title, fontSize: 13, bold: true, color: COLOR.red, charSpacing: 5, align: "left", valign: "middle" });
  s.addText([{ text: "The ideas: push, the protocol,", options: { breakLine: true } },
             { text: "and the contract" }], {
    x: 5.95, y: 2.42, w: 6.95, h: 2.00, fontFace: FONT.title, fontSize: 44, bold: true, color: COLOR.ink, align: "left", valign: "top" });
  s.addText("Why request/response falls short for a client watching something change, and what a live socket commits you to in exchange.",
    { x: 6.00, y: 4.65, w: 6.80, h: 1.05, fontFace: FONT.body, fontSize: 16, italic: true, color: COLOR.caption, align: "left", valign: "top" });
  s.addText(REV, { x: 11.85, y: 5.85, w: 0.95, h: 0.30, fontFace: FONT.mono, fontSize: 11, color: COLOR.caption, align: "right", valign: "middle" });
  try { s.addImage({ path: `${ASSETS}/logo-candidate-2.png`, x: 11.10, y: 6.80, w: 1.55, h: 0.37 }); } catch (e) {}
  addNotes(s, "This is the 101, the ideas deck covering WebSockets-based real-time APIs. It opens with why request/response has no channel for a server to speak first, walks the protocol underneath the choice, names the shared shipping/cargo domain a live feed pushes, gives the socket a reviewable AsyncAPI contract, and spends real time on the nine production concerns a long-lived connection makes you own that a one-shot HTTP call never had to. It closes with the judgment call this whole site insists on: a socket earns its cost only when the interaction actually needs it, and knowing when it doesn't is as much a part of this material as knowing how to build one. There is no stack-specific code on these slides; that is the Quarkus and Python 201 decks' job, but every idea here maps to a real chapter and a running example in this book's own repository, so nothing on this deck is hypothetical. The audience is architects, leads, and engineers deciding whether a given interaction needs a socket at all, and if it does, what that commitment actually costs to run correctly.");
}

// ===== AGENDA ==================================================================
twoCol("101 · THE IDEAS", "Six acts, one running example",
  ["The real-time problem, and choosing the right transport: not just a socket by default",
   "How WebSockets actually work: the handshake, the frame, the close code",
   "The shared shipping/cargo domain this feed pushes, and the seam it leaves alone"],
  ["Giving a socket a contract, and the discipline that lets it evolve without breaking a client already connected",
   "Nine production concerns, in concept: backpressure, errors, liveness, reconnect, security, scale, binary, observability, anti-patterns",
   "Runtime progression, and the judgment call: when a socket is the wrong tool entirely"],
  "The agenda runs six acts, each one chapter deeper into the same running example: a customer watching a booking move through customs over a live handling-event feed. Act A makes the case for push over pull and then immediately complicates it: five transports solve some version of this problem, and a WebSockets site still has to rule the other four out on the merits, not by default. Act B opens the protocol itself: the handshake that runs once, the frame format every later byte belongs to, and the close-code vocabulary every error-handling chapter leans on. Act C names the domain vocabulary this feed actually pushes, and just as importantly, what it leaves to the REST booking service by design. Act D gives the socket the same contract-first discipline a REST resource or a Protobuf service already has, including what happens the day that contract has to change under a client that's already connected. Act E is the long middle of the deck: nine production concerns a long-lived connection makes you own, each one shown at the concept level with the two-stack proof it was built against. Act F closes with the runtime path and the one question underneath all of it: does this specific interaction actually need a socket, or is there a cheaper, better-fitting answer on the shelf.");

// ===== ACT A — THE REAL-TIME PROBLEM, AND CHOOSING THE TOOL ====================
divider("A", "The Real-Time Problem", "Why asking again and again doesn't work, and the five transports that might replace it.",
  "This act opens with the cost of polling, stated in real numbers against the shipping domain this whole site shares with its REST and gRPC siblings, and closes by refusing the easy answer that push always means a WebSocket. Five transports solve some version of the same problem, and the discipline this act teaches is running every interaction through the same ordered questions instead of defaulting to the socket a WebSockets site makes look obvious.");

diagram("THE REAL-TIME PROBLEM · THE CASE", "A booking that doesn't move on request",
  "01-booking-lifecycle",
  "The booking lifecycle as a state pipeline, with the handling-event feed pushed over the socket beneath it.",
  "A GET against a booking resource answers exactly one question correctly: what is true right now. It was built for that question and it answers it well: cacheable, idempotent, the same contract the REST sibling site builds its first part around. The mismatch is on the client's side of the exchange: a shipper's dashboard, a customs broker's queue, an ops team's alert panel doesn't want a one-time read, it wants a subscription, and no amount of refining the response body changes that. The booking's state changes when a container moves or a hold opens: a fact the booking service learns at a moment it chooses, never one the client can time by asking again. The only way to approximate 'tell me when' using 'what is true right now' is to ask the second question over and over, hoping the gap between one answer and a changed one is short enough to matter. That's polling, and it's the default reach for anyone who hasn't been shown another option yet.");

diagram("THE REAL-TIME PROBLEM · THE NUMBERS", "The cost of polling",
  "01-polling-cost",
  "299 wasted requests for every real change, watching one booking for ten minutes, at any scale.",
  "Put real numbers against one booking watched for ten minutes with one handling event at minute seven. A client polling every two seconds sends 300 requests over that window; 299 of them return a body byte-for-byte identical to the one before. Every single one still costs a connection reuse, an auth check, a database read, and a JSON body over the wire: real work spent to say nothing new. Multiply by watchers: a thousand brokers each watching their own booking at the same interval turns that into 300,000 requests for roughly a thousand real events, a ratio that does not improve with scale, it only compounds. None of that capacity is reclaimable at the moment it matters most: a customs hold that triggers a wave of manual refreshing lands on top of the steady-state polling load already saturating the service, at the exact moment that service is also handling the workflow that opened the hold. Polling concentrates load exactly where attention concentrates, which is also where correctness matters most.");

diagram("THE REAL-TIME PROBLEM · THE INVERSION", "Pull vs. push: the same booking, watched two ways",
  "01-poll-vs-push",
  "Pull makes the client pay for ignorance on every request; push makes the server pay once per fact.",
  "A WebSocket inverts who speaks first. Instead of the client asking 'did anything change' on a schedule it has to guess, it opens one connection and the booking service's event stream sends a message the instant a handling event is recorded, because sending it is a side effect of the event happening, not a response to being asked. That one upgrade replaces the three hundred separate connections a ten-minute poll loop would have made; the handshake cost is paid once, not once per check. A booking that goes quiet for six hours between gate-in and the next event sends nothing over the socket in that window; a booking with five events in five minutes gets five messages, each one carrying something the client didn't have before. Volume now tracks information instead of a guessed interval. None of this is free: a server now carries one open socket, and the memory and file-descriptor cost that comes with it, for as long as a client cares to watch. That real cost is what Act E's production-concerns section spends its time on.");

content("THE REAL-TIME PROBLEM · THE TRADE", "Latency vs. freshness: a knob with no good setting",
  ["Shortening the poll interval cuts detection latency but multiplies wasted requests by the same factor",
   "Lengthening it hides staleness a 200 OK never signals to whoever is reading the dashboard",
   "Backing off under load, whether rate limits or a longer Retry-After, buys the server relief at the direct cost of every watcher's freshness",
   "There is no fixed or adaptive interval that decouples a client's freshness from the server's load; the two move in opposite directions on the same knob"],
  "Shortening the poll interval trades one cost for another, not for nothing. A client polling every ten seconds misses an event by up to ten seconds; drop the interval to one second and the gap shrinks while request volume rises tenfold, serving ten times the empty answers to shave a few seconds off a detection time it still can't guarantee. There is no interval that delivers both low latency and low waste, because the interval is a guess about when something will happen, made by a client with no information about when that something will happen. Staleness is the other side of the same trade: a dashboard polling every thirty seconds shows a status that might already be thirty seconds wrong, and nothing in a successful response says so. Backing off the interval under load makes both problems worse at once: the exact moment a system is busiest, usually because something real is happening across many bookings, is the moment staleness grows for every client watching one. That's the structural argument for push, stated before a single transport gets named.");

content("THE REAL-TIME PROBLEM · WHAT CHANGES", "What push changes: the server pays once per fact",
  ["A WebSocket inverts who initiates: the server speaks the instant it knows something, not when asked",
   "One upgrade handshake replaces the connection-and-request cost of hundreds of polls",
   "Request volume now tracks real events in the domain, not a client's anxiety level",
   "Holding a connection open isn't free: it moves the cost from per-request to per-connection, which later chapters spend real space on"],
  "Push changes the shape of the cost, it doesn't erase it. A client opens GET /bookings/4471/events with an Upgrade header, the server answers 101 Switching Protocols, and from that point the same TCP connection carries WebSocket frames in both directions instead of HTTP request/response pairs. That one handshake, paid once, is what replaces the three hundred connection-and-request cycles a ten-minute poll loop would have cost. What a server now carries instead is an open socket and the memory and file-descriptor cost that comes with it, per watching client, for as long as that client cares to watch; a real cost, and the one this deck's production-concerns act spends real time on: backpressure when a client can't keep up, heartbeats to detect a connection that died without saying so, fan-out when one event has to reach thousands of open connections without doing thousands of times the work. None of that erases the case for push; it reframes the bill from per-request, paid whether or not anything happened, to per-connection, paid once for as long as the watch lasts.");

diagram("CHOOSING THE TOOL · THE FIELD", "The contenders: WebSockets, SSE, long-polling, webhooks",
  "02-duplex-comparison",
  "The same push problem, five different rules about who may send and when.",
  "Five transports solve some version of the push problem this act opened with, and a site built around WebSockets has an obvious bias toward answering every interaction the same way; that bias is the wrong starting point. A WebSocket is a single TCP connection that upgrades in place and carries framed messages in both directions for as long as it stays open; neither side waits for the other to finish speaking. Server-Sent Events push data one way only, over a plain HTTP response whose body never ends, with a browser-native EventSource that reconnects on its own. Long-polling fakes a push by holding a request open until the server has something to say, then immediately issuing the next one. Every update costs a full request/response cycle, but the wire format is nothing stranger than HTTP. A webhook inverts who initiates entirely: the event source calls the receiver's own endpoint, no connection held between deliveries. gRPC server-streaming is a stream over HTTP/2 between two services that already share a Protobuf contract: the shape this site's gRPC sibling covers from the other direction.");

content("CHOOSING THE TOOL · THE DIMENSIONS", "Dimensions that matter: direction, duplex, ordering, backpressure",
  ["Direction: who's allowed to originate a message, and when; a WebSocket allows either side at any time, SSE only the server",
   "Duplex: can both directions carry traffic at once, or must one finish before the other starts",
   "Ordering and backpressure: FIFO guarantees differ by transport, and only gRPC streaming gets flow control built into HTTP/2 itself",
   "Proxy survival and reconnection: SSE heals itself with Last-Event-ID; a WebSocket makes the application write every bit of that logic"],
  "These dimensions collapse into one table worth keeping next to the decision framework that follows. Direction asks who may originate a message: a WebSocket allows either side at any time; SSE's one and only client-to-server act is the original GET; a webhook flips the usual client/server relationship entirely. Duplex is the sharper version of the same question: a WebSocket is full-duplex by protocol, long-polling and webhooks are strictly half-duplex request/response pairs, and SSE sits at one extreme of half-duplex since there's no client-to-server half to interleave with at all. Ordering matters once more than one update is in flight: a WebSocket and SSE both guarantee FIFO delivery because each is one ordered stream; webhooks are the outlier, since two deliveries for the same booking can arrive out of order if a sender retries one and not the other. Backpressure is what happens when a receiver can't keep up: raw WebSockets give an application nothing here beyond TCP's own flow control, while gRPC server-streaming gets real backpressure from HTTP/2's own flow-control windows with no extra code. Reconnection separates a transport that heals itself from one that makes the application write the healing logic: EventSource resumes with Last-Event-ID built into the spec; a WebSocket has no equivalent at all.");

diagram("CHOOSING THE TOOL · THE FRAMEWORK", "A decision framework: five questions, six answers",
  "02-transport-decision",
  "The same five questions, as a tree, resolving to one of five transports or to no transport at all.",
  "Running an interaction through these questions in order resolves to one of the five transports, or to a sixth answer: nothing here is needed, plain request/response on demand is the right tool. Start with whether the interaction needs live updates at all; a report generated once a day never gets further than this question. If it does, ask who has to send: one side only, or both. The moment the interaction needs the client to send something mid-stream, switching which booking it's watching, acknowledging a message, duplex stops being optional and a WebSocket is the only one of the five that provides it natively. When the server is the only side that ever sends, the branch depends on who's receiving: a browser tab on a streaming-friendly network path gets SSE's native reconnection for less implementation effort than a socket; a known-hostile network path gets long-polling instead, which degrades to plain request/response rather than failing outright. When the receiver is another service, the question becomes whether it can expose a reachable endpoint: a webhook if it can, scheduled polling if it can't, and that's a real answer, not a failure state.");

content("CHOOSING THE TOOL · THE WORKED CASE", "A worked decision: the handling-event feed",
  ["Needs live updates at all: a stale status while a container has already cleared customs is the exact failure this act opened with",
   "Needs the client to send too: an initial subscribe naming the booking, a resubscribe on switch; rules out SSE's one-way channel",
   "Receiver is a browser tab the team controls, not another service with its own endpoint; rules out a webhook",
   "Expected latency and volume rule out long-polling's per-update cost and gRPC streaming's browser-hostile requirement"],
  "Running the booking page's own handling-event feed through the framework by name grounds the abstract questions above before this deck moves on. Does it need live updates at all: yes, a customer staring at a stale status while a container has already cleared customs is the exact failure this act opened with. Who needs to send: here the answer is both, because the page has to tell the backend which booking to watch the moment it connects, and because switching bookings mid-session means sending a new subscribe message without reopening a connection. That single requirement rules out SSE regardless of how one-sided the rest of the traffic looks, since an EventSource has no channel back to the server at all. The receiver is a browser tab the team controls, which rules out a webhook, since nothing here can expose a public endpoint for someone else to call. And the volume and latency a customer expects, a status change reflected in under a second, rule out long-polling's per-update request cost and gRPC streaming's requirement that neither end be a browser. The socket is correct here because the dimensions say so, not because this is a WebSockets site.");

// ===== ACT B — HOW WEBSOCKETS WORK =============================================
divider("B", "How WebSockets Work", "The handshake that runs once, and the frame format everything after it belongs to.",
  "This act names the mechanism underneath the transport choice Act A made: the HTTP Upgrade handshake that turns one ordinary request into a long-lived socket, the frame format RFC 6455 defines for everything that crosses it afterward, the control frames that keep a connection alive or end it cleanly, and the parts of the surrounding stack, TLS, proxies, load balancers, that have opinions about a connection that refuses to close.");

diagram("THE PROTOCOL · THE HANDSHAKE", "The upgrade handshake: one HTTP request becomes a socket",
  "03-upgrade-handshake",
  "One HTTP request becomes a long-lived socket: the 101 response is the whole handshake.",
  "A WebSocket connection starts as a normal HTTP request: no separate port, no separate listener. What makes it a handshake rather than a page fetch is a specific set of headers: Upgrade: websocket, Connection: Upgrade, a fixed protocol version, and a random Sec-WebSocket-Key generated fresh per connection. A server that accepts replies 101 Switching Protocols instead of 200 OK, echoing the handshake back with a Sec-WebSocket-Accept value derived, not echoed, from the key: the server concatenates the client's key with a fixed GUID published in the spec text, hashes it, and base64-encodes the digest. This isn't authentication and isn't meant to be; its job is narrower: proving the server on the other end actually understood this was a WebSocket upgrade and ran the handshake logic, rather than being a caching proxy or a misconfigured intermediary that echoed the request back without understanding it. Once validated, both sides agree: this connection no longer carries HTTP request/response pairs. The handshake happens exactly once per connection, amortized across every frame that follows for however long the client keeps watching.");

diagram("THE PROTOCOL · THE FRAME", "Frame anatomy: FIN, opcode, mask, length",
  "03-frame-anatomy",
  "Frame anatomy, decoded against a real captured frame carrying one handling event.",
  "After the 101, an application sends and receives messages, but the wire carries frames: a message can be split across more than one. The first two bytes carry almost everything a receiver needs before reading the payload: FIN marks the last frame of a message; a four-bit opcode says what kind of frame this is: text, binary, close, ping, or pong; a MASK bit says whether the payload is XOR-masked; and a payload-length field extends from seven bits up to sixty-four when the message is large. Masking is specific to client-to-server frames and has nothing to do with confidentiality: masking a payload with a key sent in the clear in the same frame provides zero cryptographic protection, and the spec says so directly. It exists to defeat cache-poisoning and request-smuggling attacks against intermediaries that don't understand WebSocket framing: an unpredictable, per-frame mask key means an attacker can't control the literal bytes that hit the wire. Servers don't mask their frames because the corresponding attack runs browser-to-intermediary, not server-to-intermediary; a browser is the component running uncontrolled script that needs the key unpredictable.");

content("THE PROTOCOL · STAYING ALIVE, ENDING CLEAN", "Control frames and close codes",
  ["Ping/pong is a liveness probe, not proof the TCP connection itself is still there",
   "Close (0x8) is a handshake in miniature: an optional 2-byte code plus an optional reason string",
   "1006 is reserved: never sent on the wire, synthesized locally when a connection drops with no close frame at all",
   "4000-4999 is the private-use range RFC 6455 sets aside for a site's own application-specific rejections"],
  "Three of the six opcodes manage the connection itself rather than carry application data, and all three share one rule: control frames are never fragmented and carry at most 125 bytes, so an implementation can always process one in a single read. Ping and pong are a liveness check: either endpoint may send a ping at any time, and the receiver must reply with a pong carrying the identical payload, without waiting for in-progress data frames to finish. A ping/pong round trip tells a sender the connection's other end is still processing, not only that the TCP socket hasn't been torn down; a socket can sit half-open for minutes after a peer dies, since TCP's own keepalives are optional and slow. Close ends the connection as a miniature handshake: one side sends a close frame, the other is expected to echo it back, and only then does either tear down the underlying TCP connection. 1006 is one of two codes a conforming implementation must never place in an actual close frame: it's the value a client-side API synthesizes locally when a connection ends with no handshake at all. The 4000-4999 range exists precisely because the standard codes have nothing to say about why a feed closed for an application-specific reason.");

content("THE PROTOCOL · NEGOTIATION", "Subprotocols and extensions: two different negotiations",
  ["Sec-WebSocket-Protocol negotiates the message format: the handshake fails outright if nobody agrees, rather than falling back silently",
   "Sec-WebSocket-Extensions modifies the framing itself; permessage-deflate (RFC 7692) is the one in wide production use",
   "Compression buys bandwidth on repetitive JSON at the cost of CPU, per-connection memory, and a real TLS-plus-compression attack class",
   "Both negotiate exactly once, at the handshake; a client that wants a different protocol version opens a new connection"],
  "Two negotiation fields ride the same handshake as the Upgrade itself, and they solve different problems easy to conflate on a first read. Sec-WebSocket-Protocol is application-level negotiation: the client lists message formats it can speak in preference order, the server picks one it supports and echoes exactly that value back; if the server supports none of them, the spec requires it to fail the handshake rather than connect successfully on an undeclared default. A versioned subprotocol token means a client and server that disagree about message shape fail at connection time with a clear signal, instead of failing later when an unrecognized field arrives inside an otherwise-successful connection. Extensions modify the framing itself: permessage-deflate compresses each message's payload before it's framed, earning real bandwidth savings on repetitive JSON where field names repeat on every push, but it costs CPU per frame, memory proportional to connection count, and carries a known attack class against TLS-plus-compression that trades a compression-ratio side channel for secret recovery. It needs an explicit decision, not a default-on flag, on any connection carrying anything sensitive.");

content("THE PROTOCOL · THE SURROUNDING STACK", "TLS, proxies, and wss://",
  ["wss:// is table stakes in production, not optional hardening: the upgrade travels over a channel TLS already encrypted",
   "A plain reverse proxy strips Connection: Upgrade unless explicitly configured for WebSocket proxying",
   "A connection is sticky by nature: every frame for its entire life must reach the same backend that completed the handshake",
   "A WebSocket has no backpressure signal above what TCP's own send buffer already enforces: no frame means 'slow down'"],
  "Production traffic runs wss://, WebSocket over TLS, for the same reason production HTTP runs https://. Without it, every payload, bearer token, and the handshake dance itself crosses the network in plaintext. Browsers enforce this as a mixed-content rule: a page loaded over https:// cannot open a plain ws:// connection at all. Reaching the server depends on everything between client and server understanding the Upgrade request: a plain reverse proxy that doesn't know about WebSockets will typically strip Connection: Upgrade as a hop-by-hop header and never deliver the 101 intact; every major reverse proxy supports WebSocket proxying correctly, but it has to be configured, never assumed. A load balancer has a second concern once the handshake succeeds: a connection is sticky by nature, since every frame for its entire lifetime must reach the same backend instance that holds its in-memory state; the normal new-TCP-connection distribution strategy for stateless HTTP works here by default, since each connection is exactly one TCP connection for its whole life. And underneath all of it: a WebSocket has no backpressure signal above TCP's own send buffer. If a server writes frames faster than a slow client reads them, nothing in the protocol means 'slow down'. That gap is Act E's first production concern.");

// ===== ACT C — THE SHARED DOMAIN ===============================================
divider("C", "The Shared Domain", "The nouns a handling-event feed pushes, and the ones it only references.",
  "This act names the shipping/cargo domain vocabulary a live handling-event feed actually carries, and draws the seam around what it leaves to the REST booking service by design. Every protocol chapter up to this point pushed bytes without naming what they meant; this act closes that gap before the contract chapters build a formal schema on top of it.");

diagram("THE DOMAIN · THE RECAP", "The shipping/cargo domain, recapped for a live feed",
  "04-domain-model",
  "What a HandlingEvent names, versus what it carries as plain identifiers and values.",
  "Every site in this series describes the same shipping/cargo domain from a different angle: REST models it as resources, gRPC as Protobuf messages passed to typed RPCs. This site cares about one narrow slice: the stream of events that fire while a booking moves from accepted to delivered. A Booking is an agreement to move Cargo from an origin to a destination, following a Route made of Legs between Locations identified by UN/LOCODE; none of that is new, it's the same glossary the REST and gRPC siblings already define. What this site adds is the HandlingEvent: a record of something that happened to a booking's cargo in the physical world, gated in, loaded, held by customs, delivered, and the one message type this socket ever sends. The REST booking service still owns the full Booking and Cargo records, their current state and history; this feed does not duplicate that ownership. A HandlingEvent carries enough to tell a watching client that something changed and what, and no more than that.");

diagram("THE DOMAIN · THE CHANNEL", "The live handling-event feed: one channel, one direction",
  "04-handling-event-feed",
  "The REST booking service's write path triggers a push; its read path still answers on request.",
  "A handling-event feed is a single WebSocket channel scoped to exactly one booking per connection: a client opens one connection per booking it wants to watch, there is no multiplexed 'all my bookings' channel in this contract. The server pushes one HandlingEvent every time a new event is recorded, in the order it registers them, and this is a receive-only operation: server to client, period. The client never sends a message back on this channel; opening the connection and keeping it open is the entire client-side contract. That one-directional shape is a direct consequence of the real-time problem this deck opened with: a client watching a booking doesn't need to ask the server anything once the socket is open, it needs to be told, exactly once per event, the instant each one is recorded. The scope-per-connection design costs more file descriptors and handshakes up front than one shared multiplexed channel would, in exchange for a simpler authorization story: a connection's access decision is 'can this caller watch this one booking,' answered once at connect time.");

content("THE DOMAIN · WHAT TRAVELS", "The nouns, and which ones travel on the wire",
  ["Booking and Cargo appear only as prefixed identifiers (bkg_, crg_), never as embedded objects",
   "Location is a bare UN/LOCODE string, not a richer place object with a name and coordinates",
   "Route, Leg, and Operation belong to the shared domain but never appear on this message at all",
   "A HandlingEvent records a fact that already happened, not a schedule of what's planned to happen next"],
  "Not every noun in the shared glossary appears the same way in a HandlingEvent message. Booking appears only as bookingId, a prefixed identifier matching the channel path's own parameter: the message never repeats the booking's status or route, only names which booking the event belongs to. Cargo appears the same way as cargoId, distinct from bookingId because one booking can cover more than one piece of cargo, and a hold on one container doesn't imply the whole booking is held. Location is exactly a UN/LOCODE string, narrower than how Location might appear elsewhere as a fuller object, because a HandlingEvent says where something happened in the one form a client needs to show it on a map or manifest line. Route, Leg, and Operation are domain nouns this site shares with its siblings but that this contract never carries: a Route's legs explain how cargo is scheduled to move, while a HandlingEvent records that something already happened. Readers who want a route's shape find it defined where it's owned: the REST and gRPC sites' own chapters.");

content("THE DOMAIN · VOCABULARY", "Event vocabulary, and Money as a decimal string",
  ["Eight HandlingEventType members, with an UNSPECIFIED zero value the server never sends",
   "occurredAt and registeredAt are two separate fields because they answer two different questions, not one collapsed into the other",
   "Money is a decimal string (\"125.00\"), never a JSON number: a float can drift a cent, a string parsed as decimal never does",
   "voyageNumber and amount are present only when the specific event kind actually has one, never padded with a sentinel"],
  "HandlingEventType names what kind of event occurred: RECEIVE, LOAD, UNLOAD, CUSTOMS, CLAIM, HOLD, DELIVERED; plus a zero value, HANDLING_EVENT_TYPE_UNSPECIFIED, that the server never sends but that gives a deserializer a safe, checkable fallback instead of crashing on an unrecognized value. Two fields carry time, and the gap between them is domain-meaningful, not incidental: occurredAt is when the event physically happened, registeredAt is when the system recorded it, and registeredAt is always greater than or equal to occurredAt: a customs hold opened at 9:12 AM might not reach a keyboard until a paper manifest is processed hours later, and collapsing both into one timestamp answers neither question a client actually needs answered. Money is typed as a decimal string matching a fixed pattern, never a JSON number, for the same reason the REST site's JSON Schema and the gRPC site's Protobuf type both commit to it: JSON numbers are IEEE 754 doubles that can't represent every decimal fraction exactly, and a cent of drift introduced somewhere downstream is a risk no wire format should carry when a string sidesteps the question entirely.");

content("THE DOMAIN · THE SEAM", "The seam: what the socket replaces, and what it doesn't",
  ["The booking service stays the one place current state lives: this feed is not a second database holding a competing copy",
   "No replay or catch-up on reconnect: a client re-fetches current state from the booking service and resumes watching from there",
   "Authorization follows the same identity and permission data the REST GET already checks against the same booking",
   "A disconnect leaves a real gap this contract alone does not promise to fill; Act E returns to exactly this limit"],
  "This chapter says precisely what the socket replaces and what it does not. The REST booking service remains the one place a Booking's and Cargo's full current state lives: this feed is not a cache a client could query instead of calling the booking service for 'what is true right now.' A client's correct sequence is: call the booking service once to get current state, open the handling-event socket to learn about every change from that point forward, and never call the booking service again just to check whether something changed: that single question is what the socket answers instead. That division draws a sharp line: a client that disconnects and reconnects does not get the events it missed replayed automatically from this contract alone. There is no catch-up operation, no persisted history a client can request. A client that needs to reconcile a gap calls the booking service's own read endpoint to re-fetch current state and resumes watching the socket from there. Act E comes back to this exact gap with two different answers: one stateless, one backed by a durable log.");

// ===== ACT D — THE CONTRACT STORY ==============================================
divider("D", "The Contract Story", "Giving a socket the same discipline a REST resource or a .proto already has.",
  "A REST endpoint publishes its contract in the request method, path, and response schema. A gRPC service publishes it as a compiled .proto that produces the client stub directly. A WebSocket has neither: this act builds the AsyncAPI 3 contract that fills that gap, the message design decisions that make the contract survive scrutiny, and the evolution discipline that keeps an already-open connection from breaking the day the schema has to change.");

content("THE CONTRACT · WHY IT'S NEEDED", "Why a socket needs a contract",
  ["A REST response carries its own verdict in the status line; a WebSocket frame carries nothing that marks it as data vs. error",
   "An undocumented socket fails silently: the connection stays open and healthy while the two ends quietly disagree about meaning",
   "A contract gives a change a diff to review before it ships, and a document a client's test suite can assert against",
   "One channel, one message, one direction: still the same object model a far larger AsyncAPI document would use"],
  "A REST endpoint publishes its contract in the request method, the path, and a response schema a client can diff against reality one call at a time. A gRPC service publishes it as a compiled .proto that produces the client stub directly: contract and code are the same artifact. A WebSocket connection has neither. Nothing about HTTP's request/response pairing applies past the upgrade: there is no status code to inspect per message, no schema validation unless something is told what the valid messages are. That gap is where undocumented sockets fail: a client guesses a message's shape from a sample payload a teammate pasted into chat, the server adds a field, and the client's parser either drops it silently or throws on a value it's never seen; the connection itself stays open and healthy, so nothing about the transport signals the contract broke. AsyncAPI is built for exactly this shape of problem: one or more participants pushing asynchronous messages over a long-lived channel, whether that channel is a WebSocket, a Kafka topic, or an MQTT queue.");

diagram("THE CONTRACT · THE SHAPE", "AsyncAPI 3 in one page: the object model",
  "05-asyncapi-object-model",
  "Servers, channels, operations, components: each one referencing the layer below it.",
  "An AsyncAPI 3 document is four top-level sections, each describing one layer of the system, each referencing the layer below it. Servers names where a connection is made: host, protocol, any connection-level detail like required headers or query parameters. Channels names an address a connection is scoped to and the messages that can flow on it; a channel is not a direction, it's a place. Operations is where direction actually enters the document: each operation names an action, send or receive, against one channel, from the perspective of the application the document describes. Components holds the reusable building blocks, chiefly messages and schemas, referenced by reference rather than inlined everywhere they're used. That operations live outside channels is the single biggest change from AsyncAPI 2.x, where a channel object carried its own publish and subscribe keys directly, nested in a way that made a channel and its direction one piece of YAML. Pulling direction into its own top-level section is what makes a channel direction-agnostic and lets a second operation attach later without touching the channel definition at all.");

diagram("THE CONTRACT · THE PAYOFF", "One contract, two stacks",
  "05-contract-to-two-stacks",
  "One contract, two stacks: neither implementation reads the other's source.",
  "Two independent implementations of the same channel, Quarkus on WebSockets Next, Python on FastAPI plus the native websockets library, and neither is a port of the other's source code. What keeps a client written against one interchangeable with a client written against the other is that both answer to the same reviewed AsyncAPI document: a Quarkus handler and a Python connection coroutine each deserialize the identical message shape, reject the identical malformed payload, and reject the identical invalid identifier; not because either implementation imports the other, but because both are implementations of the same file. Contract-first here means the contract is reviewed and validated first, and the code that follows is checked against it: a narrower claim than a Protobuf compiler that mechanically produces client code from the same source, since there's no equivalent compiler step for a hand-maintained AsyncAPI document the way there is for Protobuf. The payoff is still real: a reviewer reading a pull request against the contract sees the whole message shape change in one diff, before any handler on either stack has to be touched to match it.");

diagram("MESSAGE DESIGN · THE SHAPE", "Envelope vs. payload: one flat object, two roles",
  "06-message-envelope",
  "The contract keeps one flat message; envelope and payload are roles nine fields play, not a nesting the JSON has.",
  "A lot of WebSocket tutorials reach for an explicit envelope: a wrapper object with a type, a timestamp, a correlation id, and a nested data field holding the content. This contract defines one flat schema instead: no data field, no nested payload. eventId, eventType, occurredAt, and registeredAt do the job an explicit envelope would otherwise do: identity, discrimination, timing. But they sit at the same level as bookingId, location, and amount, the fields that describe what happened. Envelope and payload are roles those fields play, not a nesting the JSON has. A REST response's envelope is the HTTP response itself, status code, headers, body, and a gRPC call's envelope is the RPC itself. A WebSocket message has no equivalent, since HTTP's status line belongs to the one-time upgrade handshake, not to the frames that follow, so whatever an envelope would carry has to live in the message body if it's needed at all. An explicit envelope pays for itself only when a channel carries several distinct message families and a dispatcher needs to branch before it knows which schema to parse against. This channel carries exactly one.");

diagram("MESSAGE DESIGN · THE DISCRIMINATOR", "One message or many: the eventType discriminator",
  "06-one-vs-many-messages",
  "Same seven event kinds either way; the discriminator puts the branching in one enum instead of seven schemas.",
  "Every one of the seven event kinds rides the same HandlingEvent schema; eventType is what a consumer switches on to decide what the rest of the message means. The alternative, one AsyncAPI message schema per event kind, is a real, supported design that buys per-kind type safety: a LoadedEvent schema could make voyageNumber required since every LOAD event has one. The cost shows up at the edges this contract cares most about: evolution and cross-stack consistency. Adding an eighth event kind to the discriminated design is one new enum value and one new switch arm in code already written to expect the discriminator to grow. Adding an eighth kind to the per-schema design is a new message definition, a new channel reference, and new generated types on both stacks, landing on the same release. Both stacks are required to deserialize this feed identically: one discriminated schema gives them one thing to stay in sync on, where seven schemas give them seven. The per-kind field tightening is real, but every conditionally required field is already optional in the shared schema, which is the next point this act makes.");

content("MESSAGE DESIGN · WHAT SURVIVES", "Field shapes that survive: IDs, timestamps, enums",
  ["Identifiers carry their type in the string: evt_, bkg_, crg_ prefixes make a booking/cargo mix-up visible in the string itself",
   "Timestamps are two fields because they answer two different questions, not one collapsed into a single ambiguous value",
   "Enums get an explicit, never-sent zero value so a deserializer always has a safe, checkable default",
   "Optional fields stay nullable: no sentinel value standing in for 'not applicable' that a naive sum would silently fold in"],
  "Message design is mostly about choosing field shapes that won't need to change meaning later, because a client already deployed against the old meaning has no way to find out it changed. Identifiers carry their type in the string: a bare ULID is indistinguishable from any other ULID in the codebase, and the prefix makes a mix-up visible in the string itself rather than discoverable only when a downstream lookup fails. Timestamps are two fields, not one, because occurredAt and registeredAt answer two different questions, and collapsing them forces a choice between two true facts that will eventually be wrong for a delayed event. Enums get an explicit, never-sent zero value for the same reason a struct field needs some starting value before a real one is assigned; naming that slot UNSPECIFIED and documenting that the server never sends it makes an UNSPECIFIED showing up client-side unambiguous evidence of a bug, not a seventh ordinary kind of event. Optional fields stay nullable rather than defaulted to a sentinel: a sentinel is a trap for exactly the kind of code this discipline exists to prevent, like a client that sums every amount across a stream without checking for absence first.");

content("EVOLUTION · THE TEST", "What counts as breaking, for a socket",
  ["The test: does any code compiled before this change have to look at the part that's different",
   "Breaking: removing a field a client already reads, changing a field's type in place, repurposing an enum member's meaning",
   "Safe: adding a new optional field, adding a new enum member, if every consumer treats an unrecognized value generically",
   "JSON's tolerance for an added field is a deserializer setting the team has to configure, not a protocol guarantee like Protobuf's"],
  "A gRPC message carries field numbers, not names, and an old reader skips a field it doesn't recognize by construction: Protobuf's wire format does the forward-compatibility work without any application code written for it. JSON over a WebSocket carries field names, and whether an old reader skips a name it doesn't recognize is a property of whichever JSON library deserialized the message, not of the wire format itself; a strict deserializer fails closed on an unrecognized property unless explicitly configured otherwise. With that tolerance assumed, a short list of changes breaks an already-running client: removing a field a client already reads, changing a field's type or unit in place, repurposing an existing enum member's meaning, making a previously optional field required. A longer list doesn't: adding a new optional field, adding a new enum member as long as every consumer treats an unrecognized value as 'handle me generically,' adding a new channel path version, adding a second subprotocol token while still serving the first. The judgment call is never how big the diff looks: it's whether any code compiled before this change has to look at the part that's different.");

diagram("EVOLUTION · THE HARD CASE", "The already-connected-client problem",
  "07-connected-client-migration",
  "A connection opened before the deploy outlives it; the dual-publish window is what keeps it alive and correct.",
  "Here is the part with no REST or gRPC unary analog at all. A REST client's contract is renegotiated, implicitly, on every request: it sends a request, gets a response built against whatever the server looks like right now, and is done. A WebSocket connection makes exactly that commitment for however long it stays open. A client that connected before a deploy changed what the server pushes is still on that connection an hour later, a day later, if nothing closes it; every message from the deploy onward is whatever the new server code decided to send, over a socket opened against the old contract with no chance to renegotiate. A rolling deploy makes three populations exist at once for the whole length of the rollout: clients still on an old instance, clients that reconnected mid-rollout onto whichever version happens to be live, and clients connecting for the first time after it finishes. There is no mid-connection renegotiation: subprotocol, extensions, and channel path are all fixed at handshake time. 'Already connected' can mean for days, if this feed's typical connection lifetime runs that long.");

diagram("EVOLUTION · THE LEVERS", "Versioning strategies, and the evolution gate",
  "07-evolution-gate",
  "The evolution gate: four kinds of contract change, each with a safe addition above and the breaking mutation below.",
  "Three places a version can live, and each answers a different question about when an already-open connection finds out something changed. Channel path is the coarsest lever: a server registers both paths at once, a connection's path is fixed the moment the handshake completes, so a client on the old path keeps receiving whatever that route sends for the rest of its life. Reach for this when the change is structural enough that expressing both shapes through one handler would mean branching on version everywhere inside it. Subprotocol is finer-grained: one channel path, one route handler, but the handler reads which subprotocol this particular connection negotiated and serializes to match it, the way an HTTP endpoint reads an Accept header. Message-level version field is the finest-grained lever and the only one that doesn't require a new handshake at all: a connection negotiated months ago can start receiving a new shape without ever reconnecting, at the cost of every message handler branching on that version field forever. Bump the path when the channel itself is different; bump the subprotocol when the channel is the same but reconnecting is acceptable; add a message field when the payload has to change under connections that can't be relied on to reconnect.");

content("EVOLUTION · THE LIMIT OF UNSPECIFIED", "Enum evolution, and the limits of an unspecified zero",
  ["UNSPECIFIED gives a type a safe default before a value is assigned: that's the whole guarantee it makes",
   "It does not, by itself, rescue a future value a client doesn't recognize yet; that needs code written to catch the failure",
   "A defensive deserializer maps an unrecognized value to UNSPECIFIED instead of failing the connection outright",
   "Without that catch, 'add a new enum member' quietly becomes a breaking change for any client built before it existed"],
  "It is tempting to read a never-sent UNSPECIFIED zero value as 'the enum already has a forward-compatibility story built in: anything we don't recognize becomes UNSPECIFIED.' It doesn't, not automatically, and the gap between what the zero value buys and what it sounds like it buys is worth being precise about. What UNSPECIFIED solves is a narrower, real problem: giving the type a safe default to initialize into before a value has been assigned. What it does not do is rescue a future value a client doesn't recognize yet. Protobuf enums are open by design: an unrecognized integer on the wire is preserved rather than rejected. A JSON string enum, as generated by a typical model class, is closed by default: an unrecognized string is a validation failure, not a fallback to the zero value, unless the deserialization path is explicitly written to catch that failure and map it to UNSPECIFIED. Adding a new enum member is a safe change only if every consumer already has that catch-and-fall-back branch in place. Without it, 'add a new enum member' quietly becomes breaking for any client that hasn't been updated yet.");

// ===== ACT E — PRODUCTION CONCERNS, IN CONCEPT =================================
divider("E", "Production Concerns, in Concept", "Nine things a long-lived connection makes you own that request/response never did.",
  "This is the long middle of the deck. Nine concerns, each one a direct consequence of holding a connection open instead of answering one request and forgetting it: backpressure, error signaling, liveness, reconnect, security, scale-out, binary encoding, observability, and the anti-patterns every one of those concerns tends to produce under deadline pressure. Each slide is concept-level: the stack-specific implementation lives in the 201 decks.");

diagram("PRODUCTION CONCERNS · BACKPRESSURE", "Backpressure: the server's bounded buffer",
  "12-outbound-buffer-policy",
  "Two trigger signals, a full buffer, or one send past its timeout, and two policies for what happens next.",
  "A server pushing to many connections needs a bounded outbound path for a sharper reason than a client needs one: one slow client can only hurt itself if nothing bounds the buffer in front of it, but a server with no bound multiplies that cost by every connection it happens to be serving, turning one stalled client into an unbounded-memory problem for the whole process. Two independent signals say a consumer has fallen behind: the buffer itself fills up, meaning a sustained rate mismatch, or a single send call hangs past a timeout, meaning the client's TCP receive window is full because it stopped reading entirely. Either one trips a configured policy. CLOSE is the safer default: close the connection, stop sending whatever remains, because an unbounded number of slow clients each holding unbounded outstanding sends is a resource-exhaustion path for the server itself. DROP discards the offending event and keeps the connection open, appropriate only when a channel's events are superseded values rather than discrete facts; a handling event is a fact about cargo movement, which is exactly why this feed's own default is CLOSE, not DROP.");

diagram("PRODUCTION CONCERNS · ERRORS", "Error handling: two signaling channels",
  "13-error-flow-vs-1006",
  "A close code alone arrives as the socket is going away, too late to carry detail; the envelope is sent first.",
  "An HTTP response carries its own verdict in the status line, arriving before a single byte of body is read. A WebSocket has no equivalent: once the upgrade completes, every frame is just a frame, with no header field marking one as an error and another as data. The only built-in signal is a close code, and it arrives only as the connection is already ending, too late to carry a sentence of detail a developer debugging their own client could act on. So every real WebSocket application builds a second, in-band channel on top of the one the protocol provides: a plain JSON error envelope, sent while the connection is still open, read by the same message handler already wired up for ordinary push frames. The discipline is narrow: send the envelope when there's a specific offending message to annotate and the connection is still open to send it on; rely on the close code alone when there isn't, or when replying at all would open a signature oracle. No close code, in either range, can ever represent a peer that vanished before any handshake completed: that's the one gap no amount of application-level signaling can close.");

diagram("PRODUCTION CONCERNS · LIVENESS", "Liveness: why TCP won't tell you the peer is gone",
  "14-idle-timeout-trap",
  "Idle-timeout resets on the server's own outbound ping: a silent peer never trips it. Only a pong-tracked sweep does.",
  "TCP's own failure signals are weaker than they look for detecting a dead peer. If a peer's machine loses power or a network partition swallows packets silently, TCP can sit there indefinitely believing the connection is still open: the classic half-open connection problem. Protocol-level ping/pong exists to probe this actively, but the obvious way to wire up detection has a trap in it: turning on an auto-ping and an idle-timeout looks complete on paper, but an idle-timeout typically resets on any read or write on the connection, and the server's own outbound ping is write activity on that same connection. A peer that never answers a single ping and a peer answering every one look identical to a mechanism that was never actually watching for a pong; it was watching for any traffic, and the server guarantees there's always some. The fix tracks pongs explicitly: a timestamp stamped only by an actual pong, checked by a separate sweep on its own schedule, closing anything silent past a configured window. Closing a dead connection is itself a two-way handshake that a truly dead peer can't complete, so detection is bounded, not instant.");

diagram("PRODUCTION CONCERNS · RECONNECT", "Reconnect: stateless vs. replay from a log",
  "16-gap-filled-by-replay",
  "The same disconnect-inject-reconnect sequence; a durable topic behind the socket turns 'lost' into 'filled, exactly once.'",
  "A reconnect loop with backoff and jitter solves one problem: the client notices its connection died and gets a new one. It solves nothing about what happened during the gap. A stateless backplane fans an event out to whoever is subscribed right now and forgets it the instant that call returns: a client that disconnects, misses an injected event, and reconnects with a resume parameter finds the event simply gone, not delayed, not buffered, because there was never anywhere to look it up from. A client that cannot tolerate missing events needs a durable, replayable log behind the socket, not a cleverer reconnect loop. A Kafka topic keyed by booking id, carrying only the events injected after the deterministic fixture seed, lets a reconnecting client's resume parameter resolve to either 'replay everything after this id' or 'replay everything the topic has', and either branch is the correct answer, not a fallback apologizing for a limitation. None of this is free: a broker, a consumer group per instance, and a retention policy that bounds how far back a replay can actually reach are real operational cost a stateless design never has to pay.");

diagram("PRODUCTION CONCERNS · SECURITY", "Security: authenticate at the upgrade",
  "17-auth-upgrade-flow",
  "Both stacks accept the handshake, validate the token first, and close 1008 before any data goes out.",
  "A browser's WebSocket constructor cannot attach a custom Authorization header to the opening handshake: a deliberate limitation, not an oversight, because letting arbitrary script attach arbitrary headers to a cross-origin upgrade would reopen exactly the credential-leakage surface CORS exists to close. That pushes a bearer token somewhere else: a query parameter, or the one list the constructor does accept, subprotocols, and either placement ends up in access logs and proxy traces the way a header rarely does, which is why a short token TTL and wss:// are not optional hardening here, they're what makes that trade-off tolerable. Validate the token as the first thing the connection handler does, before a single frame is sent, checking structure, signature, and expiry in that order against a pinned algorithm. Collapse every failure mode, missing, malformed, bad signature, expired, into the identical close code with no detail echoed to the client: a server that answers differently per failure mode hands a prober a signature oracle, two bits of information an attacker can iterate against one guess at a time. The specific reason stays in a server log for an operator, never on the wire.");

diagram("PRODUCTION CONCERNS · SCALE-OUT", "Scale-out: sticky sessions vs. a backplane",
  "18-sticky-vs-backplane",
  "Sticky sessions pin the client to one instance; only a shared backplane crosses the gap to where an event enters.",
  "A WebSocket connection is stateful in a way an HTTP request isn't: once the upgrade completes, everything a server knows about that connection lives on one specific process for as long as the socket stays open. A sticky load balancer solves exactly that: route every frame for a given client to the same backend instance for the connection's life. What sticky sessions say nothing about is where an event comes from. An event injected through any instance's HTTP endpoint has no sticky session to honor, and even if it did, the thing producing the event has no reason to know which instance happens to be holding the one open connection that cares about it. Closing that second gap needs something every instance shares: a backplane every instance subscribes to and any instance can publish to, a Kafka topic or a Redis channel keyed by booking id. Kafka buys durability and replay at the cost of topic and offset bookkeeping; Redis buys near-zero operational surface and lower latency at the cost of losing anything published while a subscriber wasn't listening. Neither is a universal winner; the contrast is the lesson, not a recommendation.");

diagram("PRODUCTION CONCERNS · BINARY ENCODING", "Binary on the wire: JSON vs. Protobuf",
  "19-two-encodings-one-message",
  "One HandlingEvent, two wire encodings negotiated by subprotocol: Protobuf measuring roughly 40% smaller.",
  "JSON is the right default: a client opens dev tools, reads the frame, and understands it with no decoder. A second, binary wire encoding of the exact same message is additive capability for a feed that's outgrown JSON's overhead, not a wholesale replacement for it. A Protobuf schema mirrors the JSON contract field-for-field, keeping timestamps and amounts as plain strings so a value decoded from either encoding comes out byte-for-byte identical; a client that only ever sees one encoding sees the same values either way. The two encodings are negotiated through the same subprotocol mechanism this deck already introduced for versioning, with JSON as the safe fallback for a client that offers neither. The measured win is real, roughly forty percent smaller frames across the fixture's event types, but it isn't free: a Protobuf frame is opaque bytes until something with the schema decodes it, and a build-time compiler step becomes one more moving part neither stack needed before. The deeper lesson is about identity: a Protobuf field number, not its name, is what the wire actually keys on, and reusing one after a field's removal is a silent data-corruption risk, not a build-time error.");

diagram("PRODUCTION CONCERNS · OBSERVABILITY", "Observability: one connection, many spans",
  "23-auto-vs-manual",
  "Same span name, same trace-id log line, two different paths depending on what the framework auto-instruments.",
  "Distributed tracing's default mental model comes from request/response: a span starts when a request arrives and ends when the response leaves. A WebSocket connection has no one obvious boundary to pick: tracing the whole connection as a single span never closes until a client disconnects, defeating a trace's purpose as a bounded, readable unit of work; tracing each message as its own span obscures that ten messages arrived over the same socket watching the same booking. A framework that auto-instruments HTTP gets the upgrade handshake traced automatically with no extra code, since an upgrade is, at the HTTP layer, a GET request that returns 101 instead of 200; but what happens after the upgrade completes, the actual push over the open socket, needs a manual span added on top, because no mainstream OpenTelemetry ecosystem ships auto-instrumentation for a native WebSocket library. The span boundary itself is a choice scoped to what a given channel does, not a universal rule. What stays local in a minimal deployment is just as important to name: a trace can leave the process over OTLP while a metric and a correlating log line both stay local, pulled or read directly rather than shipped anywhere else.");

diagram("PRODUCTION CONCERNS · ANTI-PATTERNS", "The anti-patterns, and their remedies",
  "24-pattern-remedy-map",
  "Eight anti-patterns and the fix each one already has, cited against where this site caught it live.",
  "Every anti-pattern here already happened in a real build, not as a hypothetical invented to sound thorough. Mistaking activity for liveness: an idle-timeout that resets on the server's own outbound ping never catches a silent peer, because it was never watching for a pong. Assuming a reconnect recovers data: a stateless backplane drops a gap-era event silently, with the HTTP inject call still returning success the whole time. Trusting a size-like parameter's zero value: a bounded queue's maxsize of zero can mean unbounded rather than zero-capacity, the opposite of what almost every other size-like parameter in the same codebase means. Answering an auth failure too precisely: four distinct token failure modes reported differently hand a prober a signature oracle. Treating a wire schema like source code instead of a contract: reusing a binary field number after a field's removal is a silent data-corruption risk no parser flags. Every fix traces to the same root lesson: trusting a signal that looks like the one you need without checking what it actually measures.");

// ===== ACT F — RUNTIME, AND JUDGMENT ===========================================
divider("F", "Runtime, and Judgment", "Where this runs, and the discipline that keeps you from reaching for a socket you don't need.",
  "This closing act moves from protocol and production concerns to two different questions: where does this actually run, and does a given interaction need a socket at all. The same contract and the same two stacks run unmodified across three runtime tiers, and the discipline that keeps a team from over-reaching for a socket is as much a part of mastering this material as building one correctly.");

diagram("RUNTIME · THE PROGRESSION", "The runtime progression: Compose, minikube, OpenShift",
  "00-tier-progression",
  "Three tiers, one contract: Compose for the fast inner loop, minikube and OpenShift Local for a real scheduler.",
  "This site climbs three runtime tiers without either stack's code changing between them. Docker Compose is the fastest inner loop: two services on host ports, one shared contract, LGTM observability one profile flag away rather than on by default, so a reader's first boot isn't slowed down by signal nobody's ready to look at yet. Minikube brings the identical two services up on a real scheduler, Services, and readiness probes, using the docker driver and the containerd runtime rather than Podman, proving the same contract survives an actual platform instead of a fixed set of host ports. OpenShift Local repeats that exercise a third time, as a separate, non-numbered track rather than folded into the minikube chapter, because the two platforms solve different problems: a free local cluster for fast iteration versus a faithful single-node OpenShift for routes, security context constraints, and an operator-managed Kafka. None of the three tiers changes what either service does; each one only changes how a client reaches it and how the platform keeps it running, and that stability is by design: the toolchain and the runtime shape should never be the thing you're debugging once a chapter asks you to reason about a reconnect policy instead.");

content("JUDGMENT · THE ALTERNATIVES", "When you don't need a socket: the alternatives catalog",
  ["SSE when the server is the only side that ever sends, to a browser tab the team controls",
   "Long-polling when the network path doesn't trust a held-open response; webhooks when the receiver can host its own endpoint",
   "gRPC server-streaming when neither end is a browser and both sides already share a Protobuf contract",
   "Plain request/response when nothing is actually live; a message broker for backend-to-backend traffic that was never browser-facing"],
  "Twenty-plus chapters of protocol, contract, reconnection, backpressure, security, and observability later, it's worth returning to the same decision framework Act A opened with, not to re-run it, but to add the question that framework couldn't yet ask: does an interaction already running on a socket still belong there. Reach for Server-Sent Events when the server is the only side that ever sends and the receiver is a browser tab you control: native reconnection and a resume header built into the browser, not written by the application. Reach for long-polling when a network path is known to buffer or truncate long-lived responses, degrading to plain request/response rather than failing outright. Reach for a webhook when the relationship is service-to-service and the receiver can host a reachable endpoint of its own: no connection held between deliveries, no liveness sweep, no backpressure guard. Reach for gRPC server-streaming when both ends are services your own organization runs, sharing a contract, and get real backpressure from HTTP/2 with no extra code. And name HTTP/2 server push directly as a dead end, removed from every major browser; it is not a live option for browser fan-out today.");

content("JUDGMENT · THE LEDGER", "The cost of a socket you didn't need",
  ["Reconnection, liveness, backpressure, fan-out, auth, and tracing are all application code you write, not protocol behavior the transport provides on its own",
   "Idle tabs holding file descriptors for data that rarely changes is the clearest tell a socket was the wrong default",
   "A client-to-server channel that's never carried a message means the duplex capability that justified the socket was never used",
   "Fan-out cost scaling with instance count rather than subscriber count is a sizing problem waiting to surface in production"],
  "Each cost on this slide is a line item this site's own examples paid to keep a long-lived, full-duplex connection correct and operable; none of it hypothetical. Reconnection is application code, not protocol behavior: a reconnect loop solves getting the connection back, not resuming what the gap cost, and fixing that gap took a second backplane mode entirely, with its own topic and its own replay logic. Liveness detection needs its own clock, because the transport's own clock lies: the obvious idle-timeout approach doesn't work, and the real fix is a dedicated scheduled sweep. Backpressure is a hand-rolled guard, not a protocol feature, because a raw WebSocket gives an application nothing here beyond TCP's own flow control. Fan-out across instances needs a backplane and sticky routing, not just more pods. Browser auth gets forced into a query parameter because the handshake has no header slot. Tracing is a hand-written span because the instrumentation mostly doesn't exist yet. None of this argues a socket is wrong everywhere; it argues the decision has to be made the same way every time, for every interaction, rather than defaulted to because the rest of a WebSockets site makes it look obvious.");

// ===== CLOSE ===================================================================
content("101 · CLOSE", "Push, the protocol, and one contract: now go build it in your stack",
  ["The case for push holds on its own merits: a socket earns its cost when both sides need to send, continuously, at low latency",
   "One AsyncAPI contract, two independent stacks, the same evolution discipline either one has to honor as the schema changes",
   "Nine production concerns are the real price of that duplex connection: pay them by design, not by accident under load",
   "For the stack-specific deep dives behind every idea here, see the Quarkus WebSockets Next and Python native-websockets 201 decks"],
  "Bring it back to the one claim this whole deck exists to support: request/response has no channel for a server to speak first, a WebSocket closes that gap, and closing it is worth the real, itemized cost only when the interaction needs continuous, low-latency, full-duplex delivery, not by default because the site is about WebSockets. The protocol underneath that choice is one handshake and one frame format, both stable enough that twenty-some later chapters build on them without re-deriving a single byte. The contract discipline on top of it is the same discipline a REST resource or a Protobuf service already has, adapted for a connection that can't renegotiate mid-life. And the nine production concerns in the long middle of this deck are the itemized bill for holding a connection open instead of answering one request and forgetting it: reconnection, liveness, backpressure, security, scale, encoding, and observability, each one real, each one solved once rather than reinvented per project. Everything on these slides maps to a real chapter and a running two-stack example. For the Quarkus WebSockets Next implementation and the Python native-websockets implementation behind every idea here, the 201 decks are the next stop.");

mainCount = pageNum;

// ===== APPENDIX =================================================================
divider("APPENDIX", "Reference Material", "Deeper detail for look-up, not sequential reading.",
  "Everything from here forward is reference material pulled out of the main narrative so the body of this deck could stay close to fifty slides. Nothing in the appendix is required to follow the six acts that came before it; reach for a slide here when a conversation needs the close-code taxonomy in full, the AsyncAPI 2.x-to-3.x contrast spelled out, a deprecation-window checklist, the lab topology, the full transport comparison matrix, or the toolchain version matrix this site pins against.");

content("APPENDIX · ASYNCAPI VERSIONS", "AsyncAPI 3 vs. 2.x: why operations moved out of channels",
  ["2.x nested publish/subscribe directly under each channel: direction and address were one piece of YAML",
   "3.x pulls operations into their own top-level section, each with an explicit send or receive action and a reference back to its channel",
   "A channel in 3.x is direction-agnostic: it names an address and the messages that can appear on it, nothing more",
   "The same object model now generalizes cleanly across WebSocket, Kafka, and MQTT channels, since the verb lives in the operation, not borrowed from one protocol's vocabulary"],
  "Readers coming from an AsyncAPI 2.x document, or from an OpenAPI background where paths and operations live together, will look for a publish/subscribe pair nested under each channel and not find one. That nesting is exactly what 3.x removed. In 2.x a channel object carried its own publish and subscribe keys directly, so the channel and its direction were one piece of YAML, and a reader had to infer from the key's name which side was doing what. 3.x pulls operations out to its own top-level section, each a standalone object with an explicit action and a reference back to the channel it applies to. The concrete effect: a channel has no notion of direction baked in at all, and a separately declared operation is the one fact that a given channel's direction runs server-to-client. A second operation, a future client-to-server acknowledgment, say, would be a second entry under operations, referencing the same channel, without touching the channel definition itself. That separation is what makes the object model reusable across transports that don't share HTTP's publish/subscribe metaphor at all.");

table("APPENDIX · CLOSE CODES", "Close-code taxonomy: RFC 6455 and this site's own range",
  [
    { code: "1000", name: "Normal Closure", purpose: "Purpose complete; the ordinary clean, mutually-agreed close." },
    { code: "1001", name: "Going Away", purpose: "Server shutting down, or client navigating away from the page." },
    { code: "1002", name: "Protocol Error", purpose: "Peer sent a frame that violates RFC 6455 framing rules." },
    { code: "1003", name: "Unsupported Data", purpose: "A text-only endpoint received binary, or vice versa." },
    { code: "1006", name: "Abnormal Closure", purpose: "Reserved: never sent on the wire; synthesized locally when no handshake occurred." },
    { code: "1008", name: "Policy Violation", purpose: "Generic rule violation; this site reuses it as-is for an auth failure." },
    { code: "1009", name: "Message Too Big", purpose: "Server refused a message past a configured size limit." },
    { code: "1011", name: "Internal Error", purpose: "Unexpected server condition; this site's generic backstop code." },
    { code: "4000-4999", name: "Application-defined", purpose: "Private-use range: 4400 bad request, 4290 slow consumer, 4408 liveness timeout." },
  ],
  "RFC 6455 reserves four numeric bands, and knowing which band a code lives in tells a client whether it's reading a standard protocol-level reason or an application's own convention. 1000 through 1015 are the protocol's own defined codes; 1006 and 1005 specifically can never appear in an actual close frame on the wire; they exist only for a client-side API to report locally that a connection ended with no handshake at all. 3000-3999 is registered through IANA for libraries that want a standard code without squatting on the protocol's own range. 4000-4999 is explicitly private-use, the one band set aside for an application to define its own vocabulary with zero collision risk against a future protocol code. This site reuses RFC codes for exactly the meaning the spec already assigns them and places every code it invents into the private range, so a client's reconnect logic can use the band itself as a first signal before it even needs this site's specific documentation.");

content("APPENDIX · EVOLUTION IN PRACTICE", "Deprecation and dual-publish windows",
  ["Size the window against observed connection lifetimes, not deploy duration; a twenty-minute deploy says nothing about the longest open tab",
   "Close in two steps: stop offering the old version to anything new, then close stragglers once the old version's live-connection count reaches zero",
   "Use an application close code in the 4000-4999 range for a planned retirement, not a generic 1001 that gives a client's retry logic nothing to act on",
   "Three populations exist at once during any rollout: clients on the old version, clients that migrated mid-rollout, and clients connecting fresh"],
  "A dual-publish window is the period during which a server serves both the old and new shape of something at once, so that no already-connected client ever sees a contract break mid-connection. Closing it too early reopens exactly the problem it exists to prevent. Size the window against the connection population's actual behavior, a dashboard tab left open overnight, a mobile client that only reconnects when relaunched, not against how long the deploy itself takes. The right input is a histogram of this feed's own connection durations: the window needs to outlast whatever was already open when the new shape started being served, which in practice means watching the old version's active-connection count reach zero, not assuming a calendar date is close enough. Close it in two steps, not one: first stop offering the old version to anything new while every already-negotiated connection keeps running untouched, then once telemetry shows zero live connections on the old version, close any stragglers with an application-defined close code a client's reconnect logic can actually act on.");

diagram("APPENDIX · THE LAB", "The lab topology: one contract, two servers",
  "00-lab-topology",
  "The lab: one contract, two servers, OTel off by default.",
  "The Docker Compose lab every chapter's own example builds against brings up two services: Quarkus on one host port, Python on another, both exposing the same channel path and both generated against the identical AsyncAPI contract. A third service, the Grafana LGTM observability stack, sits behind an opt-in profile flag rather than starting by default; both applications are wired for OTLP export unconditionally, but neither requires a collector to be listening to start cleanly, and four extra containers on every reader's first boot would slow the inner loop down for no signal before there's a trace worth looking at. The profile exists so observability is one flag away the moment a chapter's content makes a trace worth examining. Tearing the lab down is one command with two flags that matter: removing named volumes, since the observability stack persists trace and metric data between runs, and removing orphaned containers left behind by an earlier, interrupted run: the discipline that makes 'run the lab, see it fail, fix the handler, run it again' a loop that never accumulates state between attempts.");

table("APPENDIX · TRANSPORT REFERENCE", "Transport decision reference: the full comparison",
  [
    { code: "Direction", name: "Either side, anytime", purpose: "SSE: server-only. Webhook: sender-initiated, roles reversed entirely." },
    { code: "Duplex", name: "Full, by protocol", purpose: "Long-poll and webhook are half-duplex request/response; SSE has no client half at all." },
    { code: "Ordering", name: "FIFO per connection", purpose: "Webhooks are the outlier: not guaranteed in order across retried deliveries." },
    { code: "Backpressure", name: "App-managed, no protocol support", purpose: "gRPC streaming gets it free from HTTP/2 flow-control windows." },
    { code: "Proxy/firewall", name: "Needs Upgrade support", purpose: "SSE, long-polling, and webhooks all ride plain, broadly-compatible HTTP." },
    { code: "Reconnection", name: "Application writes it", purpose: "SSE reconnects itself via Last-Event-ID; long-polling self-heals by construction." },
  ],
  "This is the full comparison table behind Act A's decision framework, kept here for look-up rather than repeated in the main narrative. Each row is one dimension a team has to weigh when an interaction's shape isn't obvious on first read. Direction asks who may originate a message at all; duplex asks the sharper version of the same question, whether both directions can carry traffic at once or one has to finish before the other starts. Ordering and backpressure matter once more than one update is ever in flight: a WebSocket and SSE both guarantee FIFO delivery because each is a single ordered stream, while webhooks offer no such guarantee across independently-retried deliveries, pushing the reordering problem onto the receiver. Proxy and firewall behavior decides whether a transport survives a network path nobody on the team controls: a WebSocket's opening handshake is exactly what breaks on an unconfigured intermediary. Reconnection separates a transport that heals itself by construction from one that makes the application write every bit of the healing logic by hand.",
  { colW: [2.1, 2.3, 7.69] });

table("APPENDIX · GLOSSARY & VERSIONS", "Glossary and version matrix",
  [
    { code: "HandlingEvent", name: "JSON / Protobuf message", purpose: "One record of something that happened to cargo: RECEIVE through DELIVERED." },
    { code: "AsyncAPI 3.0", name: "Contract specification", purpose: "servers / channels / operations / components describing this channel." },
    { code: "Quarkus", name: "3.40.0", purpose: "WebSockets Next extension, built on JDK 25.0.4." },
    { code: "Python", name: "3.15.0", purpose: "FastAPI for HTTP routing, paired with the native websockets library for the socket." },
    { code: "Kafka", name: "4.3.1 (KRaft mode)", purpose: "Durable backplane behind the Kafka-backed replay and cross-instance fan-out." },
    { code: "Redis", name: "8.10.2-alpine", purpose: "Pub/sub backplane alternative: fan-out without replay, at a fraction of the operational cost." },
    { code: "Close code", name: "4000-4999", purpose: "This site's own private-use range for application-specific rejections." },
  ],
  "A short glossary and the toolchain version matrix this site pins against, for look-up during a conversation rather than memorized ahead of one. HandlingEvent is the one message type this feed ever sends, flat and discriminated by an eventType enum rather than split into per-kind schemas. AsyncAPI 3.0 is the contract specification itself: the WebSocket analog of OpenAPI for REST or a .proto package for gRPC. The toolchain rows are surveyed to current stable releases rather than an older LTS floor, the same posture the REST and gRPC sibling sites take, so a reader installing today lands close to what every example actually targets: JDK 25.0.4 and Quarkus 3.40.0 on one side, Python 3.15.0 on the other, with Kafka 4.3.1 and Redis 8.10.2-alpine as the two backplane options Act E's scale-out concept introduced. Every version here is pinned to an exact release, never a floating tag, and bumped only as a reviewed change when a survey pass finds a newer stable release.",
  { colW: [2.1, 2.3, 7.69] });


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

  addNotes(s, "This is the 101 concepts deck, so the two codes point where the ideas live and where the whole series lives. On the left, the site: the chapters, the AsyncAPI contracts, and the runnable both-stack examples, all public. On the right, the Workshops and Tutorials hub: every workshop, tutorial, and deck in the series in one place. Scan whichever is useful; both are on the Pattern Catalyst GitHub organization.");
}


pres.writeFile({ fileName: OUT })
  .then(p => console.log("WROTE", p, "slides:", pageNum, "main:", mainCount, "appendix:", pageNum - mainCount))
  .catch(e => { console.error(e); process.exit(1); });
