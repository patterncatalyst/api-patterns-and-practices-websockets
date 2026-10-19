// examples/part4-backplane/k6/smoke.js
//
// DRQ-023 — the GATED k6 smoke load for Part 4's backplane example.
// Smoke-level only: a handful of VUs, one short iteration each, against the
// DEFAULT (stateless) profile's single always-up instance — no Kafka/Redis
// bring-up here (that's verify.sh's job, and takes several minutes; this
// script only proves the channel itself is alive, fast enough to run on
// every PR). It does not exercise Ch16 replay or Ch18 fan-out — those stay
// covered by verify.sh.
//
// This channel has no auth gate (PROTOCOL.md) — unlike
// examples/part4-connection, no token is needed. Each VU:
//   1. opens `ws://.../ws/v1/bookings/{bookingId}/handling-events` against
//      ONE instance (K6_WS_URL — the CI job targets quarkus-a or python-a).
//   2. asserts the upgrade succeeded (status 101).
//   3. reads the 3 seed frames (RECEIVE/LOAD/CUSTOMS, delivered
//      unconditionally on every connection regardless of bookingId — see
//      each app's README "Design note") and asserts each is well-formed.
//   4. holds the connection open briefly, then closes cleanly.
//
// Run:
//   K6_WS_URL="ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
//   k6 run examples/part4-backplane/k6/smoke.js
//
// Pinned to k6 2.3.0 (contracts/README.md, Ch0 version matrix, DRQ-023) —
// `k6/ws` is that release's stable WebSocket API.
import ws from "k6/ws";
import { check } from "k6";

// Smoke-level load: 3 VUs, 1 iteration each, no ramp.
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
    checks: ["rate==1.0"],
    ws_session_duration: ["p(95)<10000"],
  },
};

const WS_URL =
  __ENV.K6_WS_URL ||
  "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events";
const EXPECTED_EVENT_TYPES = ["RECEIVE", "LOAD", "CUSTOMS"];
const HOLD_OPEN_MS = 500;

export default function () {
  const frames = [];

  const res = ws.connect(WS_URL, {}, function (socket) {
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

    socket.on("error", function (e) {
      console.error(`smoke.js: websocket error: ${e.error ? e.error() : e}`);
    });
  });

  check(res, {
    "upgrade accepted (status 101)": (r) => r && r.status === 101,
  });

  check(frames, {
    "received all 3 seed frames": (f) => f.length === EXPECTED_EVENT_TYPES.length,
  });

  for (let i = 0; i < frames.length; i++) {
    let doc;
    try {
      doc = JSON.parse(frames[i]);
    } catch (e) {
      doc = null;
    }
    check(doc, {
      [`frame ${i} is valid JSON`]: (d) => d !== null,
      [`frame ${i} has the expected eventType`]: (d) =>
        d !== null && d.eventType === EXPECTED_EVENT_TYPES[i],
      [`frame ${i} carries the booking id`]: (d) => d !== null && typeof d.bookingId === "string",
    });
  }
}
