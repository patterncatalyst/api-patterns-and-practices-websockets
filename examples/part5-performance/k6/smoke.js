// examples/part5-performance/k6/smoke.js
//
// DRQ-023/DRQ-027 — the GATED k6 smoke load for Part 5's JSON-vs-Protobuf
// wire-encoding example. Deliberately SMOKE-level (examples/part4-*/k6/
// smoke.js's pattern: a handful of VUs, one short iteration each, no
// ramping) — this is a fast CI gate that proves BOTH negotiated encodings
// still stream the fixture on a live stack, not a load/throughput test
// (that's k6/benchmark.js, and it is explicitly LOCAL-only — DRQ-027).
//
// Target: ONE stack at a time (K6_WS_URL selects Quarkus :8090 or
// Python :8091 — see compose.yaml). This channel has no auth gate (Part 5
// drops part4's four connection concerns, compose.yaml's header comment),
// unlike part4-connection's smoke.js — no token is minted or passed. Each
// VU opens the SAME channel TWICE in one iteration:
//
//   1. Offering `handling-events.v1+json` (Sec-WebSocket-Protocol header,
//      DRQ-026) — asserts the upgrade succeeded (101), the server echoed
//      the offered subprotocol back, and the 3 fixture frames
//      (RECEIVE/LOAD/CUSTOMS) arrive as TEXT (`message` events) and are
//      well-formed JSON with the expected eventType.
//   2. Offering `handling-events.v1+protobuf` — asserts the upgrade,
//      subprotocol echo, and that the 3 fixture frames arrive as BINARY
//      (`binaryMessage` events, ArrayBuffer payload) and are non-empty.
//      This script does not decode the Protobuf bytes (verify.sh already
//      does, against a real generated stub) — it only proves the wire
//      opcode and frame count are right, which is all a CI smoke gate
//      needs.
//
// Binary-frame support confirmed against the PINNED k6 2.3.0 source
// (github.com/grafana/k6 tag v2.3.0,
// internal/js/modules/k6/ws/ws.go:215-218): the stable `k6/ws` module
// (gorilla/websocket-backed) dispatches a dedicated `binaryMessage` event
// with an ArrayBuffer payload for `websocket.BinaryMessage` frames,
// distinct from `message`'s string payload for text frames — no need for
// `k6/experimental/websockets` (or the newer `k6/websockets`) here, and
// this keeps the house pattern consistent with part4's k6/ws scripts.
// `k6/ws`'s Params has no dedicated subprotocols field (same source,
// parseConnectArgs) — the subprotocol is offered the same way any other
// WebSocket client would: a `Sec-WebSocket-Protocol` request header.
//
// Run (repeat per stack):
//   K6_WS_URL="ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
//   k6 run examples/part5-performance/k6/smoke.js
//
//   K6_WS_URL="ws://localhost:8091/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
//   k6 run examples/part5-performance/k6/smoke.js
//
// Set K6_SUBPROTOCOL to "handling-events.v1+json" or
// "handling-events.v1+protobuf" to exercise only one encoding path in a
// given invocation (default: both, in one iteration).
//
// Pinned to k6 2.3.0 (contracts/README.md, Ch0 version matrix, DRQ-023).
import ws from "k6/ws";
import { check } from "k6";

// Smoke-level load: 3 VUs, 1 iteration each, no ramp — fast enough to run
// on every PR without adding meaningful time to the contracts gate.
export const options = {
  scenarios: {
    smoke: {
      executor: "per-vu-iterations",
      vus: 3,
      iterations: 1,
      maxDuration: "30s",
    },
  },
  thresholds: {
    // Any failed check fails the whole k6 run (and thus the CI job) —
    // DRQ-023's "gated", not merely observational.
    checks: ["rate==1.0"],
    ws_session_duration: ["p(95)<10000"],
  },
};

const WS_URL =
  __ENV.K6_WS_URL ||
  "ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events";
const SUBPROTOCOL_FILTER = __ENV.K6_SUBPROTOCOL || "";
const EXPECTED_EVENT_TYPES = ["RECEIVE", "LOAD", "CUSTOMS"];
const HOLD_OPEN_MS = 500;

const JSON_SUBPROTOCOL = "handling-events.v1+json";
const PROTOBUF_SUBPROTOCOL = "handling-events.v1+protobuf";

