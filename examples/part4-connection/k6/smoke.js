// examples/part4-connection/k6/smoke.js
//
// DRQ-023 — the GATED k6 smoke load for Part 4's connection-concerns
// example. Deliberately SMOKE-level: a handful of VUs, one short iteration
// each, no ramping — this is a fast CI gate that proves the channel still
// accepts an authenticated connection and streams the fixture, not a load
// or stress test (that belongs in a separate, opt-in script this project
// does not ship yet).
//
// Target: ONE stack at a time, selected by the K6_WS_URL env var (the
// `k6-smoke` CI job and README both show the two invocations). Each VU:
//   1. opens `ws://.../ws/v1/bookings/{bookingId}/handling-events?token=...`
//      with a JWT minted against the SAME shared secret verify.sh uses
//      (see K6_TOKEN below — the CI job mints it with the project's own
//      `app/mint_token.py` / `mvn exec` equivalent before invoking k6).
//   2. asserts the upgrade succeeded (status 101).
//   3. reads the 3 seed frames (RECEIVE/LOAD/CUSTOMS — the shared fixture,
//      see ../../part3-handling-events/fixtures/handling-events.json) and
//      asserts each is well-formed JSON with the expected shape.
//   4. holds the connection open briefly (so the server's heartbeat path is
//      touched, Ch14) before closing cleanly.
//
// Run:
//   K6_WS_URL="ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
//   K6_TOKEN="$TOKEN" \
//   k6 run examples/part4-connection/k6/smoke.js
//
// Pinned to k6 2.3.0 (contracts/README.md, Ch0 version matrix, DRQ-023) —
// `k6/ws` is that release's stable WebSocket API.
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
  "ws://localhost:8080/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events";
const TOKEN = __ENV.K6_TOKEN || "";
const EXPECTED_EVENT_TYPES = ["RECEIVE", "LOAD", "CUSTOMS"];
const HOLD_OPEN_MS = 500;

export default function () {
  if (!TOKEN) {
    throw new Error(
      "smoke.js: K6_TOKEN is required — mint one against the shared " +
        "WS_JWT_SECRET (see examples/part4-connection/README.md's k6 section)",
    );
  }

  const sep = WS_URL.includes("?") ? "&" : "?";
  const url = `${WS_URL}${sep}token=${TOKEN}`;

  const frames = [];

  const res = ws.connect(url, {}, function (socket) {
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
