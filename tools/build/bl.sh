#!/bin/sh
# bl.sh -- run book_link.py with the repo's virtualenv, if there is one.
# Usage: bl.sh <book_link.py arguments>   (bl.sh --help shows book_link's help)
# Uses <repo>/.venv/bin/python when it exists (the venv the README creates, with the
# optional `render` extra installed for Playwright), else python3 on PATH. PYTHONPATH is
# unset so a user-level PYTHONPATH cannot shadow the venv's packages.
D=$(cd "$(dirname "$0")" && pwd)
PY="$D/../../.venv/bin/python"
[ -x "$PY" ] || PY=python3
exec env -u PYTHONPATH "$PY" "$D/book_link.py" "$@"
