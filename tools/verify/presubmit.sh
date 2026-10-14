#!/bin/bash
# presubmit.sh -- refuse to submit a packet that may already be submitted.
#
# Usage: presubmit.sh <Employer/Slug> <req-or-token> --mailbox-hits <N>
#          [--mailbox-roles "role1|role2" --role "this packet's role"]
#          [--data-root PATH] [--config PATH]
#
# Exits 0 ONLY if every tracked source exists and is silent AND the caller has run a LIVE
# mail search and passed its hit count. Any other outcome exits 1 (2 = usage error).
#
# FAIL-SAFE ON MISSING HISTORY. A tracker file that does not exist is a FAIL, never a pass:
# "no file" cannot be told apart from "wrong data root" or "a typo in config". On day one,
# create the files to state that you have no history yet:
#     cp templates/QUEUE.example.md data/QUEUE.md     (or an empty QUEUE.md)
#     touch data/SUBMISSIONS.tsv data/LEDGER_mailbox.tsv data/LEDGER_candidates.tsv
#     python3 tools/sourcing/build_reqs.py              (writes data/BUILD_reqs.tsv)
#
# WHY THE MAIL SEARCH IS MANDATORY, NOT OPTIONAL. This gate was built after a real
# double-submission: every tracked file was silent, and a live mail search would have caught
# it in seconds. There is no default, no --skip, and no flag that bypasses it.
#
# Data root: --data-root, else $JOBSTACK_DATA_ROOT, else paths.data_root from your config.
# File names come from paths.queue_md, paths.submissions_tsv, paths.build_reqs_tsv,
# paths.mailbox_ledger_tsv and paths.candidates_ledger_tsv. A hard-stop marker file
# <data-root>/<Employer/Slug>/DO_NOT_SUBMIT.md fails the gate whatever else is clean.
#
# LIVENESS: the req's row in the build export must say live_state LIVE (written by
# tools/verify/verify_liveness.py). CLOSED, ERROR (the check could not run), blank, or any
# other value fails the gate: unknown liveness is not a pass.

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
usage() { sed -n '4,6p' "$0" | sed 's/^# \{0,1\}//'; }
case "${1:-}" in -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;; esac

DATA_ROOT=""
CONFIG=""
PACKET=""
REQ=""
MB=""
ROLES=""
ROLE=""

# positional: <packet> <req>, then flags
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --mailbox-hits) MB="${2:-}"; shift 2 ;;
    --mailbox-roles) ROLES="${2:-}"; shift 2 ;;
    --role) ROLE="${2:-}"; shift 2 ;;
    --data-root) DATA_ROOT="${2:-}"; shift 2 ;;
    --config) CONFIG="${2:-}"; shift 2 ;;
    -*) echo "presubmit.sh: unknown flag $1" >&2; usage >&2; exit 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
PACKET="${ARGS[0]:-}"
REQ="${ARGS[1]:-}"

if [ -z "$PACKET" ] || [ -z "$REQ" ]; then
  usage >&2
  exit 2
fi

# File names (and the data root, if not given) come from the config. A missing config is a
# refusal: the gate will not guess which trackers to read.
CFG_OUT=$(AJS_HERE="$HERE" AJS_CONFIG="$CONFIG" python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["AJS_HERE"], "..", ".."))
from tools.common.config import load_config, get, resolve_path
cfg = load_config(os.environ.get("AJS_CONFIG") or None)
print(resolve_path(cfg, "paths.data_root") or "")
print(get(cfg, "paths.queue_md", "QUEUE.md"))
print(get(cfg, "paths.mailbox_ledger_tsv", "LEDGER_mailbox.tsv"))
print(get(cfg, "paths.candidates_ledger_tsv", "LEDGER_candidates.tsv"))
print(get(cfg, "paths.submissions_tsv", "SUBMISSIONS.tsv"))
print(get(cfg, "paths.build_reqs_tsv", "BUILD_reqs.tsv"))
PY
) || { echo "GATE FAILED -- could not read the config (see above). Do NOT submit $PACKET"; exit 1; }
line() { printf '%s\n' "$CFG_OUT" | sed -n "${1}p"; }
if [ -z "$DATA_ROOT" ]; then
  DATA_ROOT="${JOBSTACK_DATA_ROOT:-$(line 1)}"
fi
if [ -z "$DATA_ROOT" ] || [ ! -d "$DATA_ROOT" ]; then
  echo "GATE FAILED -- data root '$DATA_ROOT' does not exist. Do NOT submit $PACKET"; exit 1
