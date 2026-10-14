#!/bin/bash
# Render a tailored resume or cover letter to PDF, and REFUSE to produce one that would
# embarrass you.
#
# Usage: render-resume_v3.sh <document.html> <CompanyName> [--config PATH] [--chrome-path PATH]
#
# The company argument is mandatory: the <span class="target"> in the resume footer must
# match it exactly. That span is the only place a company name is allowed to appear in the
# closing line, and this is what stops a resume tailored for one company reaching another by
# accident.
#
# A file whose name contains "CoverLetter", "Cover_Letter", "cover_letter" or "coverletter"
# is treated as a cover letter. Anything else is treated as a resume.
#
# Five fail-closed gates:
#   Gate 1: resume footer target == the company you asked to render for (and a cover letter
#           must carry NO target footer at all; that convention belongs to the resume only).
#   Gate 2: no remote webfont reference (@import / fonts.googleapis / fonts.gstatic). Headless
#           print does not wait for a webfont to load, so a remote font silently falls back to
#           a system font and the PDF looks wrong without any error.
#   Gate 3: only your configured font family (render.font_family, default "Carlito") appears
#           in the rendered PDF. Helvetica/.SFNS/Times means the font never resolved.
#   Gate 4: a COVER LETTER's salutation, read off the RENDERED TEXT (not the HTML source),
#           names the company you asked to render for.
#   Gate 5: no name from your banned-names list (gates.banned_names_file) anywhere in the
#           rendered text, on BOTH the resume and the letter (forbidden_names_gate.py).
#
# Needs: python3, a local Chrome/Chromium or Playwright (see render_pdf.py), and poppler
# (pdffonts, pdftotext, pdfinfo). Run `python3 tools/doctor.py --stage render` to check.
# Config: --config, else $JOBSTACK_CONFIG, else ./config.yaml, else <repo>/config.yaml.
set -euo pipefail

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; }
case "${1:-}" in -h|--help) usage; exit 0 ;; esac

SRC="${1:-}"; COMPANY="${2:-}"
if [ -z "$SRC" ] || [ -z "$COMPANY" ]; then usage >&2; exit 2; fi
shift 2
CONFIG_ARGS=(); EXTRA_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG_ARGS=(--config "${2:?--config needs a path}"); shift 2 ;;
    --chrome-path) EXTRA_ARGS+=(--chrome-path "${2:?--chrome-path needs a path}"); shift 2 ;;
    *) echo "REFUSE: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -f "$SRC" ] || { echo "REFUSE: no such file: $SRC" >&2; exit 1; }

HERE=$(cd "$(dirname "$0")" && pwd)
DIR=$(cd "$(dirname "$SRC")" && pwd)
BASE=$(basename "$SRC" .html)
OUT="$DIR/${BASE}.pdf"

# Resolve the config ONCE and pass every value explicitly to the steps below, so every gate
# reads the same file. A missing config or a missing key is a refusal, never a default.
CFG_VALUES=$(AJS_HERE="$HERE" python3 - ${CONFIG_ARGS[@]+"${CONFIG_ARGS[@]}"} <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["AJS_HERE"], "..", ".."))
from tools.common.config import load_config, get, resolve_path, resolve_config_path
args = sys.argv[1:]
explicit = args[1] if args[:1] == ["--config"] else None
path = resolve_config_path(explicit)
cfg = load_config(str(path))
font = get(cfg, "render.font_family", None) or "Carlito"
names = resolve_path(cfg, "gates.banned_names_file")
if not names:
    sys.exit("[render] gates.banned_names_file is not set in " + str(path))
print(path)
print(font)
print(names)
PY
) || { echo "REFUSE: could not read the config (see the message above)." >&2; exit 1; }
CONFIG_FILE=$(printf '%s\n' "$CFG_VALUES" | sed -n 1p)
FONT_FAMILY=$(printf '%s\n' "$CFG_VALUES" | sed -n 2p)
NAMES_FILE=$(printf '%s\n' "$CFG_VALUES" | sed -n 3p)

# --- Gate 1: the footer target must name THIS company, and no other.
# Cover letters carry no target footer by house convention, and a resume does. Detect which
# document this is from its filename rather than refusing, so an agent under pressure cannot
# "fix" a refusal by pasting the resume's closing line into a cover letter to satisfy this
# check -- a gate that cannot tell the two apart invites the document to be mangled to suit it.
case "$(basename "$SRC")" in
  *CoverLetter*|*Cover_Letter*|*cover_letter*|*coverletter*) KIND=cover ;;
  *) KIND=resume ;;
esac

TARGET=$(sed -n 's/.*<span class="target">\([^<]*\)<\/span>.*/\1/p' "$SRC" | head -1)
if [ "$KIND" = resume ] && [ -z "$TARGET" ]; then
  echo "REFUSE: no <span class=\"target\">...</span> in the resume footer. Add one naming $COMPANY." >&2; exit 1
