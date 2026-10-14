#!/usr/bin/env python3
"""
li_post.py -- LinkedIn post-harvest, two stages.

Stage A (cards only, no outbound traffic): drops cards whose id was already
seen in an earlier sweep, whose company you've already applied to or built a
packet for, whose location is clearly non-US, or whose title is off-track or
junior.

Stage B fetches each survivor's JD ONE AT A TIME (LI_DELAY env var, default
6s -- keep this slow; see the rate-limit warning below), then applies body
rules: drops a listing whose office is somewhere specific without a US-remote
claim, and drops anything whose stated comp band tops out under your floor.
Agency postings are TAGGED, never dropped silently. Every drop is logged with
the text that decided it, into dropped.tsv.

!! IMPORTANT: run at most ONE of harvest.py / li_post.py against LinkedIn's
   guest API at a time, from at most one process or machine. It is IP-rate-limited. !!

Config-driven (see ../../config.example.yaml):
  paths.data_root        -- directory holding raw_cards.json, dedupe_set.json
                             and where jd/, dropped.tsv, survivors.json land
  paths.submissions_tsv  -- your submissions view, relative to data_root
  paths.build_reqs_tsv   -- your built-packet index, relative to data_root
  sourcing.min_comp_band  -- drop a listing whose stated max comp is under this (0 = keep all)
  sourcing.title_include_regex -- same key sweep.py / harvest.py use

Env: LI_DELAY (seconds between JD fetches, default 6)

Usage:
  python3 li_post.py [--config path] [--data-dir DIR] [--dry]
"""
import argparse
import collections
import html as H
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, resolve_path, add_config_arg  # noqa: E402
from ats_common import DEFAULT_TITLE_IN  # noqa: E402

DELAY = float(os.environ.get("LI_DELAY", "6"))
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_ALIASES = {
    "amazonwebservicesaws": "amazon", "amazonwebservices": "amazon", "aws": "amazon",
    "googlecloud": "google", "microsoftazure": "microsoft",
}

NONUS = (
    r"\b(canada|toronto|vancouver|london|united kingdom|\buk\b|emea|europe|germany|france|india|"
    r"bangalore|bengaluru|australia|sydney|singapore|japan|tokyo|brazil|mexico|israel|tel aviv|"
    r"ireland|dublin|netherlands|amsterdam|spain|poland|apac|apj|latam|korea|dubai|uae|saudi|"
    r"riyadh|berlin|paris|madrid|philippines|manila|puerto rico)\b"
)
OFFICE_ELSEWHERE = (
    r"(?i)\b(hybrid|on-?site|in[- ]office|in the office)\b[^.]{0,80}\b(san francisco|new york|nyc|chicago|"
    r"austin|boston|denver|atlanta|los angeles|dallas|miami|washington,? d\.?c)"
)
REMOTE_US = r"(?i)\b(us|u\.s\.|united states)[- ]remote\b|\bremote[,( -]+(us|u\.s\.|usa|united states)\b|100% remote"
JUNIOR = r"(?i)\b(associate|junior|jr\.?|intern|entry[- ]level|coordinator|specialist i\b|analyst)\b"
NOTTRACK = (
    r"(?i)\b(account executive|sales development|bdr|sdr|recruiter|marketing manager|payroll|nurse|clinical|"
    r"pharmac|teacher|driver|warehouse|software engineer(?! in test)|data scientist|accountant)\b"
)
AGENCY = (
    r"(?i)(staffing and recruiting|on behalf of (one of )?our (client|customer)s?|our client,? an? |"
    r"contract[- ]to[- ]hire|corp[- ]to[- ]corp|\bc2c\b(?! or contract role))"
)
MONEY = r"\$\s?(\d{2,3})(?:,(\d{3}))?(?:\.\d+)?\s*[kK]?\s*(?:-|–|to)\s*\$?\s?(\d{2,3})(?:,(\d{3}))?\s*[kK]?"


def norm(c):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\(.*?\)", "", (c or "").lower()))


def band_max(t):
    best = None
    for m in re.finditer(MONEY, t):
        hi = int(m.group(3) + m.group(4)) if m.group(4) else int(m.group(3)) * 1000
        lo = int(m.group(1) + m.group(2)) if m.group(2) else int(m.group(1)) * 1000
        if 30000 <= hi <= 900000 and lo <= hi:
            best = max(best or 0, hi)
    return best


def load_known(submissions_tsv, build_reqs_tsv, canon):
    known = {}
    for path, col_idx, title_idx in ((submissions_tsv, 2, 3), (build_reqs_tsv, 0, 3)):
        if not path or not os.path.isfile(path):
            continue
        for l in open(path):
            x = l.rstrip("\n").split("\t")
            if len(x) > 3 and not l.startswith("#"):
                known.setdefault(canon(x[col_idx]), f"{os.path.basename(path)[:5]}: {x[title_idx][:40]}")
    return known