fi

Q="$DATA_ROOT/$(line 2)"
LM="$DATA_ROOT/$(line 3)"
LC="$DATA_ROOT/$(line 4)"
LS="$DATA_ROOT/$(line 5)"
BR="$DATA_ROOT/$(line 6)"

EMP="${PACKET%%/*}"
fail=0
say() { printf '%-22s %s\n' "$1" "$2"; }

echo "=== PRE-SUBMIT GATE . $PACKET . req $REQ . data root $DATA_ROOT"

# 0. Every tracker must exist. Missing history is a FAIL (see the header comment).
for f in "$Q" "$LM" "$LC" "$LS" "$BR"; do
  if [ ! -f "$f" ]; then
    say "MISSING" "$f"
    echo "                       No file means no history was checked. See presubmit.sh --help."
    fail=1
  fi
done

# 1. MANDATORY live mail search. Counts are EMPLOYER-level, so a non-zero count is not
#    automatically a duplicate -- one real employer can send multiple acks for multiple
#    different open roles. When hits > 0 the caller must pass the roles found
#    (--mailbox-roles "a|b|c") and this packet's role (--role "x"), and the gate compares
#    them itself rather than trusting an assertion.
if [ -z "$MB" ]; then
  say "MAIL SEARCH" "NOT RUN -- this gate does not pass without it."
  echo "                       Run your own mail tool, e.g.: search for \"$EMP\" in the last 30 days"
  echo "                       Then: presubmit.sh $PACKET $REQ --mailbox-hits <n> [--mailbox-roles \"r1|r2\" --role \"this role\"]"
  fail=1
elif [ "$MB" = "0" ]; then
  say "MAIL SEARCH" "0 acks (caller-verified, live)"
elif [ -z "$ROLES" ] || [ -z "$ROLE" ]; then
  say "MAIL SEARCH" "$MB ack(s) for $EMP and no role breakdown given"
  echo "                       Re-run with --mailbox-roles \"<roles in those acks, | separated>\" --role \"<this packet's role>\""
  fail=1
else
  norm() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9'; }
  tgt=$(norm "$ROLE"); clash=""
  IFS='|' read -ra RA <<< "$ROLES"
  for r in "${RA[@]}"; do
    rn=$(norm "$r"); [ -z "$rn" ] && continue
    if [ "$rn" = "$tgt" ]; then clash="$r"; break; fi
  done
  if [ -n "$clash" ]; then
    say "MAIL SEARCH" "an ack already exists for THIS role: $clash"; fail=1
  else
    say "MAIL SEARCH" "$MB ack(s) at $EMP, none matching this role"
    echo "                       seen: $ROLES"
    echo "                       this: $ROLE"
  fi
fi

# 2. QUEUE prose -- SAME-LINE match only. A wider window around a matched req line can
#    cry wolf on unrelated nearby text that happens to look like a submission assertion.
if [ -f "$Q" ] && grep -q -- "$REQ" "$Q" 2>/dev/null; then
  hits=$(grep -n -- "$REQ" "$Q" | grep -viE 'VERIFIED, GO|\| GO \|' \
         | grep -iE 'sent [0-9]|submitted|confirmation page|ack in hand|ack [a-z]+ [0-9]')
  if [ -n "$hits" ]; then
    say "QUEUE" "req on a line asserting submission"
    printf '%s\n' "$hits" | head -3 | cut -c1-150 | sed 's/^/                       /'
    fail=1
  else
    say "QUEUE" "req mentioned, but never on a line asserting submission"
  fi
elif [ -f "$Q" ]; then
  say "QUEUE" "req not mentioned"
fi

# 3. Ledgers
if [ -f "$LM" ] && grep -qi "^$EMP	" "$LM"; then
  say "LEDGER_mailbox" "$(grep -ci "^$EMP	" "$LM") row(s) for $EMP"; fail=1
elif [ -f "$LM" ]; then
  say "LEDGER_mailbox" "no row"
fi