fi
if [ "$KIND" = cover ] && [ -n "$TARGET" ]; then
  echo "REFUSE: this cover letter carries a <span class=\"target\"> footer. That closing line is a" >&2
  echo "        RESUME convention. Remove it rather than adding it to satisfy this script." >&2
  exit 1
fi
if [ "$KIND" = resume ] && [ "$TARGET" != "$COMPANY" ]; then
  echo "REFUSE: footer says '$TARGET' but you asked to render for '$COMPANY'." >&2; exit 1
fi

# --- Gate 2: no webfont fetch. Headless print does not wait for one.
# Strip CSS/HTML comments first: a comment SAYING "@import removed" is not an @import,
# and a guard that cries wolf on its own documentation trains you to run past it.
if python3 -c "
import re,sys
d=open(sys.argv[1],encoding='utf-8').read()
d=re.sub(r'/\\*.*?\\*/','',d,flags=re.S)
d=re.sub(r'<!--.*?-->','',d,flags=re.S)
sys.exit(0 if re.search(r'@import|fonts\\.googleapis|fonts\\.gstatic',d) else 1)
" "$SRC"; then
  echo "REFUSE: remote font reference in $SRC. Use a locally installed font only." >&2; exit 1
fi

# Render. A stale $OUT is deleted first (inside render_pdf.py) so a failed render can never
# leave last run's PDF looking fresh.
python3 "$HERE/render_pdf.py" "$SRC" "$OUT" --config "$CONFIG_FILE" ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
[ -s "$OUT" ] || { echo "REFUSE: no PDF written to $OUT" >&2; exit 1; }

# --- Gate 3: your configured font family only. Helvetica/.SFNS/Times means the font never resolved.
FONTS=$(pdffonts "$OUT" | tail -n +3 | awk '{print $1}' | sed 's/^[A-Z]*+//' | sort -u)
if echo "$FONTS" | grep -qiE 'helvetica|SFNS|Times'; then
  echo "REFUSE: fallback font in $OUT:" >&2; echo "$FONTS" >&2; rm -f "$OUT"; exit 1
fi
FAM=$(printf '%s' "$FONT_FAMILY" | tr -d ' ')   # PDF font names drop spaces: "Liberation Sans" -> LiberationSans-Regular
echo "$FONTS" | grep -qi "^$FAM" || { echo "REFUSE: no $FONT_FAMILY in $OUT (is it installed? see README Prerequisites)" >&2; rm -f "$OUT"; exit 1; }
OTHER=$(echo "$FONTS" | grep -vi "^$FAM" || true)
if [ -n "$OTHER" ]; then
  echo "REFUSE: fonts other than $FONT_FAMILY in $OUT:" >&2; echo "$OTHER" >&2; rm -f "$OUT"; exit 1
fi

# --- Gate 4: a COVER LETTER must be addressed to THIS company, read off the RENDERED text.
# Origin of this gate: a tailoring script can die before touching the letter body, and the file
# that gets rendered is still the one it was forked from. Gates 1-3 alone do not catch that:
# Gate 1 exempts cover letters from the target span BY DESIGN, Gate 3 only checks fonts, and
# nothing else checks WHO the letter was written to. Reads the PDF, not the HTML, because the
# artifact is what ships. Newlines are flattened first so a salutation wrapped across a line
# still matches.
if [ "$KIND" = cover ]; then
  TEXT=$(pdftotext "$OUT" - 2>/dev/null | tr '\n' ' ' | tr -s ' ')
  DEAR=$(printf '%s' "$TEXT" | grep -oE 'Dear [^,]{1,60},' | head -1)
  if [ -z "$DEAR" ]; then
    echo "REFUSE: no 'Dear ...,' salutation found in the rendered letter $OUT" >&2; rm -f "$OUT"; exit 1
  fi
  case "$DEAR" in
    *"$COMPANY"*) : ;;                                         # addressed to this company
    *"Hiring Manager"*|*"Hiring Team"*|*"Recruiting Team"*)
      echo "WARN: generic salutation '$DEAR', not addressed to $COMPANY by name." >&2 ;;
    *)
      echo "REFUSE: letter rendered for '$COMPANY' is addressed '$DEAR'" >&2
      echo "        This is the forked-from letter, not a tailored one. Re-run the tailoring and" >&2
      echo "        check it exited 0 BEFORE rendering. Do not edit the salutation to pass this." >&2
      rm -f "$OUT"; exit 1 ;;
  esac
fi

# --- Gate 5: no forbidden name in the RENDERED text, resume AND letter.
# The list is your configured names file (gates.banned_names_file), read each run; an unreadable
# list or a text-less PDF REFUSES, never passes. Guarded with if/else because this script runs
# set -e and a non-zero gate must not abort before rm.
if python3 "$HERE/forbidden_names_gate.py" --names-file "$NAMES_FILE" "$OUT"; then :; else
  rm -f "$OUT"; exit 1
fi

PAGES=$(pdfinfo "$OUT" | awk '/^Pages:/{print $2}')
echo "OK  $OUT"
echo "    company: $COMPANY   pages: $PAGES"
echo "    fonts:   $(echo "$FONTS" | tr '\n' ' ')"
