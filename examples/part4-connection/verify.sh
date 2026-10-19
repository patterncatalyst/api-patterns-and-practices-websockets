#!/usr/bin/env bash
# examples/part4-connection/verify.sh
#
# Part 4 "Connection Concerns" example — proves, live against both running
# stacks, the four concerns this part adds on top of part3's plain fixture
# replay (contracts/asyncapi.yaml `operations.receiveHandlingEvent`):
#
#   Ch17 auth          — a valid JWT gets the fixture replay; a missing,
#                         garbage, expired, or bad-signature token gets
#                         rejected (close 1008), no data.
#   Ch13 error taxonomy — any client-sent frame gets an in-band
#                         {"error":{"code":"BAD_REQUEST",...}} envelope,
#                         then a 4400 close.
#   Ch12 backpressure   — an outbound overrun closes with 4290 (CLOSE
#                         policy).
#   Ch14 heartbeats     — a client that completes the upgrade and then never
#                         answers a ping is closed by the server's own
#                         pong-tracking liveness check, asserted within a
#                         short, env-configured detection window on one-off
#                         instances of both stacks (see Step 6). Quarkus's
#                         detector is HeartbeatLivenessSweep — a scheduled
#                         sweep over per-connection pong timestamps, NOT the
#                         auto-ping-interval/idle-timeout combination alone
#                         (that combination never detects a silent peer: the
#                         server's own outbound ping is write activity that
#                         keeps resetting Vert.x's idle clock regardless of
#                         whether the peer ever answers — see that class's
#                         Javadoc and the Quarkus app's README Ch14 section).
#
# Both stacks share ONE JWT secret (compose.yaml's WS_JWT_SECRET) and the
# SAME close-code numbers (see README.md), so every assertion below runs
# once per stack with identical expectations — a client should not be able
# to tell which stack it's talking to.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../_lib/lib.sh
source "$SCRIPT_DIR/../_lib/lib.sh"

# --profile <name> is optional (e.g. `./verify.sh --profile observability`)
# and brings up compose.yaml's opt-in `lgtm` service alongside the app
# stack — it does not change which assertions run.
PROFILE=""
if [[ "${1:-}" == "--profile" ]]; then
  PROFILE="${2:-}"
fi

PROJECT="part4-connection"
COMPOSE_FILE="$SCRIPT_DIR/compose.yaml"
SCHEMA_FILE="$SCRIPT_DIR/../../build/handling-event.schema.json"
EXTRACT_SCRIPT="$SCRIPT_DIR/../../scripts/extract-message-schema.py"

# Must match compose.yaml's WS_JWT_SECRET for BOTH services exactly — see
# the comment there. A single shared secret is what lets verify.sh mint
# ONE set of tokens (below) and use them against either stack.
SHARED_JWT_SECRET="part4-verify-harness-shared-secret-value"

BOOKING_ID="bkg_01HZY3KX7QZJ8N6VWT2E4R9F0A"
CHANNEL_PATH="/ws/v1/bookings/${BOOKING_ID}/handling-events"
EXPECTED_EVENT_TYPE="RECEIVE"

# One-off backpressure containers (see Step 5) run on these host ports so
# they don't collide with the already-up primary stack (8080/8081/8082).
BP_QUARKUS_PORT=18080
BP_PYTHON_PORT=18091
BP_QUARKUS_NAME="part4-connection-bp-quarkus"
BP_PYTHON_NAME="part4-connection-bp-python"

# Ch14 heartbeat one-off containers (Step 6) — same pattern as the Ch12
# backpressure one-offs above, on their own alternate host ports so they
# don't collide with either the primary stack or the backpressure one-offs.
HB_QUARKUS_PORT=18082
HB_PYTHON_PORT=18092
HB_QUARKUS_NAME="part4-connection-hb-quarkus"
HB_PYTHON_NAME="part4-connection-hb-python"