// Go's http.Header canonicalizes "Sec-WebSocket-Protocol" to
// "Sec-Websocket-Protocol" (textproto.CanonicalMIMEHeaderKey lowercases
// everything but the first letter of each hyphen-separated segment) before
// k6/ws copies the upgrade response's headers into HTTPResponse.Headers —
// compare case-insensitively rather than hardcoding either casing.
function echoedSubprotocol(res) {
  if (!res || !res.headers) return "";
  for (const key of Object.keys(res.headers)) {
    if (key.toLowerCase() === "sec-websocket-protocol") {
      return res.headers[key];
    }
  }
  return "";
}

function checkJsonPath(subprotocol) {
  const frames = [];

  const res = ws.connect(
    WS_URL,
    { headers: { "Sec-WebSocket-Protocol": subprotocol } },
    function (socket) {
      socket.on("open", function () {
        socket.setTimeout(function () {
          socket.close();
        }, HOLD_OPEN_MS);
      });

      socket.on("message", function (data) {
        frames.push(data);
        if (frames.length >= EXPECTED_EVENT_TYPES.length) {
          socket.close();
        }
      });

      // A binary frame on the +json path would mean the server picked the
      // wrong encoding — fail loudly via the frame-count check below
      // rather than silently dropping it.
      socket.on("binaryMessage", function () {});

      socket.on("error", function (e) {
        console.error(`smoke.js: JSON path websocket error: ${e.error ? e.error() : e}`);
      });
    },
  );

  check(res, {
    "JSON path: upgrade accepted (status 101)": (r) => r && r.status === 101,
    "JSON path: server echoed the +json subprotocol": (r) => echoedSubprotocol(r) === subprotocol,
  });

  check(frames, {
    "JSON path: received all 3 seed frames as TEXT": (f) => f.length === EXPECTED_EVENT_TYPES.length,
  });

  for (let i = 0; i < frames.length; i++) {
    let doc;
    try {
      doc = JSON.parse(frames[i]);
    } catch (e) {
      doc = null;
    }
    check(doc, {
      [`JSON path: frame ${i} is valid JSON`]: (d) => d !== null,
      [`JSON path: frame ${i} has the expected eventType`]: (d) =>
        d !== null && d.eventType === EXPECTED_EVENT_TYPES[i],
      [`JSON path: frame ${i} carries the booking id`]: (d) => d !== null && typeof d.bookingId === "string",
    });
  }
}

function checkProtobufPath(subprotocol) {
  const frames = [];

  const res = ws.connect(
    WS_URL,
    { headers: { "Sec-WebSocket-Protocol": subprotocol } },
    function (socket) {
      socket.on("open", function () {
        socket.setTimeout(function () {
          socket.close();
        }, HOLD_OPEN_MS);
      });

      socket.on("binaryMessage", function (data) {
        frames.push(data);
        if (frames.length >= EXPECTED_EVENT_TYPES.length) {
          socket.close();
        }
      });

      // A text frame on the +protobuf path would mean the server picked
      // the wrong encoding — fail loudly via the frame-count check below.
      socket.on("message", function () {});

      socket.on("error", function (e) {
        console.error(`smoke.js: Protobuf path websocket error: ${e.error ? e.error() : e}`);
      });
    },
  );

  check(res, {
    "Protobuf path: upgrade accepted (status 101)": (r) => r && r.status === 101,
    "Protobuf path: server echoed the +protobuf subprotocol": (r) => echoedSubprotocol(r) === subprotocol,
  });

  check(frames, {
    "Protobuf path: received all 3 seed frames as BINARY": (f) => f.length === EXPECTED_EVENT_TYPES.length,
  });

  for (let i = 0; i < frames.length; i++) {
    const data = frames[i];
    check(data, {
      [`Protobuf path: frame ${i} is a non-empty binary ArrayBuffer`]: (d) =>
        d instanceof ArrayBuffer && d.byteLength > 0,
    });
  }
}

export default function () {
  if (SUBPROTOCOL_FILTER === "" || SUBPROTOCOL_FILTER === JSON_SUBPROTOCOL) {
    checkJsonPath(JSON_SUBPROTOCOL);
  }
  if (SUBPROTOCOL_FILTER === "" || SUBPROTOCOL_FILTER === PROTOBUF_SUBPROTOCOL) {
    checkProtobufPath(PROTOBUF_SUBPROTOCOL);
  }
}
