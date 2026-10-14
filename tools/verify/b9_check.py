#!/usr/bin/env python3
"""
b9_check.py -- independent post-build gate. Runs over rendered PDF TEXT, not the HTML
source, because the PDF is what actually gets sent.

    python3 b9_check.py <pdf> [<pdf> ...] [--rules PATH]

Carries a positive control: a synthetic string built from every banned pattern must trip
every single rule. If the control does not fire, the run is INVALID and says so rather
than printing a clean pass on a broken matcher.

Also runs a cross-letter six-gram overlap check across every cover-letter PDF given:
phrases your facts file or build brief mandate verbatim (loaded from the same rules file,
`protected_phrases`) are excluded before judging overlap, so required repetition across
two letters is never scored as unwanted duplication/copy-paste. Everything else repeated
across two letters IS flagged -- that is the actual anti-duplication check.

⚠️ The original version of this tool had its banned-pattern list and its protected-phrase
list hardcoded inline, naming real former-employer claims and FACTS-specific sentences.
Both lists are now loaded from an external rules file: --rules, or gates.b9_rules_file in
your config. The shipped example is tools/examples/b9_check_rules.example.yaml. Replace it
with your own.

Exit codes: 0 = clean, 1 = a banned pattern or a cross-letter overlap was found,
2 = INVALID (the control did not fire, or no rules file).
"""
import argparse
import itertools
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, resolve_path, add_config_arg  # noqa: E402


def _items(block):
    out, cur = [], None
    for line in block.splitlines():
        m = re.match(r'^\s*-\s*(\w+):\s*"(.*)"\s*$', line)
        if m:
            if cur is not None:
                out.append(cur)
            cur = {m.group(1): m.group(2)}
            continue
        m = re.match(r'^\s+(\w+):\s*"(.*)"\s*$', line)
        if m and cur is not None:
            cur[m.group(1)] = m.group(2)
    if cur is not None:
        out.append(cur)
    return out


def _list_items(block):
    """Parse a flat '  - "value"' list (used for protected_phrases)."""
    out = []
    for line in block.splitlines():
        m = re.match(r'^\s*-\s*"(.*)"\s*$', line)
        if m:
            out.append(m.group(1))
    return out


def load_rules(path):
    if not path or not os.path.isfile(path):
        sys.exit(f"[b9_check] REFUSE: rules file not found: {path}")
    text = open(path, encoding="utf-8").read()
    sections = {}
    cur_key, cur_lines = None, []
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s*$", line)
        if m:
            if cur_key:
                sections[cur_key] = "\n".join(cur_lines)
            cur_key, cur_lines = m.group(1), []
        elif cur_key:
            cur_lines.append(line)
    if cur_key:
        sections[cur_key] = "\n".join(cur_lines)

    banned_raw = _items(sections.get("banned", ""))
    banned = {d["label"]: d["pattern"] for d in banned_raw if "label" in d and "pattern" in d}
    protected = _list_items(sections.get("protected_phrases", ""))
    if not banned:
        sys.exit("[b9_check] REFUSE: rules file has an empty or unparseable 'banned' list")
    return banned, protected


def pdftext(p):
    return subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout


DATELINE = re.compile(
    r"^\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}\b",
    re.M,
)


def body(t):
    """Drop the letterhead block (name/tagline/contact line), which is identical by
    design across every letter -- comparing it would report duplication that isn't real.
    Cut at the dateline, which every letter carries and no header does."""
    m = DATELINE.search(t)
    return t[m.start():] if m else t


def protected_grams(protected):
    out = set()
    for p in protected:
        w = p.split()
        for i in range(max(0, len(w) - 5)):
            out.add(tuple(w[i : i + 6]))
    return out


def sixgrams(t):
    w = re.findall(r"[a-z0-9']+", t.lower())
    return set(tuple(w[i : i + 6]) for i in range(len(w) - 5))


def build_control_string(banned):
    """A synthetic string must trip every rule. Since rules are loaded from a file we don't
    control, build the control from a literal fragment of each pattern's first alternative
    rather than hand-typing a sentence that could drift out of sync.

    Regex escapes are handled before metacharacters are stripped: a class or anchor escape
    such as \\b, \\s or \\d becomes a space (so "\\bGlobex" yields "Globex", not "bGlobex"),
    and an escaped literal such as \\. becomes the literal character."""
    frags = []
    for pat in banned.values():
        alt = pat.split("|")[0]
        out, i = [], 0
        while i < len(alt):
            ch = alt[i]
            if ch == "\\" and i + 1 < len(alt):
                nxt = alt[i + 1]
                out.append(" " if nxt.isalpha() else nxt)  # \b -> space, \. -> "."
                i += 2
                continue
            if ch not in "^$*+?()[]{}":
                out.append(ch)                              # drop bare metacharacters
            i += 1
        literal = re.sub(r"\s+", " ", "".join(out)).strip()
        if literal:
            frags.append(literal)
    return " ".join(frags) if frags else " "


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*", help="Rendered PDFs to check (cover letters are also compared pairwise)")
    ap.add_argument("--rules", default=None, help="Rules file (default: gates.b9_rules_file from your config)")
    add_config_arg(ap)
    a = ap.parse_args(argv)

    rules_path = a.rules or resolve_path(load_config(a.config), "gates.b9_rules_file")
    if not rules_path:
        print("[b9_check] REFUSE: no --rules given and gates.b9_rules_file is not set in config", file=sys.stderr)
        return 2
    banned, protected = load_rules(rules_path)
    PROT = protected_grams(protected)

    control = build_control_string(banned)
    fired = [k for k, rx in banned.items() if re.search(rx, control, re.I)]
    missing = [k for k in banned if k not in fired]
    if missing:
        print("INVALID RUN - the control did not trip:", missing)
        return 2
    print(f"control: {len(fired)} of {len(banned)} rules fired on the synthetic string - matcher is live\n")

    bad = 0
    letters = {}
    for p in a.pdfs:
        t = pdftext(p)
        name = os.path.basename(p)
        if not t.strip():
            print(f"  !! {name}: pdftotext returned NOTHING - cannot clear this file")
            bad += 1
            continue
        hits = [k for k, rx in banned.items() if re.search(rx, t, re.I)]
        print(f"  {'FAIL' if hits else 'ok  '} {name[:70]:70s} {len(t):6d} chars  {hits if hits else ''}")
        if hits:
            bad += 1
        if "coverletter" in name.lower() or "cover_letter" in name.lower():
            letters[name] = body(t)

    print()
    ks = sorted(letters)
    common = set.intersection(*[sixgrams(letters[k]) for k in ks]) if len(ks) > 1 else set()
    for x, y in itertools.combinations(ks, 2):
        ga, gb = sixgrams(letters[x]), sixgrams(letters[y])
        ov = ga & gb
        ov2 = ov - common - PROT
        print(f"  six-gram overlap {x[:28]:28s} x {y[:28]:28s} raw={len(ov)} discretionary={len(ov2)}")
        if ov2:
            bad += 1
            for g in list(ov2)[:3]:
                print("     >>", " ".join(g))

    print(f"\nRESULT: {'FAIL' if bad else 'PASS'} ({bad} problem file(s)/pair(s))")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