cleanup_all() {
  docker rm -f "$BP_QUARKUS_NAME" "$BP_PYTHON_NAME" "$HB_QUARKUS_NAME" "$HB_PYTHON_NAME" >/dev/null 2>&1 || true
  compose_down "$COMPOSE_FILE" "$PROJECT" "$PROFILE"
}

if ! command -v uv >/dev/null 2>&1; then
  echo "verify.sh: FAIL — 'uv' is required (mints JWTs and probes close codes via ephemeral venvs) but not found on PATH" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# mint_token <mode> <secret> [booking-id]
#
# Mints ONE HS256 JWT against <secret> with PyJWT (via `uv run --with
# pyjwt`, the same self-contained-ephemeral-install pattern lib.sh's
# schema_validate already uses for jsonschema — no project sync needed).
# Because both stacks verify a bare HS256 signature + exp claim with no
# other claim requirements (see quarkus's JwtHs256.verify and python's
# app/auth.py::validate_token), ONE token minted this way is accepted by
# EITHER stack as long as they share a secret — which compose.yaml ensures.
#
#   valid    — exp 5 minutes out.
#   expired  — exp 5 minutes in the past.
#   bad-sig  — signed with secret + "-wrong", so signature verification
#              fails against the real secret.
# ---------------------------------------------------------------------------
mint_token() {
  local mode="$1" secret="$2" booking_id="${3:-$BOOKING_ID}"
  uv run --with pyjwt python3 -I -c '
import sys, time, jwt

mode, secret, booking_id = sys.argv[1], sys.argv[2], sys.argv[3]
now = int(time.time())
claims = {"sub": "verify-harness", "bookingId": booking_id, "iat": now, "exp": now + 300}
use_secret = secret
if mode == "expired":
    claims["iat"] = now - 310
    claims["exp"] = now - 10
elif mode == "bad-sig":
    use_secret = secret + "-wrong"
elif mode != "valid":
    raise SystemExit(f"unknown mode: {mode!r}")
print(jwt.encode(claims, use_secret, algorithm="HS256"))
' "$mode" "$secret" "$booking_id" 2>/dev/null
}

# ---------------------------------------------------------------------------
# ws_close_probe <ws-url-with-query> [payload-to-send]
#
# Connects to <ws-url-with-query> with the `websockets` library (via `uv
# run --with websockets`, fetched into an ephemeral venv), optionally sends
# one text frame, then reads every frame until the server closes the
# connection. Prints ONE line of JSON: {"frames": N,
# "envelope_bad_request": bool, "close_code": N|null} — used both for the
# Ch13 error-taxonomy check (close code 4400 + the BAD_REQUEST envelope)
# and the Ch12 backpressure check (close code 4290, no payload sent).
# websocat can't observe close codes reliably, which is why this uses a
# small Python probe instead (mirrors how both app READMEs' own self-verify
# sections note the same websocat limitation).
# ---------------------------------------------------------------------------
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
        # async-for loop itself once the server closes — catch it here so
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

