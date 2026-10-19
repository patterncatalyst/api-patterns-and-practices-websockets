#!/usr/bin/env bash
# examples/_lib/lib.sh
#
# Shared verification harness for every hands-on example's verify.sh.
# Source this file, then use the functions below to bring up the example's
# docker compose stack, wait for the WebSocket endpoint to accept the
# upgrade, read frames via websocat, and assert MESSAGE SHAPE against the
# chapter's contract (JSON Schema or field-by-field) — not just "the socket
# opened". A successful upgrade that then emits a wrong-shaped or
# wrong-valued frame must fail the check.
#
# Usage (from an example's verify.sh):
#
#   #!/usr/bin/env bash
#   set -euo pipefail
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   # shellcheck source=../_lib/lib.sh
#   source "$SCRIPT_DIR/../_lib/lib.sh"
#
#   PROJECT="ws-ch05-quarkus"               # unique per example+stack, for CI isolation
#   compose_up "$SCRIPT_DIR/quarkus/compose.yaml" "$PROJECT"
#
#   wait_for_ws localhost:8080 /ticker
#   frame="$(ws_first_frame ws://localhost:8080/ticker)"
#   assert_eq "AAPL" "$(json_field '.symbol' <<<"$frame")" "ticker symbol"
#   schema_validate "$frame" "$SCRIPT_DIR/schema/ticker-update.schema.json"
#
# compose_down runs automatically on EXIT via a trap registered by compose_up.
#
# This file must stay `bash -n` clean: scripts/validate.py runs `bash -n` on
# every *.sh in the repo.

set -euo pipefail

# ---------------------------------------------------------------------------
# Path resolution — works regardless of the calling example's cwd.
# ---------------------------------------------------------------------------

LGTM_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LGTM_LIB_DIR/../.." && pwd)"
export REPO_ROOT

# ---------------------------------------------------------------------------
# Self-contained websocat: download a pinned binary into a cached .bin dir so
# verify.sh needs no pre-installed tool / CI YAML change (mirrors the gRPC
# harness's self-downloading grpcurl, and the REST harness's self-contained
# venv philosophy).
#
# Pin: websocat v1.14.1 (latest stable tag on github.com/vi/websocat at the
# time this harness was written — 2026-10-18). Release assets are raw
# binaries (no tar.gz), named by Rust target triple, e.g.
# `websocat.x86_64-unknown-linux-musl`. Override WEBSOCAT_VERSION to pin a
# different release.
# ---------------------------------------------------------------------------

LGTM_BIN_DIR="${LGTM_BIN_DIR:-$LGTM_LIB_DIR/.bin}"
WEBSOCAT_VERSION="${WEBSOCAT_VERSION:-1.14.1}"

ensure_websocat() {
  if command -v websocat >/dev/null 2>&1; then
    return 0
  fi
  local bin="$LGTM_BIN_DIR/websocat"
  if [[ -x "$bin" ]]; then
    export PATH="$LGTM_BIN_DIR:$PATH"
    return 0
  fi
  local os arch target
  os="$(uname -s)"
  arch="$(uname -m)"
  case "$arch" in
    x86_64|amd64) arch="x86_64" ;;
    aarch64|arm64) arch="aarch64" ;;
  esac
  case "$os" in
    Linux) target="${arch}-unknown-linux-musl" ;;
    Darwin) target="${arch}-apple-darwin" ;;
    *)
      echo "lib.sh: FAIL — unsupported OS '$os' for websocat auto-download; install websocat manually" >&2
      return 1
      ;;
  esac
  local url="https://github.com/vi/websocat/releases/download/v${WEBSOCAT_VERSION}/websocat.${target}"
  echo "lib.sh: downloading websocat ${WEBSOCAT_VERSION} (${os}/${arch}) ..." >&2
  mkdir -p "$LGTM_BIN_DIR"
  if ! curl -fsSL "$url" -o "$bin"; then
    echo "lib.sh: FAIL — could not download websocat from $url" >&2
    return 1
  fi
  chmod +x "$bin"
  if ! "$bin" --version >/dev/null 2>&1; then
    echo "lib.sh: FAIL — downloaded websocat binary at $bin did not run" >&2
    return 1
  fi
  export PATH="$LGTM_BIN_DIR:$PATH"
}

