#!/bin/bash
# Sweep every PDF under a path for forbidden names (see forbidden_names_gate.py).
# Usage: sweep-forbidden-names.sh [path] [-- extra args passed to forbidden_names_gate.py]
# Default path: $JOBSTACK_DATA_ROOT if set, else the current directory.
# One line per hit or refusal on stderr; summary on stdout.
# Exit 0 = all clean . 1 = at least one hit . 2 = at least one PDF could not be checked, or
# zero PDFs were found (a sweep that checked nothing is not a pass).
#
# The names list comes from forbidden_names_gate.py: --names-file, else
# gates.banned_names_file in your config. Pass extra flags (--names-file, --config) after `--`.
set -uo pipefail
case "${1:-}" in -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;; esac
HERE=$(cd "$(dirname "$0")" && pwd)
P="${1:-${JOBSTACK_DATA_ROOT:-.}}"
shift || true
if [ "${1:-}" = "--" ]; then shift; fi
EXTRA_ARGS=("$@")
[ -d "$P" ] || { echo "REFUSE: not a directory: $P" >&2; exit 2; }

n=0; hit=0; ref=0
while IFS= read -r -d '' f; do
  n=$((n+1))
  python3 "$HERE/forbidden_names_gate.py" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"} "$f"; rc=$?
  [ $rc = 1 ] && hit=$((hit+1))
  [ $rc = 2 ] && ref=$((ref+1))
done < <(find "$P" -name '*.pdf' -not -path '*/_HISTORY/*' -print0)
echo "swept $n PDFs under $P: $hit with a forbidden name, $ref could not be checked"
if [ "$n" -eq 0 ]; then echo "REFUSE: no PDFs found under $P; nothing was checked." >&2; exit 2; fi
[ $hit -gt 0 ] && exit 1; [ $ref -gt 0 ] && exit 2; exit 0
