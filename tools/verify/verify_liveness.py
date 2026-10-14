#!/usr/bin/env python3
"""
verify_liveness.py -- multi-ATS liveness re-check.

Given a list of (name, kind, arg) entries describing postings you've applied to or
are tracking, re-fetches each one from its native ATS/page and reports whether it is
still live, what location/compensation language the page itself shows now, and pulls
out any sentence matching common hard-requirement patterns (years of experience,
location/residency requirements, clearance, travel, pay figures) so you can spot a
requirement that changed since you applied.

kind is one of: page | wd (Workday) | gh (Greenhouse) | ashby | lever
arg shape per kind:
  page   -- a URL to fetch and scan as plain text
  wd     -- "<workday-host>|<site>|<job-path>"
  gh     -- "<board-token>|<job-id>"
  ashby  -- "<board-token>|<job-id>"
  lever  -- "<board-token>|<posting-id>"

⚠️ The original version of this tool shipped a hardcoded table of real companies and
real requisition IDs from one person's job search. That is personal/confidential data
and has been removed entirely. Supply your own tracked postings via --entries-file (a
TSV: name<TAB>kind<TAB>arg, one per line, '#' comments allowed).

This tool makes LIVE network requests to the ATS hosts in your entries file. --demo runs
three fictional entries (Acme Corp, Globex, Initech): the board tokens are invented, so
expect each to report an error or a 404. It still contacts the real Greenhouse and Ashby
APIs to get that answer. It is a smoke test of the plumbing, not an offline demo.

Usage:
  python3 verify_liveness.py --entries-file my_tracked_postings.tsv
  python3 verify_liveness.py --demo   # three fictional entries; makes real requests
"""
import argparse
import html
import json
import re
import sys
import urllib.request

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/152.0 Safari/537.36",
    "Accept": "application/json,text/html",
}

# 2-3 obviously fake example entries -- never real company names or req ids.
# These exist only so the tool is runnable without a real tracked-postings file.
DEMO_ENTRIES = [
    ("Acme Corp Forward Deployed Engineer", "page", "https://careers.acme-corp.example/jobs/0000001"),
    ("Globex Regional Sales Engineer", "gh", "globex-example|0000002"),
    ("Initech Technical Account Manager", "ashby", "initech-example|00000000-0000-0000-0000-000000000003"),
]

REQUIREMENT_PATTERN = re.compile(
    r"[^.]{0,90}(\d+\+? ?(?:-|–|to)? ?\d*\+? years?[^.]{0,80}|must (?:be|reside|live)[^.]{0,70}|"
    r"located in[^.]{0,60}|based (?:in|out of)[^.]{0,60}|time ?zone[^.]{0,40}|travel[^.]{0,40}|"
    r"clearance[^.]{0,30}|\$\s?\d{2,3}[,.]?\d{0,3}[^.]{0,60})",
    re.I,
)


def get(u, data=None, ct=None):
    h = dict(UA)
    if ct:
        h["Content-Type"] = ct
    return urllib.request.urlopen(urllib.request.Request(u, data=data, headers=h), timeout=30).read().decode(
        "utf-8", "replace"
    )


def txt(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(s or ""))))


def check_one(name, kind, arg):
    """Returns (live_state, location, body_text) or raises on a hard transport error."""
    if kind == "gh":
        tok, jid = arg.split("|")
        j = json.loads(get(f"https://boards-api.greenhouse.io/v1/boards/{tok}/jobs/{jid}?pay_transparency=true"))
        body = txt(j.get("content", ""))
        loc = j["location"]["name"]
        live = "LIVE"
    elif kind == "ashby":
        tok, jid = arg.split("|")
        d = json.loads(get(f"https://api.ashbyhq.com/posting-api/job-board/{tok}?includeCompensation=true"))
        m = [x for x in d["jobs"] if x["id"] == jid]
        live = "LIVE" if m else "NOT ON BOARD"
        j = m[0] if m else {}
        body = j.get("descriptionPlain", "")
        loc = " | ".join([j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations", []) or []])
        loc += " remote" if j.get("isRemote") else ""
        body += " COMP: " + " ; ".join(t.get("tierSummary", "") for t in (j.get("compensation") or {}).get("compensationTiers", []) or [])
    elif kind == "lever":
        tok, jid = arg.split("|")
        j = json.loads(get(f"https://api.lever.co/v0/postings/{tok}/{jid}"))
        live = "LIVE"
        loc = str(j.get("categories", {}).get("location")) + " " + str(j.get("workplaceType"))
        body = (
            j.get("descriptionPlain", "")
            + " "
            + " ".join(txt(l.get("content", "")) for l in j.get("lists", []))
            + " "
            + (j.get("additionalPlain") or "")
        )
    elif kind == "wd":
        host, site, path = arg.split("|")
        ten = host.split(".")[0]
        j = json.loads(get(f"https://{host}/wday/cxs/{ten}/{site}{path}"))
        i = j["jobPostingInfo"]
        live = "LIVE" if i.get("canApply", True) else "CLOSED"
        loc = i.get("location", "") + " + " + "; ".join(i.get("additionalLocations", []) or [])
        body = txt(i.get("jobDescription", ""))
    else:  # page
        s = get(arg)
        body = txt(s)
        loc = "(page)"
        live = "HTTP200 len=%d" % len(body)
    return live, loc, body


def run(entries):
    for name, kind, arg in entries:
        try:
            live, loc, body = check_one(name, kind, arg)
        except Exception as e:
            print(f"## {name}: ERR {str(e)[:80]}")
            continue
        hits = [m.group(0).strip() for m in REQUIREMENT_PATTERN.finditer(body)]
        print(f"## {name} | {live} | loc: {loc[:140]}")
        for h in hits[:7]:
            print("   -", h[:170])


def load_entries_file(path):
    out = []
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 3:
            sys.exit(f"[verify_liveness] malformed line (expected name\\tkind\\targ): {line!r}")
        out.append(tuple(parts))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--entries-file", default=None, help="TSV of name/kind/arg rows to check (see module docstring)")
    ap.add_argument("--demo", action="store_true",
                    help="Run 3 fictional entries (makes real requests; expect errors or 404s)")
    args = ap.parse_args()

    if args.demo:
        print("[verify_liveness] --demo: three fictional entries; real requests, expect errors.\n", file=sys.stderr)
        run(DEMO_ENTRIES)
        return 0
    if not args.entries_file:
        ap.print_usage(sys.stderr)
        print("verify_liveness.py: error: give --entries-file FILE (or --demo)", file=sys.stderr)
        return 2
    run(load_entries_file(args.entries_file))
    return 0


if __name__ == "__main__":
    sys.exit(main())