# ---------------------------------------------------------------------------
# Docker compose lifecycle
# ---------------------------------------------------------------------------

_LIB_COMPOSE_FILE=""
_LIB_COMPOSE_PROJECT=""
_LIB_COMPOSE_PROFILE=""

# compose_up <compose-file> <project-name> [profile]
#
# [profile] is optional: pass an opt-in compose profile name (e.g.
# "observability") to bring its services up alongside the default ones —
# mirrors `docker compose --profile <name> up`. Omit it (or pass "") for the
# default, profile-less stack.
compose_up() {
  local compose_file="$1"
  local project="$2"
  local profile="${3:-}"

  if [[ ! -f "$compose_file" ]]; then
    echo "lib.sh: compose file not found: $compose_file" >&2
    return 1
  fi
  if ! command -v docker >/dev/null 2>&1; then
    echo "lib.sh: docker is required but not found on PATH" >&2
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "lib.sh: 'docker compose' (v2 plugin) is required; legacy docker-compose is not supported" >&2
    return 1
  fi

  _LIB_COMPOSE_FILE="$compose_file"
  _LIB_COMPOSE_PROJECT="$project"
  _LIB_COMPOSE_PROFILE="$profile"

  local -a profile_args=()
  if [[ -n "$profile" ]]; then
    profile_args=(--profile "$profile")
  fi

  echo "lib.sh: docker compose -p $project ${profile_args[*]} up -d --build" >&2
  docker compose -p "$project" -f "$compose_file" "${profile_args[@]}" up -d --build

  trap 'compose_down "$_LIB_COMPOSE_FILE" "$_LIB_COMPOSE_PROJECT" "$_LIB_COMPOSE_PROFILE"' EXIT
}

# compose_down <compose-file> <project-name> [profile]
#
# [profile] should match whatever was passed to compose_up, so the
# profile's services (e.g. "observability"'s lgtm) are included in the
# teardown, not just the default-profile ones.
compose_down() {
  local compose_file="$1"
  local project="$2"
  local profile="${3:-}"

  if [[ -z "$project" ]]; then
    return 0
  fi

  local -a profile_args=()
  if [[ -n "$profile" ]]; then
    profile_args=(--profile "$profile")
  fi

  echo "lib.sh: docker compose -p $project ${profile_args[*]} down -v --remove-orphans" >&2
  docker compose -p "$project" -f "$compose_file" "${profile_args[@]}" down -v --remove-orphans || true
}

# ---------------------------------------------------------------------------
# WebSocket helpers (ws:// by default; set WEBSOCAT_OPTS for wss/-k/etc. in
# the TLS chapters, e.g. WEBSOCAT_OPTS="-k" to accept self-signed certs)
# ---------------------------------------------------------------------------

WEBSOCAT_OPTS="${WEBSOCAT_OPTS:-}"

# wait_for_ws <host:port> <path> [timeout_secs]
#
# Polls <host:port><path> until it accepts a WebSocket upgrade, or fails
# loudly after timeout_secs (default 90, to cover JVM/native cold start).
# Each probe opens a connection with stdin already closed (/dev/null) and
# -E (exit-on-eof) so websocat tears the socket back down immediately once
# the upgrade succeeds, rather than idling until the outer timeout fires.
wait_for_ws() {
  local target="$1"
  local path="$2"
  local timeout="${3:-90}"
  local waited=0
  local interval=3
  local url="ws://${target}${path}"

  ensure_websocat
  echo "lib.sh: waiting for WebSocket $url (timeout ${timeout}s) ..." >&2
  while (( waited < timeout )); do
    if timeout 5 websocat $WEBSOCAT_OPTS -E -t - "$url" </dev/null >/dev/null 2>&1; then
      echo "lib.sh: WebSocket $url is up after ${waited}s" >&2
      return 0
    fi
    sleep "$interval"
    waited=$(( waited + interval ))
  done

  echo "lib.sh: FAIL — WebSocket $url did not accept an upgrade within ${timeout}s" >&2
  return 1
}