# SUBMISSIONS.tsv carries destination-confirmed sends that a mail sweep alone cannot see
# (some ATSes send no ack) or that postdate the last sweep. Match the req on column 1
# exactly -- a prior send under the same req is a duplicate whichever packet it came from.
# Workday posting ids carry a "-N" suffix that the bare req does not; compare on the bare
# Workday req when either side looks like one.
WDQ='function wd(x,  y){ if (match(x,/(^|[_\/])(JR|RP|R)-?[0-9]+(-[0-9]+)?$/)) { y=substr(x,RSTART,RLENGTH); sub(/^[_\/]/,"",y); if (y ~ /[0-9]-[0-9]+$/) sub(/-[0-9]+$/,"",y); if (y ~ /^(JR|RP|R)-?[0-9]+$/) return y } return "" }
     { if ($1==r || (wd($1)!="" && wd($1)==wd(r))) { hit=1; line=$3" . "$4" . "$5; exit } }
     END{ if (hit) print line; exit !hit }'
if [ -n "$REQ" ] && [ -f "$LS" ] && awk -F'\t' -v r="$REQ" "$WDQ" "$LS" >/dev/null; then
  say "SUBMISSIONS" "req already submitted: $(awk -F'\t' -v r="$REQ" "$WDQ" "$LS")"; fail=1
elif [ -f "$LS" ]; then
  say "SUBMISSIONS" "req not in the submission view"
fi
if [ -f "$LC" ] && grep -qi "^$PACKET	" "$LC"; then
  st=$(grep -i "^$PACKET	" "$LC" | cut -f2)
  case "$st" in
    SUBMITTED*|BLOCKED|STRUCK) say "LEDGER_cand" "status $st"; fail=1 ;;
    *) say "LEDGER_cand" "status $st" ;;
  esac
elif [ -f "$LC" ]; then
  say "LEDGER_cand" "packet not in candidates list"
fi

# 4. A hard-stop marker file at the packet root
if [ -f "$DATA_ROOT/$PACKET/DO_NOT_SUBMIT.md" ]; then
  say "STRUCK" "DO_NOT_SUBMIT.md present at packet root"
  head -3 "$DATA_ROOT/$PACKET/DO_NOT_SUBMIT.md" | sed 's/^/                       /'
  fail=1
else
  say "STRUCK" "no DO_NOT_SUBMIT.md"
fi

# 5. Build's req export -- flag and liveness, joined on req_id (never the folder slug)
if [ -f "$BR" ]; then
  # req_id is NOT unique: a superseded pair can share one req. Prefer the row whose
  # packet_dir matches THIS packet, else a dead sibling's SUPERSEDED flag would fail a
  # live packet.
  row=$(grep -vE '^#|^$' "$BR" | awk -F'\t' -v r="$REQ" -v p="$PACKET" '$2==r && index($7,p)==1 {print; exit}')
  if [ -z "$row" ]; then
    row=$(grep -vE '^#|^$' "$BR" | awk -F'\t' -v r="$REQ" '$2==r {print; exit}')
    [ -n "$row" ] && say "BUILD_reqs" "matched by req only; no row names this packet_dir"
  fi
  if [ -z "$row" ]; then
    say "BUILD_reqs" "req NOT in the build export -- cannot check liveness or your Gate 0. Unjoinable = do not send."; fail=1
  else
    fl=$(printf '%s' "$row" | cut -f9); ls_=$(printf '%s' "$row" | cut -f11)
    case "$fl" in
      *STRUCK*)      say "BUILD_reqs" "flag STRUCK"; fail=1 ;;
      *GATE0*)       say "BUILD_reqs" "flag GATE0 -- fails your own screening filter"; fail=1 ;;
      *SUPERSEDED*)  say "BUILD_reqs" "flag $fl"; fail=1 ;;
      *)             say "BUILD_reqs" "flag ${fl:-none}" ;;
    esac
    case "$ls_" in
      CLOSED) say "LIVENESS" "req is CLOSED at source"; fail=1 ;;
      LIVE)   say "LIVENESS" "LIVE at $(printf '%s' "$row" | cut -f10)" ;;
      ERROR)  say "LIVENESS" "ERROR -- the check could not run, so liveness is unknown. Re-run verify_liveness.py."; fail=1 ;;
      "")     say "LIVENESS" "no live_state recorded -- run verify_liveness.py before sending"; fail=1 ;;
      *)      say "LIVENESS" "unrecognised live_state '$ls_' -- only LIVE passes"; fail=1 ;;
    esac
  fi
fi

echo "---"
if [ "$fail" -eq 0 ]; then echo "GATE PASSED -- safe to submit $PACKET"; exit 0
else echo "GATE FAILED -- do NOT submit $PACKET"; exit 1; fi
