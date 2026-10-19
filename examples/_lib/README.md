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
| `ws_first_frame <ws-url> [timeout]` | Connect, read exactly one text frame (no input sent), print it to stdout, close. Bounded by `timeout` (default 15s) so a silent server fails loudly instead of hanging. |
| `schema_validate <json-string-or-file> <schema-file>` | Validate a JSON document against a JSON Schema (Draft 2020-12). Exits non-zero with a readable error on failure. |
| `json_field <dot.path>` | Extract a value from JSON on stdin (supports numeric indices: `.legs.0.carrier`). |
| `assert_eq <expected> <actual> <ctx>` / `assert_contains <needle> <hay> <ctx>` | Value assertions. |

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
