#!/usr/bin/env bash
# run-all.sh -- runs every test file in tests/, then (optionally) a leaked-identifier gate.
#
# Exit code is nonzero if ANY test fails, or if the leak gate runs and finds anything.
#
# The unit tests need no config file, no network and no environment variables.
#
# The leak gate is opt-in. It scans the repo for your own private identifiers, and its
# deny-list comes ONLY from $LEAK_DENYLIST (a path to a file outside the repo, one term per
# line). With LEAK_DENYLIST unset it prints "SKIP leak gate (set LEAK_DENYLIST to enable)".
# With LEAK_DENYLIST set to a path that does not exist, it FAILS: you asked for the gate.

set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"

OVERALL_STATUS=0
TESTS_RUN=0

echo "=== Running test files in $HERE ==="
echo

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    echo "FAIL: $PY not found on PATH" >&2
    exit 1
fi

shopt -s nullglob
TEST_FILES=("$HERE"/test_*.py)
shopt -u nullglob

if [ ${#TEST_FILES[@]} -eq 0 ]; then
    echo "FAIL: no test_*.py files found in $HERE" >&2
    OVERALL_STATUS=1
else
    for f in "${TEST_FILES[@]}"; do
        name="$(basename "$f")"
        echo "--- $name ---"
        if (cd "$REPO_ROOT" && env -u JOBSTACK_CONFIG -u JOBSTACK_DATA_ROOT PYTHONDONTWRITEBYTECODE=1 \
                "$PY" "$f" 2>&1 | tee "${TMPDIR:-/tmp}/ajs_test_out.$$"; \
                exit "${PIPESTATUS[0]}"); then
            echo "PASS: $name"
        else
            echo "FAIL: $name"
            OVERALL_STATUS=1
        fi
        n=$(sed -n 's/^Ran \([0-9][0-9]*\) tests\{0,1\} in .*/\1/p' "${TMPDIR:-/tmp}/ajs_test_out.$$" | tail -1)
        TESTS_RUN=$((TESTS_RUN + ${n:-0}))
        rm -f "${TMPDIR:-/tmp}/ajs_test_out.$$"
        echo
    done
fi
echo "Unit tests run: $TESTS_RUN in ${#TEST_FILES[@]} files"
echo

echo "=== Leaked-identifier gate ==="
echo

if [ -z "${LEAK_DENYLIST:-}" ]; then
    echo "SKIP leak gate (set LEAK_DENYLIST to enable)"
    echo
    if [ "$OVERALL_STATUS" -eq 0 ]; then echo "=== OVERALL: PASS ==="; else echo "=== OVERALL: FAIL ===" >&2; fi
    exit "$OVERALL_STATUS"
fi

if [ ! -f "$LEAK_DENYLIST" ]; then
    echo "FAIL: \$LEAK_DENYLIST points at '$LEAK_DENYLIST', which does not exist." >&2
    echo "=== OVERALL: FAIL ===" >&2
    exit 1
fi

# Your own working files (config.yaml, FACTS.md, data/, .venv/) are gitignored and never
# ship, so the scan skips them; it checks what a commit of this tree would publish.
EXCLUDES=(--exclude-dir=.git --exclude-dir=__pycache__ --exclude-dir=data --exclude-dir=.venv
          --exclude-dir=venv --exclude=config.yaml --exclude=config.local.yaml --exclude=FACTS.md)

echo "Deny-list: $LEAK_DENYLIST"
echo "Scanning repo root: $REPO_ROOT"
echo

LEAK_FOUND=0

# --- Part 1: deny-list scan (case-insensitive, LITERAL per line -- grep -F, never -E,
#     so a "." or other regex metacharacter in a deny-list term can't wildcard-match
#     unrelated text such as a date) ---
while IFS= read -r term || [ -n "$term" ]; do
    # skip blank lines and comments
    case "$term" in
        ""|\#*) continue ;;
    esac
    matches="$(grep -RIlF -i "${EXCLUDES[@]}" -- "$term" "$REPO_ROOT" 2>/dev/null)"
    if [ -n "$matches" ]; then
        echo "LEAK (deny-list term '$term') found in:"
        echo "$matches" | sed 's/^/    /'
        LEAK_FOUND=1
    fi
done < "$LEAK_DENYLIST"

# --- Part 2: pattern-based scans, LINE-level (not file-level), so a line is only
#     excused when the matched content is one of this repo's own known-fictional or
#     known-benign markers -- a real leak on another line of the same file still fires.
#
#     Fictional-data allowance (repo-wide, not path-restricted -- the Jordan Rivera
#     persona appears intentionally in templates/, tests/fixtures/, config.example.yaml
#     and this script's own comments):
JORDAN_MARKERS='jordan\.rivera@example\.com|555-010-0100|jordan-rivera-example|@example\.com'
# A line that is itself part of this script's own comments/examples (identified by the
# literal guard string below) never counts as a hit on itself.
SELF_MARKER='local label='
# templates/ and tests/fixtures/ hold only fictional data (the Jordan Rivera persona,
# example pay figures, example dates), so a pattern hit in a file under them is allowed.
TEMPLATES_DIR="$REPO_ROOT/templates"
FIXTURES_DIR="$REPO_ROOT/tests/fixtures"

scan_pattern() {
    local label="$1"
    local pattern="$2"
    local extended="$3"       # "-E" or ""
    local allow_extra="${4:-}"  # optional extra grep -E pattern; a matching LINE is allowed
    local egrep_flag=""
    [ "$extended" = "-E" ] && egrep_flag="-E"
    local hits
    hits="$(grep -RIn $egrep_flag "${EXCLUDES[@]}" -- "$pattern" "$REPO_ROOT" 2>/dev/null)"
    [ -z "$hits" ] && return 0

    local flagged=0
    local flagged_files=""
    while IFS= read -r hitline; do
        [ -z "$hitline" ] && continue
        local file="${hitline%%:*}"
        local rest="${hitline#*:}"
        local content="${rest#*:}"
        # allow this script's own source lines that exist only to define the patterns
        case "$content" in
            *"$SELF_MARKER"*|*'scan_pattern '*|*'JORDAN_MARKERS'*|*'# any '*) continue ;;
        esac
        # allow the fictional Jordan Rivera data wherever it legitimately appears
        if echo "$content" | grep -qiE -- "$JORDAN_MARKERS"; then
            continue
        fi
        # allow any hit whose file lives in a fictional-data-by-design directory
        case "$file" in
            "$TEMPLATES_DIR"/*|"$FIXTURES_DIR"/*) continue ;;
        esac
        # allow extra per-pattern benign content (e.g. a User-Agent string for IPv4)
        if [ -n "$allow_extra" ] && echo "$content" | grep -qE -- "$allow_extra"; then
            continue
        fi
        case "$flagged_files" in
            *"|$file|"*) ;;
            *) flagged_files="${flagged_files}|$file|" ;;
        esac
        flagged=1
    done <<< "$hits"
    if [ "$flagged" -eq 1 ]; then
        echo "LEAK ($label) found in:"
        echo "$flagged_files" | tr '|' '\n' | sed '/^$/d' | sed 's/^/    /'
        LEAK_FOUND=1
    fi
    return 0
}

# any email address, except the fictional Jordan Rivera one
scan_pattern "email address" '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' "-E"

# any US-phone-number-shaped string (e.g. 555-010-0100, (555) 010-0100, +1-555-010-0100),
# except the fictional Jordan Rivera one
scan_pattern "US-phone-shaped string" '(\+1[-. ]?)?\(?[0-9]{3}\)?[-. ][0-9]{3}[-. ][0-9]{4}' "-E"

# any IPv4 address, except a browser User-Agent version string (a line carrying
# "Mozilla/5.0") or the loopback address 127.0.0.1 (the tests' dead proxy). Neither is a
# network address of yours.
scan_pattern "IPv4 address" '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' "-E" 'Mozilla/5\.0|127\.0\.0\.1'

# any $-prefixed figure of 2+ digits (so bash's own $1/$2/$3 positional parameters in
# this script and in ported shell tools never self-trigger), except a fictional-data line
scan_pattern "dollar-prefixed number" '\$[0-9]{2,}[0-9,]*(\.[0-9]+)?' "-E"

echo
if [ "$LEAK_FOUND" -ne 0 ]; then
    echo "FAIL: leaked-identifier gate found one or more matches (see above)." >&2
    OVERALL_STATUS=1
else
    echo "PASS: leaked-identifier gate found nothing."
fi

echo
if [ "$OVERALL_STATUS" -eq 0 ]; then
    echo "=== OVERALL: PASS ==="
else
    echo "=== OVERALL: FAIL ===" >&2
fi

exit "$OVERALL_STATUS"
