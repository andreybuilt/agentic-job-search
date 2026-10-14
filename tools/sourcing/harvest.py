#!/usr/bin/env python3
"""
harvest.py -- unauthenticated LinkedIn guest-API job-card search harvest.

Pages the public "jobs-guest" search endpoint (no login, no cookie) for each
query in sourcing.linkedin_queries_csv, across a US-only and a remote-only pass,
and writes the deduped raw cards to <data-dir>/raw_cards.json for li_post.py
to screen and fetch JDs for.

!! IMPORTANT: run at most ONE of harvest.py / li_post.py against LinkedIn's
   guest API at a time, from at most one process or machine. The guest API is
   IP-rate-limited; running two in parallel burns through the budget faster
   and is more likely to get your egress IP rate-limited or blocked. !!

Config-driven (see ../../config.example.yaml):
  paths.data_root          -- directory holding dedupe_set.json (input) and
                               where raw_cards.json is written
  sourcing.linkedin_queries_csv -- comma-separated search phrases to run
                               (empty: the example DEFAULT_QUERIES below)

dedupe_set.json has the shape {"ids": [...], "companies": [...]} -- job ids
and normalized company names already seen in an earlier sweep, so this run
doesn't re-harvest them (dedup itself is done downstream in li_post.py; this
file only needs the "ids"/"companies" keys to exist, defaults to empty sets
if missing).
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, resolve_path, add_config_arg  # noqa: E402

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
}

# Generic example search terms for a customer-facing technical role. Replace
# via config (sourcing.linkedin_queries_csv) with your own target titles.
DEFAULT_QUERIES = [
    "customer success manager",
    "strategic customer success manager",
    "technical account manager",
    "enterprise customer success",
    "solutions engineer",
    "sales engineer",
    "solutions architect",
    "forward deployed engineer",
    "customer engineer",
    "manager solutions engineering",
    "manager customer success",
    "customer success engineer",
    "deployment strategist",
    "technical customer success manager",
    "field engineer",
]


def norm_company(c):
    if not c:
        return None
    c = c.strip().lower()
    c = re.sub(r"[^a-z0-9]+", "", c)
    return c or None


def fetch(url, tries=3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", errors="replace"), r.status
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < 2:
                    print(f"  429, sleeping 60s (attempt {attempt + 1})", file=sys.stderr)
                    time.sleep(60)
                    continue
                return None, 429
            print(f"  HTTPError {e.code} on {url}", file=sys.stderr)
            return None, e.code
        except Exception as e:
            print(f"  error {e} on {url}", file=sys.stderr)
            if attempt < tries - 1:
                time.sleep(5)
                continue
            return None, -1
    return None, -1


CARD_RE = re.compile(
    r'data-entity-urn="urn:li:jobPosting:(\d+)".*?'
    r'sr-only">\s*(.*?)\s*</span>.*?'
    r'base-search-card__subtitle">\s*<a[^>]*>\s*(.*?)\s*</a>.*?'
    r'job-search-card__location">\s*(.*?)\s*</span>',
    re.S,
)


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def parse_search(body):
    out = []
    for m in CARD_RE.finditer(body):
        jid, title, company, loc = m.groups()
        out.append({"id": jid, "title": strip_tags(title), "company": strip_tags(company), "location": strip_tags(loc)})
    return out


def search_query(kw, remote=False, max_start=70):
    results = []
    kw_enc = urllib.parse.quote(kw)
    for start in range(0, max_start, 10):  # guest API pages are 10 cards; a 25-step skips 10-24
        url = (
            f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
            f"?keywords={kw_enc}&location=United%20States&f_TPR=r259200&start={start}"
        )
        if remote:
            url += "&f_WT=2"
        body, status = fetch(url)
        time.sleep(4)
        if body is None:
            print(f"  search fetch failed status={status} url={url}", file=sys.stderr)
            break
        rows = parse_search(body)
        if not rows:
            break
        results.extend(rows)
        if len(rows) < 5:
            break
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=None, help="Directory with dedupe_set.json / for raw_cards.json output")
    add_config_arg(ap)
    args = ap.parse_args()

    cfg = load_config(args.config)
    data_dir = args.data_dir or resolve_path(cfg, "paths.data_root") or "."

    dedupe_path = os.path.join(data_dir, "dedupe_set.json")
    if os.path.isfile(dedupe_path):
        dedupe = json.load(open(dedupe_path))
    else:
        dedupe = {"ids": [], "companies": []}
    _known_ids = set(dedupe.get("ids", []))
    _known_companies = set(dedupe.get("companies", []))

    queries_csv = get(cfg, "sourcing.linkedin_queries_csv", None)
    queries = [q.strip() for q in queries_csv.split(",")] if queries_csv else DEFAULT_QUERIES

    all_cards = {}
    for kw in queries:
        for remote in (False, True):
            tag = f"{kw} [remote]" if remote else kw
            print(f"query: {tag}", file=sys.stderr)
            rows = search_query(kw, remote=remote, max_start=70)
            print(f"  got {len(rows)} cards", file=sys.stderr)
            for r in rows:
                r["_query"] = tag
                all_cards.setdefault(r["id"], r)

    print(f"TOTAL unique cards across all queries: {len(all_cards)}", file=sys.stderr)
    os.makedirs(data_dir, exist_ok=True)
    out_path = os.path.join(data_dir, "raw_cards.json")
    json.dump(list(all_cards.values()), open(out_path, "w"), indent=1)
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