def fetch(lid):
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{lid}", headers=UA),
            timeout=20,
        ) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception:
        return 0, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=None, help="Directory with raw_cards.json / dedupe_set.json")
    ap.add_argument("--dry", action="store_true", help="Stop after stage A screening, before any JD fetch")
    add_config_arg(ap)
    args = ap.parse_args()

    cfg = load_config(args.config)
    data_dir = args.data_dir or resolve_path(cfg, "paths.data_root") or "."
    submissions_tsv = os.path.join(data_dir, get(cfg, "paths.submissions_tsv", "SUBMISSIONS.tsv"))
    build_reqs_tsv = os.path.join(data_dir, get(cfg, "paths.build_reqs_tsv", "BUILD_reqs.tsv"))
    min_comp = int(get(cfg, "sourcing.min_comp_band", 0) or 0)
    title_in = re.compile(get(cfg, "sourcing.title_include_regex", None) or DEFAULT_TITLE_IN, re.I)
    aliases = {**DEFAULT_ALIASES, **(get(cfg, "sourcing.company_aliases", {}) or {})}

    def canon(c):
        n = norm(c)
        return aliases.get(n, n)

    known = load_known(submissions_tsv, build_reqs_tsv, canon)

    dedupe_path = os.path.join(data_dir, "dedupe_set.json")
    seen = set(json.load(open(dedupe_path))["ids"]) if os.path.isfile(dedupe_path) else set()

    cards_path = os.path.join(data_dir, "raw_cards.json")
    if not os.path.isfile(cards_path):
        sys.exit(f"[li_post] raw_cards.json not found at {cards_path} -- run harvest.py first")
    cards = json.load(open(cards_path))

    log = []
    stageA = []
    for c in cards:
        t, loc = c["title"], c["location"]
        why = None
        ev = ""
        if c["id"] in seen:
            why, ev = "seen-in-earlier-sweep", c["id"]
        elif canon(c["company"]) in known:
            why, ev = "company-known", known[canon(c["company"])]
        elif re.search(NONUS, loc, re.I):
            why, ev = "G0-nonUS-card", loc
        elif "❓" in t or "throttled" in t or "title cut" in t:
            pass  # a throttled/blank title is UNREAD, not off-track; let stage B fetch and re-test it
        elif not title_in.search(t):
            why, ev = "title-not-on-track", t
        elif re.search(NOTTRACK, t):
            why, ev = "title-off-track", t
        elif re.search(JUNIOR, t):
            why, ev = "title-junior", t
        if why:
            log.append((why, c["company"], t, ev[:90], c["id"]))
        else:
            stageA.append(c)
    print(f"cards {len(cards)}  stage A survivors {len(stageA)}  drops {collections.Counter(x[0] for x in log)}", flush=True)
    if args.dry:
        sys.exit(0)

    jd_dir = os.path.join(data_dir, "jd")
    os.makedirs(jd_dir, exist_ok=True)
    out = []
    for i, c in enumerate(stageA):
        fn = os.path.join(jd_dir, f"{c['id']}.txt")
        if os.path.exists(fn):
            out.append(c)
            continue
        code, h = fetch(c["id"])
        tries = 0
        while code == 429 and tries < 2:
            time.sleep(60 * (tries + 1))
            code, h = fetch(c["id"])
            tries += 1
        time.sleep(DELAY)
        if code != 200 or not h:
            log.append((f"fetch-{code}", c["company"], c["title"], "", c["id"]))
            continue
        if "No longer accepting applications" in h:
            log.append(("closed", c["company"], c["title"], "", c["id"]))
            continue
        m = re.search(r'<div class="description__text[^"]*">(.*?)</div>\s*</section>', h, re.S)
        text = re.sub(r"\s+", " ", H.unescape(re.sub("<[^>]+>", " ", m.group(1)))).strip() if m else ""
        crit = {
            a.strip(): b.strip()
            for a, b in re.findall(
                r'<h3 class="description__job-criteria-subheader[^>]*>\s*([^<]+?)\s*</h3>\s*'
                r'<span class="description__job-criteria-text[^>]*>\s*([^<]+?)\s*</span>',
                h,
            )
        }
        lm = re.search(r'topcard__flavor--bullet">\s*([^<]+?)\s*</span>', h)
        lp = lm.group(1).strip() if lm else ""
        full = text + " " + " ".join(f"{k} {v}" for k, v in crit.items())
        ag = (re.search(AGENCY, full) or [""])[0] if re.search(AGENCY, full) else ""
        why = None
        ev = ""
        if re.search(NONUS, lp, re.I) and not re.search(REMOTE_US, text):
            why, ev = "G0-nonUS-page", lp
        else:
            m2 = re.search(OFFICE_ELSEWHERE, text)
            if m2 and not re.search(REMOTE_US, text):
                why, ev = "G0-office-elsewhere", m2.group(0)
            else:
                bm = band_max(text)
                if bm and bm < min_comp:
                    why, ev = "G1-band-under-floor", f"max {bm}"
        if not why and ("❓" in c["title"] or "throttled" in c["title"] or "title cut" in c["title"]):
            tm = re.search(r"top-card-layout__title[^>]*>\s*([^<]+?)\s*<", h)
            real = tm.group(1).strip() if tm else ""
            if real:
                c["title"] = real
            if not real or not title_in.search(real) or re.search(NOTTRACK, real) or re.search(JUNIOR, real):
                why, ev = "title-not-on-track (read from page)", real or "no title on page"
        if why:
            log.append((why, c["company"], c["title"], ev[:90], c["id"]))
            continue
        open(fn, "w").write(
            f"COMPANY: {c['company']}\nTITLE: {c['title']}\nLINKEDIN_ID: {c['id']}\n"
            f"LOCATION (card): {c['location']}\nLOCATION (page): {lp}\nPOSTED: {c.get('posted', '')}\n"
            f"AGENCY_TAG: {ag}\nCRITERIA: {crit}\n\n---\n{text}\n"
        )
        out.append(c)
        if (i + 1) % 20 == 0:
            print(f"  fetched {i + 1}/{len(stageA)} kept {len(out)}", flush=True)

    with open(os.path.join(data_dir, "dropped.tsv"), "w") as f:
        f.write("reason\tcompany\ttitle\tevidence\tlinkedin_id\n")
        for x in log:
            f.write("\t".join(x) + "\n")
    json.dump(out, open(os.path.join(data_dir, "survivors.json"), "w"), indent=0)
    print(f"DONE survivors {len(out)}  drops {collections.Counter(x[0] for x in log)}")


if __name__ == "__main__":
    main()