# ---------------------------------------------------------------------------
# raw_silent_client_close_wait <host> <port> <path-with-query> <timeout_secs>
#
# Ch14 best-effort heartbeat check. A spec-compliant WebSocket client
# (websocat included, and the `websockets` library used above) answers
# ping frames automatically at the protocol level, so neither can ever
# manufacture a genuinely dead peer (both app READMEs note this limitation
# explicitly). This instead speaks raw HTTP/TCP: it hand-writes the
# WebSocket opening handshake with Python's stdlib `socket` module (no
# WebSocket client library at all), confirms the 101 response, and then
# NEVER sends another byte — no pong, no close, nothing — for the rest of
# the probe. Any frame the server sends (fixture replay, pings, its own
# close frame) is read and discarded unparsed; the probe only measures how
# long the raw TCP connection survives total silence from this end,
# printing "CLOSED:<elapsed_s>" if the peer closed it within <timeout_secs>
# or "STILL_OPEN:<elapsed_s>" if it didn't.
# ---------------------------------------------------------------------------
raw_silent_client_close_wait() {
  local host="$1" port="$2" path="$3" timeout_s="$4"
  python3 -I -c '
import base64, os, socket, sys, time

host, port, path, timeout_s = sys.argv[1], int(sys.argv[2]), sys.argv[3], float(sys.argv[4])
key = base64.b64encode(os.urandom(16)).decode()
req = (
    f"GET {path} HTTP/1.1\r\n"
    f"Host: {host}:{port}\r\n"
    "Upgrade: websocket\r\n"
    "Connection: Upgrade\r\n"
    f"Sec-WebSocket-Key: {key}\r\n"
    "Sec-WebSocket-Version: 13\r\n"
    "\r\n"
).encode()

sock = socket.create_connection((host, port), timeout=10)
sock.sendall(req)

sock.settimeout(10)
resp = b""
while b"\r\n\r\n" not in resp:
    chunk = sock.recv(4096)
    if not chunk:
        print("NOUPGRADE:no-response")
        raise SystemExit(0)
    resp += chunk
status_line = resp.split(b"\r\n", 1)[0]
if b"101" not in status_line:
    print(f"NOUPGRADE:{status_line!r}")
    raise SystemExit(0)

# Upgrade succeeded. From here on this probe sends ABSOLUTELY NOTHING —
# no pong, no close frame — so any server-side close can only be the
# result of its own heartbeat/idle-timeout detection, never a client-
# initiated teardown. Tracks a single cumulative DEADLINE rather than
# reusing one settimeout() for the whole wait: a per-call socket timeout
# only bounds how long ONE recv() blocks, and this channel periodically
# delivers non-empty data of its own (ping frames) well inside that
# window, which would otherwise reset the clock on every ping and make
# the loop run forever instead of giving up at timeout_s.
start = time.monotonic()
deadline = start + timeout_s
closed = False
try:
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        sock.settimeout(remaining)
        chunk = sock.recv(4096)
        if not chunk:
            closed = True
            break
except socket.timeout:
    closed = False
except OSError:
    closed = True
elapsed = time.monotonic() - start
label = "CLOSED" if closed else "STILL_OPEN"
print(f"{label}:{elapsed:.1f}")
' "$host" "$port" "$path" "$timeout_s"
}

echo "=== Step 0: regenerate the contract-derived JSON Schema ==="
ensure_websocat
python3 -I "$EXTRACT_SCRIPT" "$SCHEMA_FILE"

echo
echo "=== Step 1: mint the shared-secret tokens (one set, used against BOTH stacks) ==="
VALID_TOKEN="$(mint_token valid "$SHARED_JWT_SECRET")"
EXPIRED_TOKEN="$(mint_token expired "$SHARED_JWT_SECRET")"
BADSIG_TOKEN="$(mint_token bad-sig "$SHARED_JWT_SECRET")"
GARBAGE_TOKEN="not-a-jwt-at-all"
for name in VALID_TOKEN EXPIRED_TOKEN BADSIG_TOKEN; do
  if [[ -z "${!name}" ]]; then
    echo "verify.sh: FAIL — $name is empty; token minting failed" >&2
    exit 1
  fi
done
echo "lib.sh: minted valid/expired/bad-sig tokens against the shared secret" >&2

echo
echo "=== Step 2: docker compose up${PROFILE:+ (--profile $PROFILE)} ==="
compose_up "$COMPOSE_FILE" "$PROJECT" "$PROFILE"
trap cleanup_all EXIT

