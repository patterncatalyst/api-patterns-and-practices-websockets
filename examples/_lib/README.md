# examples/_lib — shared verification harness

Every hands-on example's `verify.sh` sources `lib.sh`. The harness brings up the
example's Docker Compose stack, waits for the WebSocket endpoint to accept the
upgrade, reads frames via **websocat**, and asserts **message shape against the
chapter's contract** (JSON Schema or field-by-field) — not just "the socket
opened". A successful upgrade that then emits a wrong-shaped or wrong-valued
frame must fail the check (this is the "On the wire" box of each chapter,
encoded).

## Functions

| Function | Purpose |
|---|---|
| `compose_up <file> <project>` | `docker compose up -d --build`; registers an EXIT trap that tears the stack down automatically. |
| `compose_down <file> <project>` | `docker compose down -v --remove-orphans` (called by the trap). |
| `wait_for_ws <host:port> <path> [timeout]` | Poll until the endpoint accepts a WebSocket upgrade (default timeout 90s, covers JVM/native cold start). |
| `wait_for_tcp <host> <port> [timeout]` | Poll until a raw TCP connection succeeds (default timeout 90s) — for broker dependencies (Kafka, Redis) that don't speak HTTP/WebSocket. Prefers bash's `/dev/tcp`; falls back to `nc -z` if available. |
| `ws_first_frame <ws-url> [timeout]` | Connect, read exactly one text frame (no input sent), print it to stdout, close. Bounded by `timeout` (default 15s) so a silent server fails loudly instead of hanging. |
| `ws_first_frame_auth <ws-url> <token> [timeout]` | Like `ws_first_frame`, but appends `?token=<token>` (or `&token=<token>` if the URL already has a query string) — for Ch17 auth checks. |
| `ws_frames_n <ws-url> <n> [timeout]` | Connect, read exactly `n` frames (prints one per line, in order), close. Bounded by `timeout` (default 20s). Internally uses websocat's `--max-messages-rev` — `--max-messages` alone caps the client-to-server direction, not server-to-client. |
| `ws_connect_bg <ws-url> <logfile>` | Open a long-lived **background** connection, appending every received frame to `<logfile>`; prints its PID to stdout. Caller must `kill`/`wait` the PID when done. For fan-out/broadcast proofs (Ch18): stay connected to instance A in the background while an event is injected through instance B, then assert the frame landed in `<logfile>`. |
| `assert_ws_rejected <ws-url> [timeout] [context]` | Assert a connection is **rejected** — either a non-101 handshake failure, or a 101 upgrade immediately followed by a close with zero application frames sent (e.g. an `@OnOpen` handler that closes the session). Checks received data, not exit code, since a server-side close after a successful upgrade still makes websocat exit 0. For Ch17 missing/invalid-token checks. |
| `ws_idle_hold <ws-url> <seconds>` | Hold a connection open for `<seconds>` without sending any application data (websocat answers WS pings with pongs automatically), to observe heartbeat/idle-timeout behavior (Ch14). Prints `held` (connection survived) or `closed` (server closed it first) to stdout — a report, not a pass/fail judgment; the caller decides which outcome its chapter expects. |
| `schema_validate <json-string-or-file> <schema-file>` | Validate a JSON document against a JSON Schema (Draft 2020-12). Exits non-zero with a readable error on failure. |
| `json_field <dot.path>` | Extract a value from JSON on stdin (supports numeric indices: `.legs.0.carrier`). |
| `assert_eq <expected> <actual> <ctx>` / `assert_contains <needle> <hay> <ctx>` | Value assertions. |
| `wait_for_log_pattern <file> <pattern> [timeout]` | Poll a file for a line containing a fixed-string `<pattern>` (default timeout 30s); fails loudly with a tail of the file on timeout. Promoted from `part3-handling-events/verify.sh` so new examples can reuse it without redefining it locally. |
| `wait_for_log_count <file> <pattern> <min-count> [timeout]` | Poll a file until at least `<min-count>` lines match `<pattern>` (default timeout 30s) — distinguishes "happened once" from "happened again," e.g. proving a client resumed receiving after a reconnect. Also promoted from `part3-handling-events/verify.sh`. |

`websocat` is downloaded into a cached `.bin/` on first use (pinned via
`WEBSOCAT_VERSION`, currently **v1.14.1**), so `verify.sh` is self-contained and
needs no CI pre-install — the same philosophy as the gRPC harness's self-downloading
`grpcurl`. Override `WEBSOCAT_OPTS` (default empty) to pass `-k`/TLS flags in the
`wss://` chapters.

### `schema_validate` dependency chain

In order of preference:

1. `python3 -I -c 'import jsonschema'` — used directly if the interpreter on
   `PATH` already has it installed (e.g. a CI image that carries it).
2. `uv run --with jsonschema ...` — a self-contained **ephemeral** install via
   `uv`, cached after first use. Used automatically when `uv` is on `PATH` but
   `jsonschema` isn't importable directly. Gives full Draft 2020-12 coverage
   without requiring anyone to `pip install` anything.
3. A minimal hand-rolled fallback, used only if neither of the above is
   available. It checks `type`, `required`, `properties` (recursively),
   `items`, `enum`, `minimum`/`maximum`, `minLength`/`maxLength`, `pattern`,
   and `additionalProperties: false` — enough for the flat/shallow message
   schemas used in these examples. It is **not** a full Draft 2020-12
   implementation (no `$ref`, `oneOf`/`anyOf`/`allOf`, conditionals); install
   `jsonschema` (or have `uv` on `PATH`) for full coverage.

## Minimal example

```bash
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../_lib/lib.sh"

PROJECT="ws-ch05-quarkus"
compose_up "$SCRIPT_DIR/quarkus/compose.yaml" "$PROJECT"
wait_for_ws localhost:8080 /ticker

frame="$(ws_first_frame ws://localhost:8080/ticker)"
assert_eq "AAPL" "$(json_field '.symbol' <<<"$frame")" "ticker symbol"
schema_validate "$frame" "$SCRIPT_DIR/schema/ticker-update.schema.json"
```
