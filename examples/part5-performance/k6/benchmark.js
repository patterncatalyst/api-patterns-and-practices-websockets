// examples/part5-performance/k6/benchmark.js
//
// DRQ-027 — the comparative, LOCAL-ONLY k6 throughput/size benchmark for
// Part 5's JSON vs. Protobuf wire encodings (plus a permessage-deflate
// variant — RFC 7692). NOT part of the CI gate (see smoke.js for that):
// absolute throughput numbers are host-dependent, which would make a flaky
// CI threshold — this script is meant to be run by hand against a stack on
// your own machine, and its printed comparison cited in prose (Ch20), the
// same decision smoke.js's own header documents (DRQ-023/DRQ-027).
//
// What this measures, and what it does NOT:
//
//   This channel's server-push shape is "replay the 3 fixture events on
//   connect, then stay open with no further pushes"
//   (quarkus/.../HandlingEventPerformanceWebSocket.java,
//   python/app/ws_server.py's `_replay` + `wait_closed`) — there is no
//   sustained in-connection message stream to measure. So each VU here
//   repeatedly does the only thing this channel supports: open a fresh
//   connection, read exactly 3 frames, close, and loop — as fast as it
//   can for the sustained-load window. "messages/sec" below is therefore
//   CONNECTION-CHURN throughput (connects/sec * 3), not a steady per-
//   connection push rate; see the printed summary's own labels.
//
//   permessage-deflate: `k6/ws`'s Params.compression: "deflate" asks
//   gorilla/websocket (the library behind the stable k6/ws module) to
//   offer the extension on the upgrade request. If the server negotiates
//   it, gorilla TRANSPARENTLY INFLATES each compressed frame before this
//   script ever sees its bytes — there is no k6/ws API to read the
//   on-the-wire compressed length. The `json_deflate` scenario's
//   bytes-per-frame Trend therefore measures the same POST-INFLATION
//   payload size as the plain `json` scenario by construction; it proves
//   nothing about deflate's wire savings. What this script DOES prove,
//   honestly, is whether the extension was negotiated at ALL (the
//   `permessage-deflate negotiated` line in the summary, read from the
//   upgrade response's echoed `Sec-WebSocket-Extensions` header) — see
//   examples/part5-performance/README.md's k6 section and Ch20's
//   CRIME-caveat discussion for why this project doesn't lean on
//   permessage-deflate for this channel regardless of whether a given
//   stack happens to negotiate it.
//
// Usage:
//   docker compose -f examples/part5-performance/compose.yaml up --build -d
//   K6_WS_URL="ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events" \
//     k6 run examples/part5-performance/k6/benchmark.js
//
// Env vars:
//   K6_WS_URL          target channel URL (default: Quarkus :8090, see below)
//   PART5_BENCH_VUS    per-scenario VU count during the sustained-load
//                      stage (default: 5 — kept modest; see README's
//                      gated-vs-local note). NOT named K6_VUS: that name is
//                      a k6-reserved env var which, if set, silently
//                      discards this script's `options.scenarios` entirely
//                      in favor of a single default scenario (confirmed
//                      live — k6 logs `"env" level configuration overrode
//                      scenarios configuration entirely` and then fails
//                      with `function 'default' not found in exports`,
//                      since this script has no default-exported function).
//   PART5_BENCH_DURATION  per-scenario sustained-load duration (default:
//                         15s) — same reserved-name trap as K6_VUS above
//                         (K6_DURATION), avoided the same way.
//
// Grafana LGTM / OTLP output (DRQ-006): this script's own `handleSummary`
// always prints the console comparison below, regardless of `-o`. To ALSO
// push these metrics into the project's LGTM stack
// (`docker compose --profile observability up`, compose.yaml), add k6's
// built-in OpenTelemetry metrics output on the command line — no code
// change needed, k6 reads the exporter config from the environment:
//
//   K6_OTEL_GRPC_EXPORTER_INSECURE=true \
//   K6_OTEL_GRPC_EXPORTER_ENDPOINT=localhost:4317 \
//   k6 run -o opentelemetry examples/part5-performance/k6/benchmark.js
//
// (Pinned k6 2.3.0 ships OpenTelemetry metrics output built in — confirmed
// via `k6 run --help`'s Outputs section; this project has not separately
// verified a live LGTM round-trip for this script, so treat the above as
// documented-but-unverified rather than proven — the console summary below
// is the one path actually exercised end to end.)
//
// Pinned to k6 2.3.0 (contracts/README.md, Ch0 version matrix, DRQ-023/027).
import ws from "k6/ws";
import { check } from "k6";
import { Trend, Counter } from "k6/metrics";