# ---------------------------------------------------------------------------
# run_stack_auth_and_error_tests <stack> <host:port>
#
# Ch17 auth accept/reject + Ch13 error taxonomy, against ONE stack.
# ---------------------------------------------------------------------------
run_stack_auth_and_error_tests() {
  local stack="$1" target="$2"
  local base_url="ws://${target}${CHANNEL_PATH}"

  echo
  echo "=== verifying stack '$stack' at $target$CHANNEL_PATH ==="

  wait_for_ws "$target" "$CHANNEL_PATH"

  echo "--- Ch17 auth: valid token accepted, RECEIVE fixture frame streamed ---"
  local frame
  frame="$(ws_first_frame_auth "$base_url" "$VALID_TOKEN")"
  echo "lib.sh: $stack first frame (valid token): $frame" >&2
  schema_validate "$frame" "$SCHEMA_FILE"
  assert_eq "$EXPECTED_EVENT_TYPE" "$(json_field '.eventType' <<<"$frame")" "$stack valid-token first frame eventType"
  assert_eq "$BOOKING_ID" "$(json_field '.bookingId' <<<"$frame")" "$stack valid-token first frame bookingId"

  echo "--- Ch17 auth: rejections (no token, garbage, expired, bad-sig) — close 1008, no data ---"
  assert_ws_rejected "$base_url" 10 "$stack: no token"
  assert_ws_rejected "${base_url}?token=${GARBAGE_TOKEN}" 10 "$stack: garbage token"
  assert_ws_rejected "${base_url}?token=${EXPIRED_TOKEN}" 10 "$stack: expired token"
  assert_ws_rejected "${base_url}?token=${BADSIG_TOKEN}" 10 "$stack: bad-sig token"

  echo "--- Ch13 error taxonomy: malformed client frame -> envelope + close 4400 ---"
  local probe_result close_code envelope_ok
  probe_result="$(ws_close_probe "${base_url}?token=${VALID_TOKEN}" '{"not":"valid"}')"
  echo "lib.sh: $stack error-taxonomy probe result: $probe_result" >&2
  close_code="$(json_field '.close_code' <<<"$probe_result")"
  envelope_ok="$(json_field '.envelope_bad_request' <<<"$probe_result")"
  assert_eq "4400" "$close_code" "$stack error-taxonomy close code"
  assert_eq "true" "$envelope_ok" "$stack error-taxonomy BAD_REQUEST envelope received"

  echo "=== $stack: auth + error-taxonomy assertions passed ==="
}

echo
echo "=== Step 3: Quarkus — Ch17 auth + Ch13 error taxonomy ==="
run_stack_auth_and_error_tests "quarkus" "localhost:8080"

echo
echo "=== Step 4: Python — Ch17 auth + Ch13 error taxonomy ==="
run_stack_auth_and_error_tests "python" "localhost:8081"

# ---------------------------------------------------------------------------
# Step 5: Ch12 backpressure — one-off containers with the threshold forced
# low enough to trip deterministically on the very first fixture burst (see
# each app's README "Self-verify"/backpressure section). Quarkus's
# OutboundBackpressureGuard compares pending-sends > threshold, so 0 trips
# before anything is ever sent — verified live in that module's own
# Javadoc. Python's OutboundQueue sits on top of asyncio.Queue, where
# maxsize<=0 means UNBOUNDED (confirmed empirically) rather than
# zero-capacity — the opposite of what a "0 is deterministic" reading would
# suggest — so 1 is the value that actually trips deterministically here:
# all 3 fixture events are enqueued synchronously before the drain task
# ever runs, so the 2nd enqueue always overflows a maxsize=1 queue.
#
# Run as plain `docker run` (not `docker compose run --service-ports`)
# against the images compose already built, on alternate host ports, so
# the primary stack keeps running on 8080/8081/8082 throughout.
# ---------------------------------------------------------------------------
echo
echo "=== Step 5: Ch12 backpressure — one-off instances with the threshold forced low ==="

