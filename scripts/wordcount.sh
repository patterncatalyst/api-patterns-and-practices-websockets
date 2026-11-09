#!/usr/bin/env bash
# Word-count report for chapter prose: about 2,000 words is the target, 2,500 the most.
#
# Counts PROSE only: strips YAML front matter, fenced code blocks, HTML blocks
# (callouts, include lines), blockquoted command output, and Markdown table
# rows — so code listings, diagram captions and command output don't inflate
# the count, matching the plan's "excluding code/captions/output" rule.
#
# There is no floor: a chapter that is complete in fewer words stays that way.
# In GATE mode a draft/verified chapter OVER 2,500 words fails the build.
#
# Usage:
#   scripts/wordcount.sh                 # report every _docs chapter
#   scripts/wordcount.sh _docs/04-*.md   # report specific files
#   GATE=1 scripts/wordcount.sh          # exit non-zero if any DRAFT/VERIFIED
#                                        # chapter is OVER 2500 words
#
# In GATE mode, only chapters marked draft/verified in the coverage matrix are
# enforced; without a coverage matrix every chapter is.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
  [ -f "$COVERAGE" ] || return 0   # no coverage matrix: every chapter is enforced
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
  if [ "$wc_words" -gt "$MAX" ]; then band="over ${MAX}"; fi
  gated=""
  if [ "$GATE" = "1" ] && is_enforced "$f" && [ "$band" != "ok" ]; then
    gated="  <-- GATE FAIL (over ${MAX})"; fail=1
  fi
  printf '%-48s %7s   %s%s\n' "$rel" "$wc_words" "$band" "$gated"
done

if [ "$GATE" = "1" ] && [ "$fail" -ne 0 ]; then
  echo "Word-count gate failed: a draft/verified chapter is over ${MAX} words." >&2
  exit 1
fi