const WS_URL =
  __ENV.K6_WS_URL ||
  "ws://localhost:8090/ws/v1/bookings/bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A/handling-events";
const VUS = Number(__ENV.PART5_BENCH_VUS || 5);
const DURATION = __ENV.PART5_BENCH_DURATION || "15s";
const RAMP = "3s";
const EXPECTED_FRAME_COUNT = 3;

const JSON_SUBPROTOCOL = "handling-events.v1+json";
const PROTOBUF_SUBPROTOCOL = "handling-events.v1+protobuf";

// Kept as distinct metric objects per encoding (rather than one metric
// sliced by a tag) so handleSummary can read each one straight out of
// `data.metrics` by name — k6's summary data doesn't expose a
// query-by-tag view of a Trend's sub-population, only whole-metric
// aggregates.
const jsonBytes = new Trend("json_bytes_per_frame", true);
const jsonConnects = new Counter("json_connects");
const jsonAttempts = new Counter("json_connect_attempts");
const jsonFrames = new Counter("json_frames_received");

const protobufBytes = new Trend("protobuf_bytes_per_frame", true);
const protobufConnects = new Counter("protobuf_connects");
const protobufAttempts = new Counter("protobuf_connect_attempts");
const protobufFrames = new Counter("protobuf_frames_received");

const deflateBytes = new Trend("deflate_bytes_per_frame", true);
const deflateConnects = new Counter("deflate_connects");
const deflateAttempts = new Counter("deflate_connect_attempts");
const deflateFrames = new Counter("deflate_frames_received");
const deflateNegotiated = new Counter("deflate_extension_negotiated");

function rampedScenario(exec) {
  return {
    executor: "ramping-vus",
    exec,
    startVUs: 0,
    stages: [
      { duration: RAMP, target: VUS },
      { duration: DURATION, target: VUS },
      { duration: RAMP, target: 0 },
    ],
    gracefulRampDown: "5s",
  };
}

export const options = {
  scenarios: {
    json: rampedScenario("jsonScenario"),
    protobuf: rampedScenario("protobufScenario"),
    json_deflate: rampedScenario("jsonDeflateScenario"),
  },
  // No `thresholds` block, deliberately: this is a LOCAL comparative
  // benchmark, not a CI gate (see header comment / DRQ-027) — each VU
  // reconnects as fast as it can with no think time, so at high VU counts
  // some connect attempts legitimately get refused/reset as the target
  // container's accept queue saturates. That's a real, interesting finding
  // (see the per-row success-rate in the printed summary), not a failure
  // this script should report via a nonzero exit code — unlike smoke.js,
  // where any failed check DOES fail the run.
};

// See smoke.js's echoedSubprotocol for why this is a case-insensitive scan
// rather than a direct key lookup (Go canonicalizes response header keys).
function echoedHeader(res, name) {
  if (!res || !res.headers) return "";
  const target = name.toLowerCase();
  for (const key of Object.keys(res.headers)) {
    if (key.toLowerCase() === target) return res.headers[key];
  }
  return "";
}

function runTextScenario(subprotocol, bytesTrend, connectsCounter, attemptsCounter, framesCounter, wsParams) {
  attemptsCounter.add(1);
  const frames = [];
  const res = ws.connect(WS_URL, wsParams, function (socket) {
    socket.on("message", function (data) {
      frames.push(data);
      if (frames.length >= EXPECTED_FRAME_COUNT) socket.close();
    });
    socket.on("error", function () {});
  });

  check(res, { [`${subprotocol}: upgrade accepted`]: (r) => r && r.status === 101 });

  if (res && res.status === 101) {
    connectsCounter.add(1);
    for (const frame of frames) {
      bytesTrend.add(frame.length);
      framesCounter.add(1);
    }
  }
  return res;
}

function runBinaryScenario(subprotocol, bytesTrend, connectsCounter, attemptsCounter, framesCounter, wsParams) {
  attemptsCounter.add(1);
  const frames = [];
  const res = ws.connect(WS_URL, wsParams, function (socket) {
    socket.on("binaryMessage", function (data) {
      frames.push(data);
      if (frames.length >= EXPECTED_FRAME_COUNT) socket.close();
    });
    socket.on("error", function () {});
  });

  check(res, { [`${subprotocol}: upgrade accepted`]: (r) => r && r.status === 101 });

  if (res && res.status === 101) {
    connectsCounter.add(1);
    for (const frame of frames) {
      bytesTrend.add(frame.byteLength);
      framesCounter.add(1);
    }
  }
  return res;
}

