#!/usr/bin/env python3
"""claim_audit.py -- audit a rendered packet's text for claims your own facts-of-record
contradict or do not support.

    python3 claim_audit.py <packet_dir> [<packet_dir> ...] [--rules PATH] [--role-term TERM]

Every rule is a claim your FACTS file (or equivalent facts-of-record) does not support, or
supports only in a narrower form. Controls run first, through the SAME check() function, so
a broken matcher cannot pass silently -- if any control disagrees with its expected answer,
the audit refuses to report anything.

⚠️ The original version of this tool had its claim list -- NEVER-say-this patterns,
NEGATED-unless-qualified terms, and a context rule for a specific identity-provider mention
-- hardcoded inline, citing specific FACTS.md line numbers from one person's resume. All of
that is now loaded from an external rules file: --rules, or gates.claim_rules_file in your
config. The shipped example is tools/examples/claim_audit_rules.example.yaml. Replace the example file with your
own FACTS-derived rules. The mechanism -- NEVER / NEGATED-unless-qualified / CONTEXT
(qualified-mention-ok, ownership-claim-not-ok) / controls-run-first -- is unchanged.
"""
import argparse
import glob
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, resolve_path, add_config_arg  # noqa: E402

NEG = r"\b(not|never|have not|has not|rather than|would be (new|learning)|am not|no|would build depth)\b"


def txt(f):
    """Return the plain text of a rendered document. A `.pdf` goes through pdftotext; a
    `.txt` is read directly. This lets a packet directory under test carry either a real
    rendered PDF (production use) or a plain-text stand-in for the rendered text (so this
    gate is testable, and runnable in CI, without a PDF renderer installed) -- see
    find_rendered() below, which looks for both and prefers the PDF."""
    if f.lower().endswith(".txt"):
        return re.sub(r"\s+", " ", open(f, encoding="utf-8", errors="replace").read())
    return re.sub(r"\s+", " ", subprocess.run(["pdftotext", f, "-"], capture_output=True, text=True).stdout)


def find_rendered(packet_dir, kind):
    """Find the highest-version rendered file for `kind` ('Resume' or 'CoverLetter')
    under <packet_dir>/20_MD/. Prefers a real .pdf; falls back to a .txt of the same name
    if no .pdf exists (see txt() above)."""
    ver = lambda f: int((re.search(r"_v(\d+)\.(pdf|txt)$", f) or [0, 1])[1])
    hits = sorted(glob.glob(f"{packet_dir}/20_MD/*{kind}*.pdf"), key=ver)
    if hits:
        return hits[-1:]
    return sorted(glob.glob(f"{packet_dir}/20_MD/*{kind}*.txt"), key=ver)[-1:]


def _items(block):
    """Parse a sequence of '- key: "value"' / '  key: "value"' entries into a list of dicts."""
    out = []
    cur = None
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


def load_rules(path):
    if not path or not os.path.isfile(path):
        sys.exit(f"[claim_audit] REFUSE: rules file not found: {path}")
    text = open(path, encoding="utf-8").read()
    sections = {}
    for name in ("NEVER", "NEGATED", "CONTEXT", "CONTROLS"):
        m = re.search(rf"^{name}:\s*\n(.*?)(?=^\w+:\s*$|\Z)", text, re.S | re.M)
        sections[name] = _items(m.group(1)) if m else []
    if not sections["NEVER"] and not sections["NEGATED"]:
        sys.exit(f"[claim_audit] REFUSE: rules file has no NEVER or NEGATED entries: {path}")
    return sections


