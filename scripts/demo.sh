#!/usr/bin/env bash
# demo.sh -- the 5-minute offline demo. Runs the anti-fabrication gates on the fictional
# Jordan Rivera fixtures and checks that each gate behaves: good inputs pass, bad inputs are
# caught. No network, no personal data, no config.yaml needed (the fictional example config
# and rule files are passed explicitly).
#
# Usage: bash scripts/demo.sh [--help]
# Exit 0 = every gate behaved as expected. Exit 1 = at least one did not.
set -u

case "${1:-}" in -h|--help) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;; esac

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
PY="${PYTHON:-python3}"
export PYTHONDONTWRITEBYTECODE=1   # the demo leaves the checkout exactly as it found it
CFG="config.example.yaml"
FX="tests/fixtures"
EX="tools/examples"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

PASS=0; FAIL=0
step() { printf '\n== %s\n' "$1"; }
show() {
  sed -n '1,12p' "$OUT/last" | sed 's/^/   | /'
  local n; n=$(wc -l < "$OUT/last"); [ "$n" -gt 12 ] && echo "   | ... ($((n-12)) more lines)"
  return 0
}
# expect <label> <wanted exit code> <grep pattern that must appear in the output> -- cmd...
expect() {
  local label="$1" want="$2" pat="$3"; shift 4
  "$@" >"$OUT/last" 2>&1; local rc=$?
  show
  if [ "$rc" = "$want" ] && grep -qE -- "$pat" "$OUT/last"; then
    printf '   OK    %s (exit %s)\n' "$label" "$rc"; PASS=$((PASS+1))
  else
    printf '   WRONG %s (exit %s, wanted %s and /%s/)\n' "$label" "$rc" "$want" "$pat"; FAIL=$((FAIL+1))
  fi
}

echo "agentic-job-search demo: every input below is fictional (Jordan Rivera, Acme Corp)."

step "1. claim_audit: does each claim trace to the facts? (controls run first)"
expect "truthful packet passes" 0 "good_packet: 0 problem" -- \
  "$PY" tools/verify/claim_audit.py "$FX/claim_audit/good_packet" --rules "$EX/claim_audit_rules.example.yaml"
expect "inflated packet is caught" 1 "bad_packet: 2 problem" -- \
  "$PY" tools/verify/claim_audit.py "$FX/claim_audit/bad_packet" --rules "$EX/claim_audit_rules.example.yaml"

step "2. verify_readback: does a cover letter leak a banned name?"
expect "leaked codename is caught, clean packet passes" 1 "BANNED NAME 'globex-project-nightingale'" -- \
  "$PY" tools/verify/verify_readback.py --packets-dir "$FX/packets" \
    --banned-names-file "$FX/banned_names.fixture.txt" --banned-claims-file "$EX/banned_claims.example.yaml"
if grep -qE '^clean_packet .* PASS$' "$OUT/last"; then
  printf '   OK    clean_packet PASS in the same run\n'; PASS=$((PASS+1))
else
  printf '   WRONG clean_packet did not PASS\n'; FAIL=$((FAIL+1))
fi

step "3. check-distinct: are two cover letters copy-paste of each other?"
expect "near-copy letters are caught" 1 "shared 6-grams: [1-9]" -- \
  "$PY" tools/build/check-distinct.py "$FX/distinctiveness/similar_1.html" "$FX/distinctiveness/similar_2.html"
expect "distinct letters pass" 0 "shared 6-grams: 0" -- \
  "$PY" tools/build/check-distinct.py "$FX/distinctiveness/distinct_1.html" "$FX/distinctiveness/distinct_2.html"

step "4. collision_check: can the 'already applied?' check actually fire?"
expect "16 controls behave" 0 "controls: 16 of 16 behaved" -- \
  "$PY" tools/verify/collision_check.py --controls --config "$CFG"

step "5. b9_check: do the banned-pattern rules fire on a synthetic control?"
expect "every rule fires on the control" 0 "control: 4 of 4 rules fired" -- \
  "$PY" tools/verify/b9_check.py --rules "$EX/b9_check_rules.example.yaml"

echo
echo "== Summary: $PASS behaved as expected, $FAIL did not"
if [ "$FAIL" -eq 0 ]; then
  echo "DEMO PASSED: every gate behaved as expected"
  exit 0
fi
echo "DEMO FAILED: see WRONG lines above" >&2
exit 1
