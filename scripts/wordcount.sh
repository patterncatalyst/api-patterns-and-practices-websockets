#!/usr/bin/env bash
# Word-count gate for chapter prose (depth standard: 2,000–2,500 words target).
#
# Counts PROSE only: strips YAML front matter, fenced code blocks, HTML blocks
# (callouts, include lines), blockquoted command output, and Markdown table
# rows — so code listings, diagram captions and command output don't inflate
# the count, matching the plan's "excluding code/captions/output" rule.
#
# 2,000–2,500 is a TARGET band, not a hard cap. In GATE mode only the lower
# bound is enforced: a draft/verified chapter UNDER 2,000 words fails the build
# (too thin), while one OVER 2,500 is flagged as a non-failing warning so long
# chapters stay visible without blocking. A chapter that runs long should earn
# it with more than one figure (see the coverage matrix / iteration plan).
#
# Usage:
#   scripts/wordcount.sh                 # report every _docs chapter
#   scripts/wordcount.sh _docs/04-*.md   # report specific files
#   GATE=1 scripts/wordcount.sh          # exit non-zero if any DRAFT/VERIFIED
#                                        # chapter is UNDER 2000 words
#
# In GATE mode, only chapters marked draft/verified in the coverage matrix are
# enforced, so planned (unwritten) chapters don't fail the build.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIN=2000
MAX=2500
GATE="${GATE:-0}"
COVERAGE="${REPO_ROOT}/_plans/coverage-matrix.md"

# Files to enforce in GATE mode: coverage rows whose status is draft/verified.
claimed_files() {
  [ -f "$COVERAGE" ] || return 0
  awk '
    /^## / { inv = ($0 ~ /^## Full chapter inventory/) ? 1 : 0; next }
    inv && /^\|/ {
      n = split($0, c, "|")
      file = c[3]; status = c[5]
      gsub(/[` ]/, "", file); gsub(/ /, "", status)
      if (file ~ /^_docs\// && (status == "draft" || status == "verified"))
        print file
    }
  ' "$COVERAGE"
}

# Count prose words in a single markdown file.
prose_wordcount() {
  awk '
    BEGIN { fm = 0; fence = 0; words = 0 }
    NR == 1 && $0 == "---" { fm = 1; next }
    fm == 1 && $0 == "---" { fm = 0; next }
    fm == 1 { next }
    /^[[:space:]]*(```|~~~)/ { fence = !fence; next }
    fence == 1 { next }
    /^[[:space:]]*</ { next }          # HTML block lines (callouts)
    /^[[:space:]]*{%/ { next }         # Liquid include lines (figure alt-text/caption, codetabs) — not prose
    /^[[:space:]]*\|/ { next }         # markdown table rows
    /^[[:space:]]*>/ { next }          # blockquoted output
    { n = split($0, a, /[[:space:]]+/); for (i = 1; i <= n; i++) if (a[i] != "") words++ }
    END { print words }
  ' "$1"
}

if [ "$#" -gt 0 ]; then
  targets=("$@")
else
  mapfile -t targets < <(find "${REPO_ROOT}/_docs" -name '*.md' 2>/dev/null | sort)
fi

mapfile -t enforced < <(claimed_files)
is_enforced() {
  local rel="${1#"${REPO_ROOT}/"}"
  for e in "${enforced[@]:-}"; do [ "$e" = "$rel" ] && return 0; done
  return 1
}

fail=0
printf '%-48s %7s   %s\n' "chapter" "words" "status"
printf '%-48s %7s   %s\n' "-------" "-----" "------"
for f in "${targets[@]}"; do
  [ -f "$f" ] || continue
  wc_words="$(prose_wordcount "$f")"
  rel="${f#"${REPO_ROOT}/"}"
  band="ok"
  if [ "$wc_words" -lt "$MIN" ]; then band="under ${MIN}"; elif [ "$wc_words" -gt "$MAX" ]; then band="over ${MAX}"; fi
  gated=""
  if [ "$GATE" = "1" ] && is_enforced "$f" && [ "$band" != "ok" ]; then
    if [ "$wc_words" -lt "$MIN" ]; then
      gated="  <-- GATE FAIL (under ${MIN})"; fail=1
    else
      gated="  <-- over target (warning, ok)"
    fi
  fi
  printf '%-48s %7s   %s%s\n' "$rel" "$wc_words" "$band" "$gated"
done

if [ "$GATE" = "1" ] && [ "$fail" -ne 0 ]; then
  echo "Word-count gate failed: a draft/verified chapter is under ${MIN} words." >&2
  exit 1
fi