def make_check(rules, role_terms):
    never = [(r["label"], r["pattern"]) for r in rules["NEVER"]]
    negated = [(r["label"], r["pattern"]) for r in rules["NEGATED"]]
    context = [(r["label"], r["term"], r["ok"], r["own"]) for r in rules["CONTEXT"]]
    role_ctx = r"\b(team|Manager|Req|Job|role)\b"

    def check(A):
        probs = []
        for label, term, ok, own in context:
            for s_ in re.split(r"(?<=[.!?])\s+", A):
                if not re.search(term, s_):
                    continue
                if re.search(own, s_, re.I) and not re.search(NEG, s_, re.I):
                    probs.append(f"{label} OWNERSHIP CLAIMED: {s_[:120]}")
                elif not re.search(ok, s_, re.I) and not re.search(NEG, s_, re.I):
                    probs.append(f"{label} without qualifying context: {s_[:120]}")
        for label, pat in never:
            for m in re.finditer(pat, A, re.I):
                probs.append(f"{label}: ...{A[max(0, m.start() - 40):m.end() + 30]}...")
        for s in re.split(r"(?<=[.!?])\s+", A):
            for label, pat in negated:
                if re.search(pat, s, re.I) and not re.search(NEG, s, re.I):
                    if any(re.search(rf"\b{re.escape(t)}\b", s, re.I) for t in role_terms) and re.search(role_ctx, s):
                        continue
                    probs.append(f"{label} CLAIMED: {s[:120]}")
        return probs

    return check


def run_controls(rules, check):
    ctl = [(c["text"], c["expect"].lower() == "true") for c in rules["CONTROLS"]]
    if not ctl:
        print("[claim_audit] WARNING: no CONTROLS in rules file -- running without a self-test", file=sys.stderr)
        return
    bad = [(s, e, len(check(s))) for s, e in ctl if (len(check(s)) > 0) != e]
    if bad:
        print("CONTROLS FAILED -- the audit is broken, refusing to report:")
        for c in bad:
            print("  ", c)
        sys.exit(2)
    print(f"controls: {len(ctl)} of {len(ctl)} behaved as expected")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packet_dirs", nargs="*")
    ap.add_argument("--rules", default=None, help="Claim rules file (default: gates.claim_rules_file from your config)")
    ap.add_argument("--role-term", action="append", default=[], help="A role-title term to exempt from NEGATED matches (repeatable)")
    add_config_arg(ap)
    args = ap.parse_args()

    rules_path = args.rules or resolve_path(load_config(args.config), "gates.claim_rules_file")
    if not rules_path:
        sys.exit("[claim_audit] REFUSE: no --rules given and gates.claim_rules_file is not set in config")
    rules = load_rules(rules_path)
    check = make_check(rules, args.role_term)
    run_controls(rules, check)

    if not args.packet_dirs:
        # Controls-only run (no packets given): controls already ran and passed above
        # (run_controls exits 2 itself if they didn't), so this is a clean exit 0 --
        # not "problems: 0" printed as if a packet had been audited.
        return 0
    tot = 0
    for d in args.packet_dirs:
        # A folder may hold v1 AND a later _v2 kept beside it (never overwritten); glob
        # order is arbitrary, so audit the highest version. Accepts a real rendered .pdf
        # or a plain .txt stand-in for one -- see find_rendered()/txt() above.
        R = find_rendered(d, "Resume")
        L = find_rendered(d, "CoverLetter")
        if not R or not L:
            print(f"\n{d}: MISSING rendered resume/cover letter (resume={len(R)} letter={len(L)})")
            tot += 1
            continue
        Rt = txt(R[0])
        Lt = txt(L[0])
        probs = check(Rt + " " + Lt)
        dear = re.search(r"Dear [^,]+,", Lt)
        label = os.path.basename(os.path.normpath(d))
        print(
            f"\n{label}: {len(probs)} problem(s)   "
            f"addressee: {dear.group(0) if dear else 'NONE'}   "
            f"[{os.path.basename(R[0])} + {os.path.basename(L[0])}]"
        )
        for p in probs:
            print("   !!", p[:160])
        tot += len(probs)
    print("\nTOTAL PROBLEMS:", tot)
    # Explicit, unambiguous: a nonzero problem count is ALWAYS a nonzero exit code.
    # (This used to be `sys.exit(1 if tot else 0)` called from inside main() -- functionally
    # the same, but returning an int and letting the module-level `sys.exit(main())` be the
    # ONLY place that ever calls sys.exit for this path removes any chance of a caller that
    # imports and invokes main() directly swallowing the SystemExit and reporting success.)
    return 1 if tot else 0


if __name__ == "__main__":
    sys.exit(main())
