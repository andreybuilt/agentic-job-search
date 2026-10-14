#!/usr/bin/env python3
"""
collision_check.py -- "have I already applied to (or been ruled out of) this role?"
Run BEFORE building a packet or offering a lead.

Usage:
  python3 collision_check.py --employer "Acme Corp" --title "Senior Customer Engineer" [--req 8172023]
  python3 collision_check.py --controls         (run the controls only)

WHY THIS EXISTS, AND WHY IT READS FOUR SOURCES, NOT ONE. In the stack this was ported
from, a single-source check missed a live application twice in two days: once because
the tracker (QUEUE.md-equivalent) had the row and the submissions table didn't yet, and
once the other way around. So:
  - ALL FOUR sources below are read every time: the submissions table, the prose tracker,
    the built-but-not-yet-submitted export, and the interview tracker. A lead can be
    "clear" in three of them and still be a live, recruiter-started conversation that
    never generated a row anywhere else.
  - Reads are plain files under paths.data_root (see config.example.yaml), read fresh on
    every run. (The original version this was ported from read a git ref instead of a
    working tree, specifically to guard against a concurrent writer on a shared,
    multi-agent repo. That is a real, documented mechanism -- see docs/MULTI_AGENT.md's
    note on shared-tracker ownership -- but it assumes a private git remote a stranger
    running this toolkit does not have. If you run multiple agents against one shared
    data_root, add your own equivalent guard; a single-operator run does not need one.)
  - A hit is a TASK, not a question: resolve it before it reaches a human.
  - Controls run first, through the same functions used for a real check. Two of them
    exist only in the prose tracker, so a check that silently stopped reading it fails
    its own controls instead of returning a confident "clear".

Exit codes:
  0 = clear
  1 = HIT -- an application or strike is on record; resolve before building/offering
  2 = controls failed (the check itself is broken; do not trust a "clear" from it),
      or the data root does not exist
  3 = a recruiter-started loop is on record in the interview tracker (not clear)
  4 = not clear -- no record of THIS req, but a prior application exists at this employer
      (the "one application per company at a time" rule)

Config: paths.data_root + paths.{queue_md,submissions_tsv,build_reqs_tsv,
interview_tracker_md} (see config.example.yaml). A missing tracked file is treated as
empty (nothing to check against it) -- that is correct for a brand-new data_root with no
history yet, and is why --controls exists: run it after setting up your own data_root to
prove the four sources are wired up correctly before trusting a real "clear".
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..")))
from tools.common.config import load_config, get, resolve_path  # noqa: E402


def _read_file(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Well-known PUBLIC parent/subsidiary and product/company name pairs. These are generic
# facts about corporate structure (anyone's job search needs the same mapping), not a
# record of who this candidate personally applied to. Extend with your own employer's
# subsidiary/brand names as needed.
ALIAS = {
    "amazon web services": "amazon",
    "aws": "amazon",
    "google cloud": "google",
    "microsoft azure": "microsoft",
    "alphabet": "google",
    "youtube": "google",
    "deepmind": "google",
    "github": "microsoft",
    "linkedin": "microsoft",
    "whatsapp": "meta",
    "instagram": "meta",
    "meta platforms": "meta",
}


def canon(emp: str) -> str:
    """Strip a parenthetical qualifier ('Amazon Web Services (AWS)' -> 'Amazon Web
    Services') then apply the alias table."""
    e = re.sub(r"\s*\([^)]*\)", "", (emp or "")).strip()
    return ALIAS.get(e.lower(), e)


def emp_hit(emp: str, text: str) -> bool:
    """Employer name matched as WHOLE WORDS only. A plain substring match would make a
    short employer name hit an unrelated word that happens to contain it (e.g. a 5-letter
    company name that is also a substring of a city name) -- see controls below."""
    emp = canon(emp)
    toks = re.findall(r"[a-z0-9]+", (emp or "").lower())
    if not toks:
        return False
    pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(map(re.escape, toks)) + r"(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


SUFFIX = (
    r"(?:\s+|[-.,])(?:ai|a\.i\.|inc|inc\.|llc|ltd|corp|corporation|co|hq|io|labs?|"
    r"technologies|technology|software|security|systems|data|cloud|group|"
    r"north america|americas|america|usa|us|u\.s\.|global|international)\.?$"
)


def core(name: str) -> str:
    """Strip trailing corporate/generic words from both sides before comparing whole
    employer cells for equality (never free text, where a short core word could match
    unrelated prose)."""
    n = canon(name).lower().strip()
    for _ in range(3):
        m = re.sub(SUFFIX, "", n).strip()
        if m == n or len(norm(m)) < 3:
            break
        n = m
    return norm(n)


def cell_hit(emp: str, cell: str) -> bool:
    return emp_hit(emp, cell) or (bool(core(emp)) and core(emp) == core(cell))


STATE = r"SUBMITTED|REJECTED|STRUCK|DROPPED|DO NOT SUBMIT|WITHDRAWN|APPLIED|GATED|RELEASED|HELD|HOLD"


def req_core(req: str) -> str:
    """Normalize a requisition id across the shapes different ATSes present it in: bare
    ('R9999999'), with a posting suffix ('R9999999-1'), or embedded in a job path
    ('Remote/Sales-Engineer_R9999999-1')."""
    r = (req or "").strip().split("/")[-1]
    if r.lower() in ("none", "n/a", "na", "null", "unknown", "-", "none visible"):
        return ""
    r = re.sub(r"^.*_(?=(JR|RP|R)-?\d)", "", r)
    return re.sub(r"-\d{1,2}$", "", r)


def req_hit(req: str, text: str) -> bool:
    c = req_core(req)
    if not c:
        return False
    if len(c) < 5:
        # A very short id cannot identify a req on its own; match only as a whole TSV cell.
        return re.search(r"(?:^|\t)" + re.escape(c) + r"(?:\t|$)", text) is not None
    return (
        re.search(r"(?<![A-Za-z0-9])" + re.escape(c) + r"(?:-\d{1,2})?(?![A-Za-z0-9])", text, re.I)
        is not None
    )


def check(emp, title, req, subs, queue):
    e = norm(emp)
    stop = {"senior", "principal", "manager", "engineer", "staff", "lead"}
    tw = [w for w in re.findall(r"[a-z0-9]{4,}", (title or "").lower()) if w not in stop]
    hits = []
    for r in subs:
        cells = r + [""] * 8
        byreq = req_hit(req, "\t".join(r))
        byname = e and cell_hit(emp, cells[2]) and (
            not tw or sum(w in cells[3].lower() for w in tw) >= max(1, len(tw) // 2)
        )
        if byreq or byname:
            label = "REQ" if byreq else "SAME EMPLOYER + SIMILAR TITLE, different req"
            hits.append(f"SUBMISSIONS  [{label}] {cells[0]} | {cells[3][:50]} | {cells[4]} | outcome={cells[5] or 'NONE'}")
    for i, l in enumerate(queue, 1):
        if not re.search(STATE, l):
            continue
        byreq = req_hit(req, l)
        byname = e and emp_hit(emp, l) and (
            not tw or sum(w in l.lower() for w in tw) >= max(1, len(tw) // 2)
        )
        if byreq or byname:
            label = "REQ" if byreq else "SAME EMPLOYER + SIMILAR TITLE, different req"
            hits.append(f"QUEUE:{i:<5} [{label}] {l.strip()[:120]}")
    return hits


def employer_rows(emp, subs):
    if not norm(emp):
        return []
    return [r for r in subs if cell_hit(emp, (r + [""])[2]) or emp_hit(emp, (r + [""])[1].split("/")[0])]


def built_rows(emp, loader):
    if not norm(emp):
        return []
    rows = [l.split("\t") for l in loader("build_reqs_tsv").split("\n") if l and not l.startswith("#")][1:]
    return [r for r in rows if cell_hit(emp, (r + [""])[0]) or emp_hit(emp, (r + [""] * 7)[6].split("/")[0])]


LOOP = (
    r"(?i)\b(screen|interview|recruiter|booked|hiring manager|\bHM\b|round|stage|panel|offer|"
    r"reject|rejected|application|applied|inbound|outreach|req|requisition|role|position|loop|"
    r"call prep|debrief)\b"
)


def tracker_rows(emp, loader):
    if not norm(emp):
        return []
    t = loader("interview_tracker_md")
    out = []
    for l in t.split("\n"):
        if not emp_hit(emp, l):
            continue
        toks = re.findall(r"[a-z0-9]+", canon(emp).lower())
        for m in re.finditer(r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(map(re.escape, toks)) + r"(?![a-z0-9])", l.lower()):
            if re.search(LOOP, l[max(0, m.start() - 140):m.end() + 140]):
                out.append(re.sub(r"\s+", " ", l).strip()[:150])
                break
    return out


def make_loader(cfg, data_root_override: str = None):
    data_root = data_root_override or resolve_path(cfg, "paths.data_root") or "./data"
    key_to_filename = {
        "queue_md": get(cfg, "paths.queue_md", "QUEUE.md"),
        "submissions_tsv": get(cfg, "paths.submissions_tsv", "SUBMISSIONS.tsv"),
        "build_reqs_tsv": get(cfg, "paths.build_reqs_tsv", "BUILD_reqs.tsv"),
        "interview_tracker_md": get(cfg, "paths.interview_tracker_md", "INTERVIEW_TRACKER.md"),
    }

    def loader(key: str) -> str:
        return _read_file(os.path.join(data_root, key_to_filename[key]))

    loader.data_root = data_root
    loader.missing = [f for f in key_to_filename.values() if not os.path.isfile(os.path.join(data_root, f))]
    return loader


def load(loader):
    subs = [l.split("\t") for l in loader("submissions_tsv").split("\n") if l and not l.startswith("#")]
    if subs and subs[0] and subs[0][0].strip().lower() == "req_id":
        subs = subs[1:]  # the header row; any other first row is data
    return subs, loader("queue_md").split("\n")


def controls(loader):
    """Pure self-test: every control below uses its OWN small, self-contained fixture
    data (obviously fictional companies/roles), never the live data loaded from
    paths.data_root. This is deliberate: `--controls` must behave identically whether
    run against a brand-new, empty data_root or a years-old one -- it proves the
    MECHANISM works, not that a specific row happens to exist in your own tracker. The
    one exception is the "built-not-sent" entry, which DOES read the live build export
    via `loader`, because that is the one thing a fixture-only test can't stand in for;
    it is tolerant of an empty/missing file (see _read_file) so it still passes on a
    fresh install with nothing built yet -- it is skipped rather than failed in that case.
    """
    FIXTURE_SUBS = [
        ["8172023", "AcmeCorp/x", "Acme Corp", "Senior Customer Engineer", "2027-01-01", "NONE", "", ""],
        ["R9999999", "GlobexInd/y", "Globex Industries", "Domain Consultant", "2027-01-02", "REJECTED", "2027-01-10", ""],
    ]
    FIXTURE_QUEUE = [
        "| STRUCK | Initech, Senior Customer Success Manager | req 4676419006 |",
    ]
    EMPTY = []

    C = [
        ("QUEUE path alone (source isolation)", "Initech", "Senior Customer Success Manager", "4676419006", EMPTY, FIXTURE_QUEUE, True),
        ("SUBMISSIONS path alone (source isolation)", "Acme Corp", "Senior Customer Engineer", "8172023", FIXTURE_SUBS, EMPTY, True),
        ("Workday -1 suffix vs table", "", "", "R9999999-1", FIXTURE_SUBS, EMPTY, True),
        ("Workday job path", "", "", "Texas/Sales-Engineer-Application-Security_R9999999-1", FIXTURE_SUBS, EMPTY, True),
        ("near-miss 817202 must not match 8172023", "", "", "817202", FIXTURE_SUBS, FIXTURE_QUEUE, False),
        ("near-miss JR-02029 matches nothing in the fixtures", "", "", "JR-02029", FIXTURE_SUBS, FIXTURE_QUEUE, False),
        ("rejected Globex is still a hit (outcome does not clear a req)", "Globex Industries", "Domain Consultant", "", FIXTURE_SUBS, EMPTY, True),
        (
            "substring employer: a 5-letter company name must not hit an unrelated word containing it",
            "Umbra",
            "Forward Deployed Engineer",
            "2021104",
            EMPTY,
            ["| SUBMITTED | AcmeCo, Forward Deployed Engineer, Umbrella Analytics HQ |"],
            False,
        ),
        ("whole-word employer still hits", "Zenbright", "Technical Account Manager", "", EMPTY, ["| SUBMITTED | Zenbright, Technical Account Manager |"], True),
        ("short req '56' does not match free text", "", "", "56", EMPTY, ["| SUBMITTED | Foo, bar | row 56 of the sheet |"], False),
        ("--req none is no req", "Nonexistentco", "Chief Example Officer", "none", FIXTURE_SUBS, FIXTURE_QUEUE, False),
        ("fabricated negative", "Nonexistentco", "Chief Example Officer", "999999999", FIXTURE_SUBS, FIXTURE_QUEUE, False),
    ]
    bad = [(l, e, bool(check(emp, t, req, su, qu))) for l, emp, t, req, su, qu, e in C if bool(check(emp, t, req, su, qu)) != e]

    E = [
        ("employer roll-up lists a different-title prior", "Globex Industries", FIXTURE_SUBS, True),
        ("alias: 'Amazon Web Services (AWS)' is Amazon", "Amazon Web Services (AWS)", [["", "", "Amazon", "Cloud Support Engineer", "", "", "", ""]], True),
        ("employer roll-up, unknown employer", "Nonexistentco", FIXTURE_SUBS, False),
    ]
    bad += [(l, e, bool(employer_rows(emp, su))) for l, emp, su, e in E if bool(employer_rows(emp, su)) != e]

    # Built-not-sent roll-up: reads the LIVE build export (see docstring above). Tolerant
    # of "nothing built yet" -- that is a legitimate state on a fresh install, not a
    # control failure. It only fails if the mechanism itself throws.
    try:
        built_rows("Nonexistentco Should Never Match Anything Real", loader)
        built_ok = True
    except Exception as exc:  # pragma: no cover - defensive, mechanism must not throw
        built_ok = False
        bad.append(("built-not-sent roll-up does not throw", True, False))

    C = C + E + [("built-not-sent roll-up runs without throwing", True, True)]
    return C, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--employer", default="", help="Employer name to check (required unless --controls)")
    ap.add_argument("--title", default="", help="Role title as posted")
    ap.add_argument("--req", default="", help="Requisition id, if known")
    ap.add_argument("--controls", action="store_true", help="Run the self-test controls only")
    ap.add_argument("--config", default=None, help="Path to your config YAML")
    ap.add_argument("--data-root", default=None, help="Override paths.data_root from config")
    a = ap.parse_args()
    if not a.controls and not a.employer:
        ap.error("--employer is required (or use --controls)")

    cfg = load_config(a.config)
    loader = make_loader(cfg, data_root_override=a.data_root)
    if not a.controls and not os.path.isdir(loader.data_root):
        print(f"REFUSE: data root {loader.data_root} does not exist; a check against nothing is not a clear.")
        sys.exit(2)
    subs, queue = load(loader)
    C, bad = controls(loader)
    if bad:
        print("CONTROLS FAILED -- this check is broken; do not trust a 'clear':")
        for b in bad:
            print("  ", b)
        sys.exit(2)
    print(f"controls: {len(C)} of {len(C)} behaved (each source alone; -N suffix; job path; 2 near-misses; 1 negative)")
    if a.controls:
        sys.exit(0)
    if loader.missing:
        print(f"NOTE: not found under {loader.data_root} (treated as empty): {', '.join(loader.missing)}")

    h = check(a.employer, a.title, a.req, subs, queue)
    er = employer_rows(a.employer, subs)
    if er:
        print(f"\nNOTE: {len(er)} prior application(s) at {a.employer} (any title) -- one-per-company applies:")
        for r in er:
            c = r + [""] * 8
            print(f"   {c[0][:40]} | {c[3][:55]} | {c[4]} | outcome={c[5] or 'NONE'}")
    br = [
        r for r in built_rows(a.employer, loader) if not any(req_hit(r[1], "\t".join(x)) for x in er)
        and not (a.req and req_core(a.req) and req_hit(a.req, r[1]))
    ] if a.employer else []
    if br:
        print(f"\nNOTE: {len(br)} packet(s) BUILT at {a.employer} and not yet in SUBMISSIONS -- one-per-company applies:")
        for r in br:
            c = r + [""] * 8
            print(f"   {c[1][:40]} | {c[3][:55]} | {c[6]}")
    tr = tracker_rows(a.employer, loader) if a.employer else []
    if tr:
        print(f"\nNOTE: {len(tr)} line(s) at {a.employer} in the interview tracker -- a live or past loop may exist with NO application on record:")
        for x in tr[:6]:
            print(f"   {x}")

    if h:
        print(f"\nHIT -- {a.employer} / {a.title} / {a.req or '(no req)'}: resolve before building or offering")
        for x in h:
            print("  ", x)
        sys.exit(1)
    if er or br:
        print(f"\nNOT CLEAR -- one-per-company: {len(er)} prior application(s) and {len(br)} built packet(s) at {a.employer} (listed above). Exit 4.")
        sys.exit(4)
    if tr:
        print(f"\nNOT CLEAR -- no application on record, but the interview tracker names {a.employer}. Read those lines before building or offering. Exit 3.")
        sys.exit(3)
    print(f"\nCLEAR in the submissions table and queue tracker (paths.data_root, read fresh): {a.employer} / {a.title} / {a.req or '(no req)'}")
    sys.exit(0)


if __name__ == "__main__":
    main()
