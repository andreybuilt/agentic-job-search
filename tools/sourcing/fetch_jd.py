#!/usr/bin/env python3
"""
fetch_jd.py -- tag new ATS reqs against companies you've already applied to or
built a packet for (one application per company is the default policy), then
save the full JD text for survivors to <out-dir>/jd/<ats>_<req>.txt.

Ashby is asked with includeCompensation=true; Lever's API often carries no pay
band so this also reads the hosted page for one; Greenhouse is asked with
pay_transparency=true.

Config-driven (see ../../config.example.yaml):
  paths.data_root        -- root directory holding your tracking TSVs
  paths.submissions_tsv  -- path to your submissions ledger (default: <data_root>/SUBMISSIONS.tsv)
  paths.build_reqs_tsv   -- path to your built-packet index (default: <data_root>/BUILD_reqs.tsv)

Nothing here is hardcoded to a specific project layout -- every path comes
from config or a CLI flag. If a referenced TSV does not exist yet, it is
treated as empty (no known companies) rather than failing.

Usage:
  python3 fetch_jd.py <new_tsv> [--out-dir DIR] [--config path]

<new_tsv> is a TSV with header employer_slug/ats/req/title/gate0/locations/comp/url
(the shape sweep.py's candidates.tsv produces).
"""
import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, resolve_path, add_config_arg  # noqa: E402

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
}


def norm(c):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\(.*?\)", "", (c or "").lower()))


# Known aliasing for companies that list under more than one name/slug.
# Extend via sourcing.company_aliases in config if you need more.
DEFAULT_ALIASES = {
    "amazonwebservicesaws": "amazon", "amazonwebservices": "amazon", "aws": "amazon",
    "googlecloud": "google", "microsoftazure": "microsoft",
}


def make_canon(aliases):
    def canon(c):
        n = norm(c)
        return aliases.get(n, n)

    return canon


def load_known(submissions_tsv, build_reqs_tsv, canon):
    known = {}
    if submissions_tsv and os.path.isfile(submissions_tsv):
        for l in open(submissions_tsv):
            f = l.rstrip("\n").split("\t")
            if len(f) > 3 and not l.startswith("#"):
                known.setdefault(canon(f[2]), f"applied: {f[3][:40]} ({f[4][:12]})" if len(f) > 4 else f"applied: {f[3][:40]}")
    if build_reqs_tsv and os.path.isfile(build_reqs_tsv):
        for l in open(build_reqs_tsv):
            f = l.rstrip("\n").split("\t")
            if len(f) > 3 and not l.startswith("#"):
                known.setdefault(canon(f[0]), f"built: {f[3][:40]}")
    return known


def get_url(u, js=True):
    with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as r:
        b = r.read().decode("utf-8", "replace")
        return json.loads(b) if js else b


def txt(h):
    return re.sub(
        r"\n\s*\n+", "\n\n",
        re.sub(
            r"[ \t]+", " ",
            html.unescape(
                re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", re.sub(r"<li[^>]*>", "\n- ", html.unescape(h or "")), flags=re.I)
            ).replace("<", "\x00<"),
        ),
    ).replace("\x00", "")


def strip_html(h):
    return re.sub(r"<[^>]+>", "", txt(h)).strip()


