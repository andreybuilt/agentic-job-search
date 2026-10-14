#!/usr/bin/env python3
"""
build_submissions.py -- publish SUBMISSIONS.tsv, the read-only submission-state view
the Build stage reads before offering or rebuilding anything.

Usage: python3 build_submissions.py [<data-root>] [--config PATH]
       <data-root> defaults to paths.data_root from your config.

Output contract (every tool that reads this file honors it):
    req_id  packet_dir  employer  role  submitted_at  outcome  outcome_at  channel

Join on (req_id, packet_dir), and NEVER on req_id alone -- a build export can carry
duplicate req_ids for a superseded pair (a packet rebuilt under a corrected title/req).

`outcome` is the column that matters, not `submitted_at` alone: a submission that was
later rejected is not "in flight, leave it" just because it has a submitted_at date.

Reads (under <data-root>; names come from the paths.* keys in your config; each optional).
A first row whose first cell is a column name (company, employer, req_id, ...) is treated
as a header and skipped. Any other first row is data.
    paths.build_reqs_tsv        company req_id ats title built_utc url packet_dir source flag ...
                                (written by tools/sourcing/build_reqs.py)
    paths.mailbox_ledger_tsv    employer role req ats submitted_at
    paths.outcomes_raw_tsv      employer role outcome outcome_at
    paths.overrides_ledger_tsv  match_req match_employer match_role match_submitted_at
                                set_req set_packet_dir set_role
    paths.direct_ledger_tsv     req_id packet_dir employer role submitted_at ats evidence
                                (written by record_send.py, with a header row)
Writes: paths.submissions_tsv
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, resolve_path, add_config_arg  # noqa: E402

HEADER_FIRST_CELLS = {"company", "employer", "req", "req_id", "match_req", "emp"}


def rows(path, skip_comments=True):
    """Data rows of a TSV. Blank and '#' lines are skipped, and the first row is skipped only
    when it is a header (its first cell is a column name). Never drops a data row."""
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if skip_comments and (line.startswith("#") or not line.strip()):
                continue
            out.append(line.rstrip("\n").split("\t"))
    if out and out[0] and out[0][0].strip().lower() in HEADER_FIRST_CELLS:
        out = out[1:]
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# Generic corporate-suffix stripping so "Acme Corp" and "Acme" (or "Acme, Inc.") normalize
# to the same key -- no hardcoded list of specific real companies, unlike an alias dict.
SUFFIX = (
    r"(?:\s+|[-.,])(?:ai|a\.i\.|inc|inc\.|llc|ltd|corp|corporation|co|hq|io|labs?|"
    r"technologies|technology|software|security|systems|data|cloud|group|"
    r"north america|americas|america|usa|us|u\.s\.|global|international)\.?$"
)


def ekey(e):
    n = (e or "").lower().strip()
    for _ in range(3):
        m = re.sub(SUFFIX, "", n).strip()
        if m == n or len(norm(m)) < 3:
            break
        n = m
    return norm(n)


RANK = {"OFFER": 4, "INTERVIEW": 3, "ASSESSMENT": 2, "OTHER": 1, "REJECTED": 0}


def better(new_, old_):
    if old_ is None:
        return True
    (no, na), (oo, oa) = new_, old_
    if na != oa:
        return na > oa
    return RANK.get(no, 0) > RANK.get(oo, 0)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_root", nargs="?", default=None, help="Data root (default: paths.data_root from config)")
    add_config_arg(ap)
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    root = a.data_root or resolve_path(cfg, "paths.data_root")
    if not root or not os.path.isdir(root):
        sys.exit(f"[build_submissions] data root does not exist: {root}")

    def tracker(key, default):
        return os.path.join(root, get(cfg, key, default) or default)

    build = rows(tracker("paths.build_reqs_tsv", "BUILD_reqs.tsv"))
    mail = rows(tracker("paths.mailbox_ledger_tsv", "LEDGER_mailbox.tsv"))
    outc = rows(tracker("paths.outcomes_raw_tsv", "OUTCOMES_raw.tsv"))

    by_er, by_e = {}, {}
    for r in build:
        if len(r) < 9:
            continue
        company, req, title, pdir, flag = r[0], r[1], r[3], r[6], (r[8] if len(r) > 8 else "")
        if "SUPERSEDED" in flag:
            continue  # never point a reader at a dead row
        by_er.setdefault((ekey(company), norm(title)), (req, pdir))
        by_e.setdefault(ekey(company), []).append((norm(title), req, pdir))

    # PRECEDENCE MATTERS for outcomes: an automated rejection can be followed hours later
    # by a human-initiated interview request for the same role. Taking the first row seen
    # would publish REJECTED for what is actually a live process. Later date wins; on a
    # tie, a live state beats a rejection.
    o_er, o_e = {}, {}
    for r in outc:
        if len(r) < 4:
            continue
        emp, role, out, at = r[0], r[1], r[2], r[3]
        k = (ekey(emp), norm(role))
        if better((out, at), o_er.get(k)):
            o_er[k] = (out, at)
        o_e.setdefault(ekey(emp), []).append((norm(role), out, at))

    out_rows = []
    for r in mail:
        if len(r) < 5:
            continue
        emp, role, req, ats, sub = r[0], r[1], r[2], r[3], r[4]
        ek, rk = ekey(emp), norm(role)
        pdir = ""

        def find(ek, rk):
            hit = by_er.get((ek, rk))
            if hit:
                return hit
            # Titles can differ by a trailing qualifier between a mail ack and the build
            # export ("...Platform Role (Remote - US/Canada)" vs "...Platform Role").
            # Prefix-match only when the shorter title is long enough that a short title
            # collision is unlikely.
            best = None
            for t, rq, pd in by_e.get(ek, []):
                if not t or not rk:
                    continue
                a, b = (rk, t) if len(rk) <= len(t) else (t, rk)
                if len(a) >= 20 and b.startswith(a):
                    if best and best[0] != rq:
                        return None  # ambiguous: refuse rather than guess
                    best = (rq, pd)
            return best

        if not req or req in ("NONE", "-", ""):
            hit = find(ek, rk)
            req, pdir = hit if hit else ("UNKNOWN", "")
        else:
            hit = find(ek, rk)
            if hit:
                pdir = hit[1]
        if not pdir:
            for t, rq, pd in by_e.get(ek, []):
                if rq == req:
                    pdir = pd
                    break

        outcome, oat = o_er.get((ek, rk), ("", ""))
        if not outcome:
            best = None
            for t, o, a in o_e.get(ek, []):
                if not t or not rk:
                    continue
                x, y = (rk, t) if len(rk) <= len(t) else (t, rk)
                if len(x) >= 20 and y.startswith(x):
                    if better((o, a), best):
                        best = (o, a)
            if best:
                outcome, oat = best
        out_rows.append([req or "UNKNOWN", pdir or "UNKNOWN", emp, role, sub, outcome or "NONE", oat or "", ats or ""])

    # Manual corrections to a mail-derived row (a req the ack never named, a packet_dir on
    # an old path, a role the ack did not state). Match by req when given, else by
    # employer + role + submitted_at exactly.
    for o in rows(tracker("paths.overrides_ledger_tsv", "LEDGER_overrides.tsv")):
        if len(o) < 7:
            continue
        mreq, memp, mrole, msub, sreq, spd, srole = o[:7]
        for r in out_rows:
            hit = (mreq and r[0] == mreq) or (
                not mreq and ekey(r[2]) == ekey(memp) and norm(r[3]) == norm(mrole) and r[4] == msub
            )
            if hit:
                if sreq:
                    r[0] = sreq
                if spd:
                    r[1] = spd
                if srole:
                    r[3] = srole
                    if r[5] == "NONE":
                        o_ = o_er.get((ekey(r[2]), norm(srole)))
                        if o_:
                            r[5], r[6] = o_

    # Destination-confirmed submissions a mail sweep cannot see at all (some ATSes send no
    # ack) or that postdate the last sweep. Without this, those submissions are simply
    # absent from this view -- and absence from this file reads as "not submitted".
    seen = {r[0] for r in out_rows if r[0] != "UNKNOWN"}
    for r in rows(tracker("paths.direct_ledger_tsv", "LEDGER_direct.tsv")):
        if len(r) < 6:
            continue
        req, pdir, emp, role, sub, ats = r[:6]
        if req != "UNKNOWN" and req in seen:
            continue
        if req == "UNKNOWN" and any(ekey(o[2]) == ekey(emp) and norm(o[3]) == norm(role) for o in out_rows):
            continue
        ek, rk = ekey(emp), norm(role)
        cands = [
            o
            for o in out_rows
            if o[0] == "UNKNOWN"
            and ekey(o[2]) == ek
            and (
                norm(o[3]) == rk
                or (
                    min(len(norm(o[3])), len(rk)) >= 20
                    and (norm(o[3]).startswith(rk) or rk.startswith(norm(o[3])))
                )
            )
        ]
        if len(cands) == 1:
            cands[0][0] = req
            if cands[0][1] == "UNKNOWN":
                cands[0][1] = pdir
            seen.add(req)
            continue
        outcome, oat = o_er.get((ek, rk), ("", ""))
        if not outcome:
            best = None
            for t, o, a in o_e.get(ek, []):
                x, y = (rk, t) if len(rk) <= len(t) else (t, rk)
                if len(x) >= 20 and x in y and better((o, a), best):
                    best = (o, a)
            if best:
                outcome, oat = best
        out_rows.append([req, pdir, emp, role, sub, outcome or "NONE", oat or "", ats])
        if req != "UNKNOWN":
            seen.add(req)

    out_rows.sort(key=lambda x: (x[2].lower(), x[3].lower()))
    dest = tracker("paths.submissions_tsv", "SUBMISSIONS.tsv")
    root_real = os.path.realpath(root)
    dest_real = os.path.realpath(dest)
    if os.path.commonpath([root_real, dest_real]) != root_real or dest_real == root_real:
        sys.exit(f"[build_submissions] REFUSE: paths.submissions_tsv resolves outside the data root: {dest_real}")
    with open(dest, "w", encoding="utf-8") as f:
        f.write("# Read-only submission state, published for the Build stage. Regenerate; never hand-edit.\n")
        f.write("# JOIN ON (req_id, packet_dir) -- never req_id alone.\n")
        f.write("# outcome NONE = submitted, no reply yet. It does NOT mean 'safe to rebuild'.\n")
        f.write("# req_id/packet_dir UNKNOWN = submitted but never carried a req; match on employer+role.\n")
        f.write("# Generated by tools/verify/build_submissions.py\n")
        f.write("req_id\tpacket_dir\temployer\trole\tsubmitted_at\toutcome\toutcome_at\tchannel\n")
        for r in out_rows:
            f.write("\t".join(r) + "\n")

    known = sum(1 for r in out_rows if r[0] != "UNKNOWN")
    withpd = sum(1 for r in out_rows if r[1] != "UNKNOWN")
    witho = sum(1 for r in out_rows if r[5] != "NONE")
    print(f"rows={len(out_rows)}  req_id known={known}  packet_dir known={withpd}  outcome known={witho}")
    print(f"wrote {dest}")


if __name__ == "__main__":
    main(sys.argv[1:])