# ws_first_frame <ws-url> [timeout_secs]
#
# Connects to <ws-url>, reads exactly one text frame, prints it to stdout
# (expected to be JSON), and closes. Does not send anything itself (stdin is
# /dev/null), so it is for servers that push a frame on connect (a ticker,
# a welcome message, a snapshot). Bounded by an outer `timeout` so a server
# that never sends a frame fails loudly instead of hanging the test run.
ws_first_frame() {
  local url="$1"
  local timeout="${2:-15}"
  ensure_websocat

  local out rc=0
  out="$(timeout "$timeout" websocat $WEBSOCAT_OPTS -1 -n -t "$url" </dev/null)" || rc=$?
  if (( rc != 0 )); then
    echo "lib.sh: FAIL — ws_first_frame $url: no frame received within ${timeout}s (exit $rc)" >&2
    return 1
  fi
  printf '%s\n' "$out"
}

# ---------------------------------------------------------------------------
# Assertions (stdlib-python JSON field extraction; no extra deps)
# ---------------------------------------------------------------------------

# json_field <dot.path> — read JSON on stdin, print the value at the given
# dotted path. Supports numeric indices: `.legs.0.carrier`. Prints nothing
# (and returns non-zero) if the path is absent.
json_field() {
  local path="$1"
  python3 -I -c '
import json, sys
path = sys.argv[1].strip(".")
doc = json.load(sys.stdin)
cur = doc
for part in [p for p in path.split(".") if p != ""]:
    if isinstance(cur, list):
        cur = cur[int(part)]
    else:
        cur = cur[part]
if isinstance(cur, (dict, list)):
    print(json.dumps(cur, separators=(",", ":")))
elif isinstance(cur, bool):
    print("true" if cur else "false")
else:
    print(cur)
' "$path"
}

# assert_eq <expected> <actual> <context>
assert_eq() {
  local expected="$1"
  local actual="$2"
  local context="${3:-equality}"
  if [[ "$expected" != "$actual" ]]; then
    echo "lib.sh: FAIL — ${context}: expected '$expected', got '$actual'" >&2
    return 1
  fi
  echo "lib.sh: ok — ${context}: '$actual'" >&2
}

# assert_contains <needle> <haystack> <context>
assert_contains() {
  local needle="$1"
  local haystack="$2"
  local context="${3:-contains}"
  if [[ "$haystack" != *"$needle"* ]]; then
    echo "lib.sh: FAIL — ${context}: '$needle' not found" >&2
    return 1
  fi
  echo "lib.sh: ok — ${context}: found '$needle'" >&2
}

# ---------------------------------------------------------------------------
# JSON Schema validation (Draft 2020-12)
# ---------------------------------------------------------------------------