QUARKUS_IMAGE="$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" images -q quarkus)"
PYTHON_IMAGE="$(docker compose -p "$PROJECT" -f "$COMPOSE_FILE" images -q python)"
if [[ -z "$QUARKUS_IMAGE" || -z "$PYTHON_IMAGE" ]]; then
  echo "verify.sh: FAIL — could not resolve built image IDs for quarkus/python from compose" >&2
  exit 1
fi

docker rm -f "$BP_QUARKUS_NAME" "$BP_PYTHON_NAME" >/dev/null 2>&1 || true

echo "--- Quarkus: EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0 ---"
docker run -d --name "$BP_QUARKUS_NAME" \
  -p "${BP_QUARKUS_PORT}:8080" \
  -e "WS_JWT_SECRET=${SHARED_JWT_SECRET}" \
  -e EXAMPLE_BACKPRESSURE_MAX_PENDING_SENDS=0 \
  "$QUARKUS_IMAGE" >/dev/null
wait_for_ws "localhost:${BP_QUARKUS_PORT}" "$CHANNEL_PATH"
bp_result="$(ws_close_probe "ws://localhost:${BP_QUARKUS_PORT}${CHANNEL_PATH}?token=${VALID_TOKEN}")"
echo "lib.sh: quarkus backpressure probe result: $bp_result" >&2
assert_eq "4290" "$(json_field '.close_code' <<<"$bp_result")" "quarkus backpressure close code"
assert_eq "0" "$(json_field '.frames' <<<"$bp_result")" "quarkus backpressure: zero frames delivered before close"

echo "--- Python: OUTBOUND_QUEUE_MAXSIZE=1 ---"
docker run -d --name "$BP_PYTHON_NAME" \
  -p "${BP_PYTHON_PORT}:8081" \
  -e "WS_JWT_SECRET=${SHARED_JWT_SECRET}" \
  -e OUTBOUND_QUEUE_MAXSIZE=1 \
  "$PYTHON_IMAGE" >/dev/null
wait_for_ws "localhost:${BP_PYTHON_PORT}" "$CHANNEL_PATH"
bp_result="$(ws_close_probe "ws://localhost:${BP_PYTHON_PORT}${CHANNEL_PATH}?token=${VALID_TOKEN}")"
echo "lib.sh: python backpressure probe result: $bp_result" >&2
assert_eq "4290" "$(json_field '.close_code' <<<"$bp_result")" "python backpressure close code"

docker rm -f "$BP_QUARKUS_NAME" "$BP_PYTHON_NAME" >/dev/null 2>&1 || true

echo
echo "=== Step 5 complete: Ch12 backpressure CLOSE policy (4290) proven live on both stacks ==="

# ---------------------------------------------------------------------------
# Step 6: Ch14 heartbeats — one-off instances with a SHORT ping/liveness
# window, so the silent-peer close is asserted (not just observed
# best-effort) within a bounded wait. Quarkus's actual detector is
# HeartbeatLivenessSweep (see quarkus/.../HeartbeatLivenessSweep.java and
# that app's README Ch14 section) — auto-ping-interval alone + Vert.x's
# idle-timeout do NOT detect a silent peer (the server's own outbound ping
# is write activity that keeps resetting the idle clock regardless of
# whether the peer answers), which is why this step forces the DEDICATED
# EXAMPLE_HEARTBEAT_* knobs down, not just QUARKUS_HTTP_IDLE_TIMEOUT.
#
# Same one-off-container pattern as Step 5, on their own ports so they
# don't collide with the primary stack or the backpressure one-offs.
# ---------------------------------------------------------------------------
echo
echo "=== Step 6: Ch14 heartbeats — one-off instances with a SHORT detection window ==="

