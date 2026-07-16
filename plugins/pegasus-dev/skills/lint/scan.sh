#!/usr/bin/env bash
#
# scan.sh — candidate gatherer for the /lint skill.
#
# Surfaces *candidates* for semantic-lint review; it does NOT judge. The agent
# reads this report, then confirms/dismisses each line (e.g. a `%` inside a regex
# is a false positive) and adds the LLM-only checks documented in SKILL.md.
#
# Usage:
#   scan.sh                # staged files (git diff --cached), the default
#   scan.sh PATH [PATH...]  # explicit files/dirs instead of the staged set
#
# Output: grouped, greppable sections — `path:lineno: snippet` per finding.

# no `set -u`: this is a candidate-scanner over possibly-empty file sets, and
# empty-array expansion under `set -u` is a footgun on macOS's bash 3.2.
set -o pipefail

# ---- resolve the target file set --------------------------------------------
declare -a FILES
if [[ $# -gt 0 ]]; then
    # explicit paths: expand directories to files, keep regular files as-is
    while IFS= read -r f; do FILES+=("$f"); done < <(
        for p in "$@"; do
            if [[ -d "$p" ]]; then find "$p" -type f; else echo "$p"; fi
        done
    )
else
    while IFS= read -r f; do
        [[ -n "$f" ]] && FILES+=("$f")
    done < <(git diff --cached --name-only --diff-filter=ACM 2>/dev/null)
fi

if [[ ${#FILES[@]} -eq 0 ]]; then
    echo "No files to lint."
    echo "  Stage changes first (git add ...), or pass paths: scan.sh <path>..."
    exit 0
fi

# keep only files that still exist on disk
declare -a EXISTING
for f in "${FILES[@]}"; do [[ -f "$f" ]] && EXISTING+=("$f"); done
FILES=("${EXISTING[@]}")
[[ ${#FILES[@]} -eq 0 ]] && { echo "No existing files to lint."; exit 0; }

# python subset (for idiom checks)
declare -a PY
for f in "${FILES[@]}"; do [[ "$f" == *.py ]] && PY+=("$f"); done

echo "=== /lint candidate scan — ${#FILES[@]} file(s), ${#PY[@]} python ==="
echo

# ---- 1. spelling (codespell, with graceful degrade) -------------------------
echo "## Spelling (codespell)"
CODESPELL=""
if command -v codespell >/dev/null 2>&1; then
    CODESPELL="codespell"
elif python3 -c "import codespell_lib" >/dev/null 2>&1; then
    CODESPELL="python3 -m codespell_lib"
elif command -v uvx >/dev/null 2>&1; then
    CODESPELL="uvx codespell"
fi
if [[ -n "$CODESPELL" ]]; then
    # -L: a few domain words that are not typos in this repo.
    # codespell exits non-zero WHEN it finds typos, so key off output, not status.
    SPELL_OUT="$($CODESPELL -L "pegasus,isi,nd,te,ist,fo,wqs,daa" "${FILES[@]}" 2>/dev/null)"
    if [[ -n "$SPELL_OUT" ]]; then echo "$SPELL_OUT"; else echo "  (no spelling candidates)"; fi
else
    echo "  codespell unavailable — spelling falls back to LLM review of the diff."
fi
echo

# ---- python idiom checks (skip if no python files) --------------------------
if [[ ${#PY[@]} -gt 0 ]]; then

    # 2. .format() / %-formatting -> f-strings.
    # Exclude logging calls: `log.info("%s", x)` is the correct lazy-logging
    # idiom, not an f-string candidate (and ruff's LOG rules cover it).
    echo "## String formatting -> prefer f-strings  (.format() / %)"
    FMT_OUT="$(grep -HnE '\.format\(|%[-#0-9.]*[sdrfx]' "${PY[@]}" 2>/dev/null \
        | grep -vE 'log(ger|ging)?\.|getLogger')"
    if [[ -n "$FMT_OUT" ]]; then echo "$FMT_OUT"; else echo "  (no candidates)"; fi
    echo

    # 3. print() in library code (cli/ is the sanctioned exception)
    echo "## print() in library code -> prefer logging  (cli/ excluded)"
    declare -a LIBPY
    for f in "${PY[@]}"; do [[ "$f" != *"/cli/"* ]] && LIBPY+=("$f"); done
    if [[ ${#LIBPY[@]} -gt 0 ]]; then
        grep -HnE '(^|[^_a-zA-Z.])print\(' "${LIBPY[@]}" 2>/dev/null \
            || echo "  (no candidates)"
    else
        echo "  (no library python files in target set)"
    fi
    echo
fi

echo "=== end of candidate scan ==="
echo "Next: read 'git diff --cached', triage these candidates, then run the"
echo "      LLM-only semantic checks (comment drift, doc staleness, ...) per SKILL.md."
