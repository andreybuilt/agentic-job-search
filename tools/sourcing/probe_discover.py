#!/usr/bin/env python3
"""
probe_discover.py -- probe Greenhouse/Ashby/Lever for company-slug guesses
(the "is this company on any of the three ATS, under what slug" question),
rate-limited to <=4 requests/sec total across all three APIs. Writes
boards_probed.txt (append log) and probe_jobs.json (full job payloads, for
filter_discover.py to screen).

Config-driven (see ../../config.example.yaml):
  paths.data_root -- directory holding candidates.tsv (input) and where
                      boards_probed.txt / probe_jobs.json are written

Usage:
  python3 probe_discover.py [--config path] [--data-dir DIR]

Input: <data-dir>/candidates.tsv with columns: company_name, <anything>, comma-separated-slug-guesses, ...
(column 0 = display name, column 2 = comma-separated slug candidates -- matches the
shape this toolkit's discovery workflow produces upstream).
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, resolve_path, add_config_arg  # noqa: E402
from ats_common import UA, strip_html as strip  # noqa: E402

lock = threading.Lock()
last = [0.0]


def throttle():
    with lock:
        w = last[0] + 0.27 - time.time()
        if w > 0:
            time.sleep(w)
        last[0] = time.time()


def get_json(u):
    for a in range(4):
        throttle()
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (a + 1))
                continue
            if e.code in (404, 400):
                return None
            return None
        except Exception:
            time.sleep(1)
    return "ERR"


def probe(slug, name):
    res = {}
    jobs = []
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
    gname = d.get("name") if isinstance(d, dict) else None
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if isinstance(d, dict):
        js = d.get("jobs", [])
        res["gh"] = len(js)
        for j in js:
            jobs.append(
                dict(
                    ats="gh", slug=slug, req=str(j["id"]), title=j["title"],
                    loc=(j.get("location") or {}).get("name", ""), url=j.get("absolute_url", ""),
                    comp="", remote=False, content=strip(j.get("content"))[:6000],
                )
            )
    else:
        res["gh"] = 0 if d is None else "ERR"
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    if isinstance(d, dict):
        js = [j for j in d.get("jobs", []) if j.get("isListed", True)]
        res["ash"] = len(js)
        for j in js:
            tiers = [
                t.get("tierSummary") or t.get("title") or ""
                for t in ((j.get("compensation") or {}).get("compensationTiers") or [])
            ]
            locs = [j.get("location", "")] + [x.get("location", "") for x in (j.get("secondaryLocations") or [])]
            jobs.append(
                dict(
                    ats="ash", slug=slug, req=j["id"], title=j["title"], loc=" | ".join(l for l in locs if l),
                    url=j.get("jobUrl", ""), comp=" ; ".join(t for t in tiers if t), remote=bool(j.get("isRemote")),
                    wt=j.get("workplaceType"), content=strip(j.get("descriptionHtml"))[:6000],
                )
            )
    else:
        res["ash"] = 0 if d is None else "ERR"
    d = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if isinstance(d, list):
        res["lev"] = len(d)
        for j in d:
            c = j.get("categories", {})
            sr = j.get("salaryRange") or {}
            jobs.append(
                dict(
                    ats="lev", slug=slug, req=j["id"], title=j["text"],
                    loc=" | ".join(x for x in [c.get("location", "")] + (c.get("allLocations") or []) if x),
                    url=j.get("hostedUrl", ""),
                    comp=(f"{sr.get('currency', '')} {sr.get('min', '')}-{sr.get('max', '')}" if sr else ""),
                    remote=j.get("workplaceType") == "remote",
                    content=(j.get("descriptionPlain") or strip(j.get("description")))[:6000],
                )
            )
    else:
        res["lev"] = 0 if d is None else "ERR"
    tok = re.sub(r"[^a-z0-9 ]", "", name.lower()).split()
    key = tok[0] if tok else ""

    def mentions(j):
        return bool(key) and key in (j["content"] + " " + j["url"]).lower()

    nj = len(jobs)
    nm = sum(1 for j in jobs if mentions(j))
    return dict(slug=slug, company=name, res=res, gname=gname, njobs=nj, name_mentions=nm, jobs=jobs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=None, help="Directory with candidates.tsv (default: paths.data_root from config)")
    add_config_arg(ap)
    args = ap.parse_args()

    cfg = load_config(args.config)
    data_dir = args.data_dir or resolve_path(cfg, "paths.data_root") or "."

    candidates_path = os.path.join(data_dir, "candidates.tsv")
    if not os.path.isfile(candidates_path):
        sys.exit(f"[probe_discover] candidates.tsv not found at {candidates_path}")

    rows = [l.rstrip("\n").split("\t") for l in open(candidates_path)][1:]
    outf = open(os.path.join(data_dir, "boards_probed.txt"), "a")
    tasks = [(s, r[0]) for r in rows for s in r[2].split(",")]

    def run(t):
        p = probe(*t)
        line = (
            f"{p['slug']}\tcompany={p['company']}\tgh:{p['res']['gh']},ash:{p['res']['ash']},lev:{p['res']['lev']}\t"
            f"gh_board_name={p['gname'] or '-'}\tjobs={p['njobs']}\tname_in_jd={p['name_mentions']}"
        )
        with lock:
            outf.write(line + "\n")
            outf.flush()
        return p

    with cf.ThreadPoolExecutor(3) as ex:
        out = list(ex.map(run, tasks))

    json.dump(out, open(os.path.join(data_dir, "probe_jobs.json"), "w"))
    live = [p for p in out if p["njobs"]]
    print("slugs", len(out), "with jobs", len(live))


if __name__ == "__main__":
    main()
