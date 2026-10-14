#!/usr/bin/env python3
"""Forbidden-name gate on a RENDERED PDF.

Usage: forbidden_names_gate.py [--names-file PATH] [--config PATH] <pdf>...
Exit 0 = every PDF clean · 1 = a forbidden name found · 2 = REFUSE (list unreadable, or text too thin to check).

The forbidden-name list is read from an external file EVERY run -- never hardcoded in this
script. Fails closed: a missing, unreadable, or empty list REFUSES rather than silently
checking nothing (a stale second copy of the list would under-report while looking healthy).

The list is the same plain file every name gate reads (config key gates.banned_names_file):
one name per line, '#'-prefixed lines ignored. Matching here is case-insensitive and
whole-word, and tolerates whitespace or a soft hyphen between letters, because PDF text
extraction can split a word across a line break.

⚠️ The original version of this tool had a hardcoded dict of real former-employer/client
names mapped to anonymized replacement phrasing. That is removed entirely. No name is ever
hardcoded here. If you want the refusal message to suggest a specific replacement phrase,
keep your own optional replacements file (one "name<TAB>replacement phrase" per line) and
pass it via --replacements-file. Otherwise the refusal names the match and leaves the
substitute phrasing to you.

Names-file resolution: --names-file, else gates.banned_names_file from your config.
Needs `pdftotext` (poppler) on PATH.
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, resolve_path, add_config_arg  # noqa: E402

MIN_CHARS = 200  # a real packet PDF's extracted text should clear this; zero observed under it in testing


def load_names(path):
    """Read the plain names list. Exits 2 (REFUSE) if it is unreadable or has no names."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, TypeError) as e:
        print(f"REFUSE: cannot read the forbidden-name list: {path} ({getattr(e, 'strerror', e)})", file=sys.stderr)
        sys.exit(2)
    names = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    if not names:
        print(f"REFUSE: the forbidden-name list {path} is empty. A gate with no list checks nothing.", file=sys.stderr)
        sys.exit(2)
    return names


def load_replacements(path):
    if not path or not os.path.isfile(path):
        return {}
    out = {}
    for line in open(path, encoding="utf-8"):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t", 1)
        if len(parts) == 2:
            out[parts[0].strip().lower()] = parts[1].strip()
    return out


def pattern(name):
    # case-insensitive; tolerate whitespace or a soft hyphen between letters, whole-word at the ends
    gap = r"(?:\s|­)?"
    return re.compile(r"(?<![A-Za-z])" + gap.join(re.escape(c) for c in name) + r"(?![A-Za-z])", re.I)


def pages(pdf):
    r = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace").split("\f")


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*", help="Rendered PDF(s) to check")
    ap.add_argument("--names-file", default=None, help="Names list, one per line (default: gates.banned_names_file from your config)")
    ap.add_argument("--replacements-file", default=None, help="Optional TSV of name<TAB>suggested replacement phrase")
    add_config_arg(ap)
    args = ap.parse_args(argv)

    if not args.pdfs:
        ap.print_usage(sys.stderr)
        print("forbidden_names_gate.py: error: give at least one PDF", file=sys.stderr)
        return 2

    names_file = args.names_file or resolve_path(load_config(args.config), "gates.banned_names_file")
    if not names_file:
        print("REFUSE: no --names-file given and gates.banned_names_file is not set in config", file=sys.stderr)
        return 2
    replacements = load_replacements(args.replacements_file)

    pats = [(n, pattern(n)) for n in load_names(names_file)]
    worst = 0
    for pdf in args.pdfs:
        pg = pages(pdf)
        if pg is None:
            print(f"REFUSE: pdftotext could not read {pdf}", file=sys.stderr)
            worst = max(worst, 2)
            continue
        chars = sum(len(re.sub(r"\s", "", p)) for p in pg)
        if chars < MIN_CHARS:
            print(
                f"REFUSE: only {chars} characters extracted from {pdf} (minimum {MIN_CHARS}). An image-only or "
                f"failed extraction cannot be checked, so it cannot pass.",
                file=sys.stderr,
            )
            worst = max(worst, 2)
            continue
        for i, p in enumerate(pg, 1):
            flat = re.sub(r"\s+", " ", p)
            for n, rx in pats:
                if rx.search(flat):
                    fix = replacements.get(n.lower(), "your own anonymised phrasing for this name")
                    print(
                        f'REFUSE: forbidden name in {pdf}: "{n}" (page {i})\n'
                        f"        Your forbidden-names list bars this name. Suggested replacement: \"{fix}\",\n"
                        f"        edited in the HTML SOURCE and re-rendered.\n"
                        f"        Do NOT obfuscate the string to satisfy this check.",
                        file=sys.stderr,
                    )
                    worst = max(worst, 1)
    return worst


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