export function jsonScenario() {
  runTextScenario(JSON_SUBPROTOCOL, jsonBytes, jsonConnects, jsonAttempts, jsonFrames, {
    headers: { "Sec-WebSocket-Protocol": JSON_SUBPROTOCOL },
  });
}

export function protobufScenario() {
  runBinaryScenario(PROTOBUF_SUBPROTOCOL, protobufBytes, protobufConnects, protobufAttempts, protobufFrames, {
    headers: { "Sec-WebSocket-Protocol": PROTOBUF_SUBPROTOCOL },
  });
}

export function jsonDeflateScenario() {
  const res = runTextScenario(JSON_SUBPROTOCOL, deflateBytes, deflateConnects, deflateAttempts, deflateFrames, {
    headers: { "Sec-WebSocket-Protocol": JSON_SUBPROTOCOL },
    compression: "deflate",
  });
  const ext = echoedHeader(res, "Sec-Websocket-Extensions");
  if (ext.toLowerCase().includes("permessage-deflate")) {
    deflateNegotiated.add(1);
  }
}

export function handleSummary(data) {
  const m = data.metrics;
  const durationS = data.state.testRunDurationMs / 1000;

  function metricCount(name) {
    return m[name] && m[name].values && typeof m[name].values.count === "number" ? m[name].values.count : 0;
  }

  function row(label, bytesMetric, connectsMetric, attemptsMetric, framesMetric) {
    const trend = m[bytesMetric];
    const avgBytes = trend ? trend.values.avg : NaN;
    const p90Bytes = trend ? trend.values["p(90)"] : NaN;
    const frames = metricCount(framesMetric);
    const connects = metricCount(connectsMetric);
    const attempts = metricCount(attemptsMetric);
    const msgsPerSec = durationS > 0 ? frames / durationS : 0;
    const connectsPerSec = durationS > 0 ? connects / durationS : 0;
    const successPct = attempts > 0 ? (connects / attempts) * 100 : 0;
    return (
      `${label.padEnd(14)}` +
      ` avg=${(avgBytes || 0).toFixed(1).padStart(8)}B` +
      ` p90=${(p90Bytes || 0).toFixed(1).padStart(8)}B` +
      ` connects=${String(connects).padStart(6)}/${String(attempts).padStart(6)}` +
      ` (${successPct.toFixed(1)}% @ ${connectsPerSec.toFixed(1)}/s)` +
      ` frames=${String(frames).padStart(6)} (${msgsPerSec.toFixed(1)}/s)`
    );
  }

  const negotiated = metricCount("deflate_extension_negotiated");
  const deflateAttemptCount = metricCount("deflate_connect_attempts");

  const lines = [
    "",
    "=== Part 5 performance benchmark: JSON vs Protobuf vs JSON+permessage-deflate ===",
    `target:              ${WS_URL}`,
    `per-scenario VUs:    ${VUS} (sustained ${DURATION}, +${RAMP} ramp up/down)`,
    `test run duration:   ${durationS.toFixed(1)}s (all 3 scenarios ran concurrently)`,
    "",
    "encoding       bytes/frame (avg / p90)       connects/attempts (success% @ rate)   frames (=msgs)",
    row("json", "json_bytes_per_frame", "json_connects", "json_connect_attempts", "json_frames_received"),
    row(
      "protobuf",
      "protobuf_bytes_per_frame",
      "protobuf_connects",
      "protobuf_connect_attempts",
      "protobuf_frames_received",
    ),
    row(
      "json+deflate",
      "deflate_bytes_per_frame",
      "deflate_connects",
      "deflate_connect_attempts",
      "deflate_frames_received",
    ),
    "",
    `permessage-deflate negotiated: ${negotiated}/${deflateAttemptCount} connect attempts` +
      ` (server echoed Sec-WebSocket-Extensions: permessage-deflate)`,
    "NOTE: json+deflate's bytes/frame is the POST-INFLATION payload size",
    "k6/ws (gorilla/websocket) hands to this script, NOT the wire-compressed",
    "size — see this file's header comment. It is expected to read the same",
    "as the plain json row; it does not disprove deflate's wire savings, it",
    "just isn't what this script can observe.",
    "",
    "'messages/sec' above is connection-churn throughput (this channel",
    "replays 3 fixture events on connect, then stays idle — see header",
    "comment), not a sustained per-connection push rate.",
    "",
  ];

  const text = lines.join("\n") + "\n";
  return { stdout: text };
}