def fetch(r, ash_cache):
    a, s, q = r["ats"], r["employer_slug"], r["req"]
    if a.startswith(("gh", "greenhouse")):
        j = get_url(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs/{q}?pay_transparency=true")
        pay = "; ".join(
            f"{p.get('title', '')}: {p.get('min_cents', 0) // 100}-{p.get('max_cents', 0) // 100} {p.get('currency_type', '')}"
            for p in (j.get("pay_input_ranges") or [])
        )
        return strip_html(j.get("content", "")), pay or "not in API", (j.get("location") or {}).get("name", "")
    if a.startswith("ash"):
        if s not in ash_cache:
            ash_cache[s] = {
                j["id"]: j for j in get_url(f"https://api.ashbyhq.com/posting-api/job-board/{s}?includeCompensation=true")["jobs"]
            }
        j = ash_cache[s].get(q)
        if not j:
            return None, "", ""
        comp = j.get("compensation") or {}
        tiers = []
        for t in comp.get("compensationTiers") or []:
            for c in t.get("components") or []:
                tiers.append(
                    f"{t.get('title', '')} {c.get('compensationType', '')} {c.get('minValue')}-{c.get('maxValue')} "
                    f"{c.get('currencyCode', '')} {c.get('interval', '')}"
                )
        locs = [j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations") or []]
        return (
            j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")),
            " ; ".join(tiers) or (comp.get("compensationTierSummary") or "none in API"),
            " | ".join(l for l in locs if l) + f" | workplaceType={j.get('workplaceType')} isRemote={j.get('isRemote')}",
        )
    if a.startswith("lev"):
        j = get_url(f"https://api.lever.co/v0/postings/{s}/{q}")
        body = (
            (j.get("descriptionPlain") or "")
            + "\n"
            + "\n".join(l.get("text", "") + "\n" + strip_html(l.get("content", "")) for l in j.get("lists") or [])
            + "\n"
            + (j.get("additionalPlain") or "")
        )
        sr = j.get("salaryRange") or {}
        pay = f"API {sr.get('min')}-{sr.get('max')} {sr.get('currency', '')} {sr.get('interval', '')}" if sr else "API none"
        try:
            hp = strip_html(get_url(j["hostedUrl"], js=False))
            m = re.search(r"\$\s?\d{2,3}[,.]?\d{0,3}[kK]?\s*(?:-|–|to)\s*\$?\s?\d{2,3}[,.]?\d{0,3}[kK]?", hp)
            pay += " ; hosted page: " + (m.group(0) if m else "none on the page")
        except Exception as e:
            pay += f" ; hosted page UNREAD ({e.__class__.__name__})"
        c = j.get("categories", {})
        return (
            body, pay,
            " | ".join(x for x in [c.get("location", "")] + (c.get("allLocations") or []) if x) + f" | workplaceType={j.get('workplaceType')}",
        )
    return None, "", ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("new_tsv", help="TSV of new reqs to fetch (sweep.py's candidates.tsv shape)")
    ap.add_argument("--out-dir", default=".", help="Directory to write jd/, dropped_company.tsv, to_screen.tsv into")
    add_config_arg(ap)
    args = ap.parse_args()

    cfg = load_config(args.config)
    data_root = resolve_path(cfg, "paths.data_root") or "."
    submissions_tsv = os.path.join(data_root, get(cfg, "paths.submissions_tsv", "SUBMISSIONS.tsv"))
    build_reqs_tsv = os.path.join(data_root, get(cfg, "paths.build_reqs_tsv", "BUILD_reqs.tsv"))
    canon = make_canon({**DEFAULT_ALIASES, **(get(cfg, "sourcing.company_aliases", {}) or {})})

    known = load_known(submissions_tsv, build_reqs_tsv, canon)
    folders = set()
    if os.path.isdir(data_root):
        folders = {
            canon(d) for d in os.listdir(data_root)
            if os.path.isdir(os.path.join(data_root, d)) and not d.startswith(("_", "."))
        }

    if not os.path.isfile(args.new_tsv):
        sys.exit(f"[fetch_jd] input TSV not found: {args.new_tsv}")
    rows = list(csv.DictReader(open(args.new_tsv), delimiter="\t"))
    jd_dir = os.path.join(args.out_dir, "jd")
    os.makedirs(jd_dir, exist_ok=True)

    ash_cache = {}
    keep = []
    drop = []
    for r in rows:
        k = canon(r["employer_slug"])
        hit = known.get(k) or ("packet folder exists" if k in folders else None)
        if hit:
            r["drop"] = hit
            drop.append(r)
            continue
        try:
            body, pay, loc = fetch(r, ash_cache)
        except Exception as e:
            body, pay, loc = None, "", f"ERR {e}"
        if not body:
            r["drop"] = f"JD not fetched {loc}"
            drop.append(r)
            continue
        fn = os.path.join(jd_dir, f"{r['ats']}_{r['req']}.txt")
        open(fn, "w").write(
            f"company_slug: {r['employer_slug']}\ntitle: {r['title']}\nats: {r['ats']}\nreq: {r['req']}\n"
            f"url: {r['url']}\nlocations (API): {loc}\ngate0 screen: {r['gate0']}\ncompensation: {pay}\n"
            f"fetched: {time.strftime('%Y-%m-%d %H:%M')}\n\n{body}\n"
        )
        r["jd_file"] = os.path.basename(fn)
        keep.append(r)
        time.sleep(0.3)

    with open(os.path.join(args.out_dir, "dropped_company.tsv"), "w") as f:
        f.write("slug\ttitle\treq\treason\n")
        for r in drop:
            f.write(f"{r['employer_slug']}\t{r['title']}\t{r['req']}\t{r['drop']}\n")
    with open(os.path.join(args.out_dir, "to_screen.tsv"), "w") as f:
        w = csv.DictWriter(f, fieldnames=list(keep[0]) if keep else ["x"], delimiter="\t")
        w.writeheader()
        w.writerows(keep)
    print("new", len(rows), "dropped", len(drop), "to screen", len(keep))


if __name__ == "__main__":
    main()