# schema_validate <json-string-or-file> <schema-file>
#
# Validates a JSON document (a literal JSON string, or a path to a file
# containing one) against a JSON Schema file (Draft 2020-12). Prefers the
# real `jsonschema` library for full spec coverage, in this order:
#   1. `python3 -I -c 'import jsonschema'` — already installed on PATH's
#      interpreter (e.g. a CI image that carries it).
#   2. `uv run --with jsonschema` — self-contained ephemeral install via uv
#      (cached after first use), same "no pre-install needed" philosophy as
#      ensure_websocat/ensure_grpcurl. Used only if `uv` is on PATH.
#   3. A minimal hand-rolled fallback (see _schema_validate_fallback below)
#      if neither is available. It checks `type`, `required`, `properties`
#      (recursively), `items`, `enum`, `minimum`/`maximum`,
#      `minLength`/`maxLength`, `pattern`, and `additionalProperties: false`
#      — enough for the flat/shallow message schemas used in these examples.
#      It is NOT a full Draft 2020-12 implementation (no $ref, oneOf/anyOf/
#      allOf, conditional keywords); install `jsonschema` for full coverage.
# Exits non-zero with a readable error on validation failure.
schema_validate() {
  local doc_arg="$1"
  local schema_file="$2"
  local doc_json

  if [[ -f "$doc_arg" ]]; then
    doc_json="$(cat "$doc_arg")"
  else
    doc_json="$doc_arg"
  fi

  if [[ ! -f "$schema_file" ]]; then
    echo "lib.sh: FAIL — schema file not found: $schema_file" >&2
    return 1
  fi

  local validator_src='
import json, sys
from jsonschema import Draft202012Validator

doc = json.loads(sys.argv[1])
with open(sys.argv[2]) as f:
    schema = json.load(f)

validator = Draft202012Validator(schema)
errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
if errors:
    for e in errors:
        path = "$" + "".join(f"[{p!r}]" for p in e.path)
        print(f"lib.sh: FAIL — schema_validate: {path}: {e.message}", file=sys.stderr)
    sys.exit(1)
'

  if python3 -I -c 'import jsonschema' >/dev/null 2>&1; then
    python3 -I -c "$validator_src" "$doc_json" "$schema_file" \
      && { echo "lib.sh: ok — schema_validate: $schema_file" >&2; return 0; } \
      || return 1
  fi

  if command -v uv >/dev/null 2>&1; then
    uv run --with jsonschema python3 -I -c "$validator_src" "$doc_json" "$schema_file" \
      && { echo "lib.sh: ok — schema_validate: $schema_file" >&2; return 0; } \
      || return 1
  fi

  echo "lib.sh: jsonschema not available (no python3 module, no uv on PATH) — using minimal fallback validator" >&2
  _schema_validate_fallback "$doc_json" "$schema_file"
}

# _schema_validate_fallback <json-string> <schema-file>
# Minimal structural validator used only when neither a real `jsonschema`
# install nor `uv` (for an ephemeral one) is available. See schema_validate
# doc comment above for exactly which keywords it supports.
_schema_validate_fallback() {
  local doc_json="$1"
  local schema_file="$2"
  python3 -I -c '
import json, re, sys

doc = json.loads(sys.argv[1])
with open(sys.argv[2]) as f:
    schema = json.load(f)

errors = []

def type_ok(value, t):
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(t, True)

def check(value, sch, path):
    if not isinstance(sch, dict):
        return
    if "type" in sch:
        want_type = sch["type"]
        types = want_type if isinstance(want_type, list) else [want_type]
        if not any(type_ok(value, t) for t in types):
            errors.append(f"{path}: expected type {want_type!r}, got {type(value).__name__}")
            return
    if "enum" in sch and value not in sch["enum"]:
        allowed = sch["enum"]
        errors.append(f"{path}: {value!r} not in enum {allowed!r}")
    if isinstance(value, str):
        min_len = sch.get("minLength")
        if min_len is not None and len(value) < min_len:
            errors.append(f"{path}: string shorter than minLength {min_len}")
        max_len = sch.get("maxLength")
        if max_len is not None and len(value) > max_len:
            errors.append(f"{path}: string longer than maxLength {max_len}")
        pattern = sch.get("pattern")
        if pattern is not None and not re.search(pattern, value):
            errors.append(f"{path}: {value!r} does not match pattern {pattern!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = sch.get("minimum")
        if minimum is not None and value < minimum:
            errors.append(f"{path}: {value} < minimum {minimum}")
        maximum = sch.get("maximum")
        if maximum is not None and value > maximum:
            errors.append(f"{path}: {value} > maximum {maximum}")
    if isinstance(value, dict):
        for req in sch.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required property {req!r}")
        props = sch.get("properties", {})
        for k, v in value.items():
            if k in props:
                check(v, props[k], f"{path}.{k}")
            elif sch.get("additionalProperties") is False:
                errors.append(f"{path}: additional property {k!r} not allowed")
    if isinstance(value, list) and "items" in sch:
        for i, item in enumerate(value):
            check(item, sch["items"], f"{path}[{i}]")

check(doc, schema, "$")
if errors:
    for e in errors:
        print(f"lib.sh: FAIL — schema_validate (fallback): {e}", file=sys.stderr)
    sys.exit(1)
' "$doc_json" "$schema_file"
}
