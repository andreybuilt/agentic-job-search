#!/usr/bin/env python3
"""
sweep.py -- lead sweep over public ATS boards (Greenhouse, Ashby, Lever).

Each company slug is probed against all three ATS APIs; a 404 means wrong ATS
or wrong slug for that company, never "no jobs". Output: a candidates.tsv of
reqs that pass a TITLE screen and a LOCATION screen on the data the board
API *displays*. This is a screen, not a decision -- the JD read later decides
what a role actually *requires*.

Config-driven (see ../../config.example.yaml, loaded via tools/common/config.py):
  sourcing.title_include_regex   -- regex: titles that pass (what you're searching for)
  sourcing.title_exclude_regex   -- regex: titles that get dropped even if included
  sourcing.target_metro_regex    -- regex: your home metro (e.g. your city/state aliases)
  sourcing.target_state_abbr     -- your state's two-letter abbreviation (used to avoid
                                     a false "remote-in-another-state" screen when your
                                     own state is tagged as a specific-state remote)

Each key has an example default in ats_common.py (field and solutions roles, a
fictional metro). Set your own in config.yaml.

Usage:
  python3 sweep.py <slugs_file> [--config path] [--out-dir DIR]

Makes live requests to the public Greenhouse, Ashby and Lever APIs.
Exit codes: 0 = done, 3 = at least one slug could not be checked because of a network or
server error (reported separately from "no board", which is a 404 on every ATS).
boards.txt columns: slug, status (board | no-board | error), detail.

<slugs_file> is a plain text file, one company-board slug per line, '#' comments allowed.
Writes boards.txt and candidates.tsv into --out-dir (default: current directory).
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
import concurrent.futures as cf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tools.common.config import load_config, get, add_config_arg  # noqa: E402
from ats_common import (  # noqa: E402
    UA, DEFAULT_TITLE_IN, DEFAULT_TITLE_OUT, DEFAULT_TARGET_METRO, DEFAULT_TARGET_STATE_ABBR, make_loc_ok,
)


class BoardError(Exception):
    """The request did not get an answer about the board (network, timeout, 5xx, 403...)."""


def get_json(u):
    """Fetch JSON. Returns None for HTTP 404 (no board under this slug on this ATS) and
    raises BoardError for anything that is not an answer about the board."""
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise BoardError(f"HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise BoardError(f"{type(e).__name__}: {getattr(e, 'reason', e)}") from e


def gh(s):
    """Greenhouse board rows, or None when the board does not exist (404)."""
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs")
    if d is None:
        return None
    out = []
    for j in d.get("jobs", []):
        locs = [j.get("location", {}).get("name", "")] + [o.get("name", "") for o in j.get("offices", [])]
        out.append(dict(
            ats="greenhouse", slug=s, req=str(j["id"]), title=j["title"], locs=locs,
            remote=bool(re.search("remote", " ".join(locs), re.I)), comp="", url=j.get("absolute_url", ""),
        ))
    return out


def ash(s):
    """Ashby board rows, or None when the board does not exist (404)."""
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true")
    if d is None:
        return None
    out = []
    for j in d.get("jobs", []):
        if not j.get("isListed", True):
            continue
        locs = [j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations", []) or []]
        comp = []
        for t in (j.get("compensation") or {}).get("compensationTiers", []) or []:
            comp.append(t.get("tierSummary", "") or t.get("title", ""))
        out.append(dict(
            ats="ashby", slug=s, req=j["id"], title=j["title"], locs=locs, remote=bool(j.get("isRemote")),
            comp=" ; ".join(c for c in comp if c), url=j.get("jobUrl", ""),
        ))
    return out


def lev(s):
    """Lever board rows, or None when the board does not exist (404)."""
    d = get_json(f"https://api.lever.co/v0/postings/{s}?mode=json")
    if d is None:
        return None
    out = []
    for j in d:
        c = j.get("categories", {})
        locs = [c.get("location", "")] + (c.get("allLocations") or [])
        sr = j.get("salaryRange") or {}
        # An empty salaryRange is NOT "no band" -- Lever often shows pay only on the
        # hosted page. Never let a screener read '' as "not posted"; the JD-fetch
        # step reads the hosted page for any req that goes forward.
        comp = (
            f"{sr.get('currency', '')} {sr.get('min', '')}-{sr.get('max', '')}"
            if sr
            else 'UNREAD: Lever API carries no pay; read hostedUrl before recording "not posted"'
        )
        out.append(dict(
            ats="lever", slug=s, req=j["id"], title=j["text"], locs=locs,
            remote=j.get("workplaceType") == "remote" or "remote" in " ".join(locs).lower(),
            comp=comp, url=j.get("hostedUrl", ""),
        ))
    return out


def probe(s, readers=None):
    """Probe one slug on every ATS. Returns (slug, status, found, rows, errors). status is
    "board" (at least one ATS answered with a board), "no-board" (every ATS answered 404),
    or "error" (no board found AND at least one ATS could not be reached, so the slug is
    unknown, not absent)."""
    readers = readers or (gh, ash, lev)
    rows, found, errors = [], [], []
    for f in readers:
        try:
            got = f(s)
        except BoardError as e:
            errors.append(f"{f.__name__}: {e}")
            continue
        if got is not None:
            found.append(f"{f.__name__}:{len(got)}")
            rows += got
    if found:
        status = "board"
    elif errors:
        status = "error"
    else:
        status = "no-board"
    return s, status, found, rows, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs_file", help="Text file of company-board slugs, one per line")
    ap.add_argument("--out-dir", default=".", help="Directory to write boards.txt/candidates.tsv into")
    add_config_arg(ap)
    args = ap.parse_args()

    cfg = load_config(args.config)
    title_in = re.compile(get(cfg, "sourcing.title_include_regex", None) or DEFAULT_TITLE_IN, re.I)
    title_out = re.compile(get(cfg, "sourcing.title_exclude_regex", None) or DEFAULT_TITLE_OUT, re.I)
    target_metro = get(cfg, "sourcing.target_metro_regex", None) or DEFAULT_TARGET_METRO
    target_state = get(cfg, "sourcing.target_state_abbr", None) or DEFAULT_TARGET_STATE_ABBR
    loc_ok = make_loc_ok(target_metro, target_state)

    if not os.path.isfile(args.slugs_file):
        sys.exit(f"[sweep] slugs file not found: {args.slugs_file}")

    with open(args.slugs_file, encoding="utf-8") as f:
        slugs = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    found_rows = {}
    status = {}
    with cf.ThreadPoolExecutor(8) as ex:
        for s, st, hit, rows, errors in ex.map(probe, slugs):
            status[s] = (st, hit, errors)
            for r in rows:
                if not title_in.search(r["title"]) or title_out.search(r["title"]):
                    continue
                g = loc_ok(r["locs"], r["remote"])
                if not g:
                    continue
                r["gate0"] = g
                found_rows[(r["ats"], r["req"])] = r

    os.makedirs(args.out_dir, exist_ok=True)
    with open(os.path.join(args.out_dir, "boards.txt"), "w", encoding="utf-8") as f:
        for s, (st, hit, errors) in sorted(status.items()):
            if st == "board":
                detail = ",".join(hit)
            elif st == "no-board":
                detail = "NO BOARD (404 on every ATS)"
            else:
                detail = "ERROR: " + "; ".join(errors)
            f.write(f"{s}\t{st}\t{detail}\n")
    with open(os.path.join(args.out_dir, "candidates.tsv"), "w", encoding="utf-8") as f:
        f.write("employer_slug\tats\treq\ttitle\tgate0\tlocations\tcomp\turl\n")
        for r in sorted(found_rows.values(), key=lambda r: (r["slug"], r["title"])):
            f.write(
                "\t".join(
                    [
                        r["slug"], r["ats"], r["req"], r["title"], r["gate0"],
                        " | ".join(x for x in r["locs"] if x)[:160], r["comp"][:160], r["url"],
                    ]
                )
                + "\n"
            )
    n = {k: sum(1 for v in status.values() if v[0] == k) for k in ("board", "no-board", "error")}
    print(f"slugs {len(slugs)}  boards found {n['board']}  no board (404) {n['no-board']}  "
          f"network/other errors {n['error']}  candidates {len(found_rows)}")
    if n["error"]:
        for s, (st, _, errors) in sorted(status.items()):
            if st == "error":
                print(f"  ERROR {s}: {'; '.join(errors)}", file=sys.stderr)
        print("An ERROR is not a missing board: the request never got an answer. Re-run before "
              "concluding anything about those slugs.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
