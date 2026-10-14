#!/usr/bin/env python3
"""verify_readback.py -- read back every packet and gate it.

    python3 verify_readback.py --packets-dir <dir>       # table + verdict per packet
    python3 verify_readback.py --packets-dir <dir> --json # machine-readable

WHY: a batch of packets written by several agents/sessions cannot be checked by reading
them one at a time. Every rule here exists because it was broken on a real application at
least once:
  - a banned client/employer name reached multiple packets before being caught
  - em dashes shipped despite the house style rule being cited twice
  - a cover letter made a claim the candidate's own facts-of-record contradict
  - a match_pct with no evidence behind it is a guess wearing a number

⚠️ BANNED_NAMES and BANNED_PHRASES are never hardcoded in this script. The original
version of this tool had three real confidential client/employer names and a
bio-specific false-claim regex inline. Both now come from files: --banned-names-file and
--banned-claims-file, or gates.banned_names_file and gates.banned_claims_file in your
config. The shipped examples are tools/examples/banned_names.example.txt and
tools/examples/banned_claims.example.yaml. The mechanism (banned-name scan, banned-phrase
scan with a quote exemption, the unevidenced-match-score check) is unchanged.

A packet is a folder holding packet.json, cover.html and answers.md. See
tests/fixtures/packets/clean_packet/ for a complete example.

Exit codes: 0 = every packet passes, 1 = at least one FAIL, 2 = zero packets found.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, resolve_path, add_config_arg  # noqa: E402

REQUIRED_JSON = ("n", "slug", "company", "title", "location", "url", "ats", "match_pct", "match_evidence", "gaps")

# Quoting the employer's own JD language back at them is good writing, not slop.
QUOTING = re.compile(r'(your posting|the posting|you (?:ask|say|write)|asks for|"[^"]{0,120}$)', re.I)


def strip_html(t):
    t = re.sub(r"<style.*?</style>|<script.*?</script>", " ", t, flags=re.S)
    return re.sub(r"<[^>]+>", " ", t)


def load_banned_names(path):
    if not path or not os.path.isfile(path):
        sys.exit(f"[verify_readback] REFUSE: banned-names file not found: {path}. A gate with no list checks nothing.")
    with open(path, encoding="utf-8") as f:
        names = [l.strip().lower() for l in f if l.strip() and not l.strip().startswith("#")]
    if not names:
        sys.exit(f"[verify_readback] REFUSE: banned-names file is empty: {path}")
    return tuple(names)


def load_banned_phrases(path):
    """Tiny dedicated parser for the fixed `- pattern: "..."` / `  why: "..."` shape --
    not a general YAML reader. See banned_claims.example.yaml for the exact shape."""
    if not path or not os.path.isfile(path):
        sys.exit(f"[verify_readback] REFUSE: banned-claims file not found: {path}")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    pairs = re.findall(r'-\s*pattern:\s*"(.*?)"\s*\n\s*why:\s*"(.*?)"', text, re.S)
    if not pairs:
        sys.exit(f"[verify_readback] REFUSE: no pattern/why entries parsed from {path}")
    return [(p, w) for p, w in pairs]


def check(d, banned_names, banned_phrases):
    slug = os.path.basename(d.rstrip("/"))
    r = {"slug": slug, "errors": [], "warnings": []}
    pj, am, ch = (os.path.join(d, x) for x in ("packet.json", "answers.md", "cover.html"))
    for f, label in ((pj, "packet.json"), (am, "answers.md"), (ch, "cover.html")):
        if not os.path.exists(f):
            r["errors"].append(f"MISSING {label}")
    if r["errors"]:
        return r
    try:
        with open(pj, encoding="utf-8") as f:
            p = json.load(f)
    except Exception as e:
        r["errors"].append(f"packet.json unparseable: {e}")
        return r
    for k in REQUIRED_JSON:
        if k not in p:
            r["errors"].append(f"packet.json missing key: {k}")
    r["company"] = p.get("company", "")
    r["title"] = p.get("title", "")
    r["match_pct"] = p.get("match_pct")
    ev = p.get("match_evidence") or []
    if isinstance(r["match_pct"], (int, float)):
        if r["match_pct"] < 90:
            r["warnings"].append(f"match {r['match_pct']}% is below the 90 bar")
        if len(ev) < 3:
            r["errors"].append(f"match_pct {r['match_pct']} backed by only {len(ev)} evidence lines")
    else:
        r["errors"].append("match_pct missing or not a number")
    if p.get("finding"):
        r["warnings"].append(f"FINDING recorded: {str(p['finding'])[:80]}")
    # A boolean flag like "jd_fetched: true" asserts something about a file while living in a
    # DIFFERENT file from it, and cannot distinguish KEPT from DISCARDED. The file on disk is
    # the evidence; assert the artifact, never a flag about it.
    jd = p.get("jd_file") or {}
    jd_path = jd.get("path")
    if not jd_path:
        r["warnings"].append("no jd_file recorded -- the JD was not frozen at build time")
    elif not os.path.exists(jd_path):
        r["errors"].append(f"jd_file recorded but MISSING on disk: {jd_path}")
    else:
        with open(jd_path, "rb") as f:
            got = hashlib.sha256(f.read()).hexdigest()
        if got != jd.get("sha256"):
            r["errors"].append(f"jd_file sha256 does not match {jd_path} -- the stored JD changed after capture")
        if not jd.get("captured_relative_to_submission"):
            r["warnings"].append(f"{jd_path} does not say WHEN it was captured relative to submission")

    with open(ch, encoding="utf-8", errors="replace") as f:
        cover_raw = f.read()
    cover = strip_html(cover_raw)
    with open(am, encoding="utf-8", errors="replace") as f:
        ans = f.read()

    def in_quote(body, idx):
        return bool(QUOTING.search(body[max(0, idx - 140):idx]))

    for body, label in ((cover, "cover"), (ans, "answers")):
        low = body.lower()
        for n in banned_names:
            if n in low:
                r["errors"].append(f"BANNED NAME '{n}' in {label}")
        for pat, why in banned_phrases:
            for m in re.finditer(pat, low):
                if "slop phrase" in why and in_quote(low, m.start()):
                    r["warnings"].append(f"{why} in {label} (inside a JD quote - allowed)")
                else:
                    r["errors"].append(f"{why} in {label}")
                break
    if "—" in cover:
        r["errors"].append("em dash in rendered cover text")
    if "—" in ans:
        r["warnings"].append("em dash in answers.md")
    words = len(cover.split())
    if words < 180:
        r["warnings"].append(f"cover only {words} words")
    if "Dear" not in cover_raw:
        r["warnings"].append("no salutation in cover")
    r["cover_words"] = words
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packets-dir", default=None, help="Directory containing one subfolder per packet (default: paths.data_root from config)")
    ap.add_argument("--banned-names-file", default=None, help="Banned-names list (default: gates.banned_names_file from your config)")
    ap.add_argument("--banned-claims-file", default=None, help="Banned-claims list (default: gates.banned_claims_file from your config)")
    ap.add_argument("--json", action="store_true")
    add_config_arg(ap)
    args = ap.parse_args()

    need_cfg = not (args.packets_dir and args.banned_names_file and args.banned_claims_file)
    cfg = load_config(args.config) if need_cfg else {}
    packets_dir = args.packets_dir or resolve_path(cfg, "paths.data_root")
    names_path = args.banned_names_file or resolve_path(cfg, "gates.banned_names_file")
    claims_path = args.banned_claims_file or resolve_path(cfg, "gates.banned_claims_file")
    if not packets_dir:
        sys.exit("[verify_readback] REFUSE: no --packets-dir given and paths.data_root is not set in config")
    banned_names = load_banned_names(names_path)
    banned_phrases = load_banned_phrases(claims_path)

    if not os.path.isdir(packets_dir):
        sys.exit(f"[verify_readback] packets dir not found: {packets_dir}")
    os.chdir(packets_dir)
    # Anchoring to a cwd-relative glob is deliberate but EXPLICIT here (via --packets-dir /
    # os.chdir above), not implicit on wherever the caller happened to run from -- a silent
    # cwd-relative glob that finds zero packets prints "0 PASS 0 FAIL 0 packets", which reads
    # exactly like a clean run. See the zero-guard below.
    dirs = sorted(d for d in glob.glob("*/") if os.path.exists(os.path.join(d, "packet.json")) or not d.startswith("_"))
    dirs = [d for d in dirs if os.path.isdir(d) and d not in ("./",)]
    res = [check(d, banned_names, banned_phrases) for d in dirs]
    res = [r for r in res if not (len(r["errors"]) == 3 and all("MISSING" in e for e in r["errors"]))]
    if not res:
        print("GATE FOUND ZERO PACKETS. This is a broken instrument, not a pass.")
        sys.exit(2)
    if args.json:
        print(json.dumps(res, indent=1))
        return
    ok = fail = 0
    print(f"{'PACKET':38} {'MATCH':>6}  {'WORDS':>5}  VERDICT")
    print("-" * 88)
    for r in sorted(res, key=lambda x: -(x.get("match_pct") or 0)):
        v = "PASS" if not r["errors"] else "FAIL"
        ok += v == "PASS"
        fail += v == "FAIL"
        m = r.get("match_pct")
        m = f"{m}%" if m is not None else "  ?"
        print(f"{r['slug'][:38]:38} {m:>6}  {r.get('cover_words', '?'):>5}  {v}")
        for e in r["errors"]:
            print(f"    [FAIL] {e}")
        for w in r["warnings"]:
            print(f"    [warn] {w}")
    print("-" * 88)
    print(f"{ok} PASS   {fail} FAIL   {len(res)} packets   checked {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