# Budget: EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT (5s) + EXAMPLE_HEARTBEAT_SWEEP_INTERVAL
# (1s, worst case) for HeartbeatLivenessSweep to DETECT the silent peer and
# request a close, PLUS Vert.x's own ~10s WebSocket closing-handshake grace
# (HttpServerOptions.DEFAULT_WEBSOCKET_CLOSING_TIMEOUT — not currently
# exposed as a Quarkus config property) before it gives up waiting for an
# acknowledgment that, by construction, a silent peer will never send and
# forcibly tears the TCP connection down — see HeartbeatLivenessSweep's
# Javadoc. ~16s observed live; 25s leaves comfortable margin for a slower
# CI host.
HEARTBEAT_TIMEOUT_S=25

docker rm -f "$HB_QUARKUS_NAME" "$HB_PYTHON_NAME" >/dev/null 2>&1 || true

echo "--- Quarkus: AUTO_PING_INTERVAL=2 EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT=5s EXAMPLE_HEARTBEAT_SWEEP_INTERVAL=1s ---"
docker run -d --name "$HB_QUARKUS_NAME" \
  -p "${HB_QUARKUS_PORT}:8080" \
  -e "WS_JWT_SECRET=${SHARED_JWT_SECRET}" \
  -e QUARKUS_WEBSOCKETS_NEXT_SERVER_AUTO_PING_INTERVAL=2 \
  -e EXAMPLE_HEARTBEAT_LIVENESS_TIMEOUT=5s \
  -e EXAMPLE_HEARTBEAT_SWEEP_INTERVAL=1s \
  "$QUARKUS_IMAGE" >/dev/null
wait_for_ws "localhost:${HB_QUARKUS_PORT}" "$CHANNEL_PATH"
quarkus_hb_result="$(raw_silent_client_close_wait localhost "${HB_QUARKUS_PORT}" "${CHANNEL_PATH}?token=${VALID_TOKEN}" "$HEARTBEAT_TIMEOUT_S")"
echo "lib.sh: quarkus heartbeat probe result: $quarkus_hb_result" >&2
assert_eq "CLOSED" "${quarkus_hb_result%%:*}" "quarkus heartbeat: silent peer closed within ${HEARTBEAT_TIMEOUT_S}s"

echo "--- Python: WS_PING_INTERVAL_S=2 WS_PING_TIMEOUT_S=3 ---"
docker run -d --name "$HB_PYTHON_NAME" \
  -p "${HB_PYTHON_PORT}:8081" \
  -e "WS_JWT_SECRET=${SHARED_JWT_SECRET}" \
  -e WS_PING_INTERVAL_S=2 \
  -e WS_PING_TIMEOUT_S=3 \
  "$PYTHON_IMAGE" >/dev/null
wait_for_ws "localhost:${HB_PYTHON_PORT}" "$CHANNEL_PATH"
python_hb_result="$(raw_silent_client_close_wait localhost "${HB_PYTHON_PORT}" "${CHANNEL_PATH}?token=${VALID_TOKEN}" "$HEARTBEAT_TIMEOUT_S")"
echo "lib.sh: python heartbeat probe result: $python_hb_result" >&2
assert_eq "CLOSED" "${python_hb_result%%:*}" "python heartbeat: silent peer closed within ${HEARTBEAT_TIMEOUT_S}s"

docker rm -f "$HB_QUARKUS_NAME" "$HB_PYTHON_NAME" >/dev/null 2>&1 || true

echo
echo "=== Step 6 complete: Ch14 heartbeat liveness detection of a genuinely silent peer PROVEN LIVE on BOTH stacks ==="

echo
echo "PASS — Part 4 connection-concerns: Quarkus and Python both implement" \
     "identical Ch17 auth (accept + 4 reject modes), Ch13 error taxonomy" \
     "(BAD_REQUEST envelope + 4400 close), Ch12 backpressure (4290 close)," \
     "and Ch14 heartbeat liveness detection of a silent peer (proven live" \
     "on both stacks within a short, env-configured window) against the" \
     "SAME shared JWT secret."

# Explicit teardown in addition to the cleanup_all EXIT trap
# (belt-and-suspenders); compose_down/docker rm are idempotent.
cleanup_all
