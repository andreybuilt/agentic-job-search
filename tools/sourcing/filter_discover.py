#!/usr/bin/env python3
"""
filter_discover.py -- screen discovery probe jobs (from probe_discover.py's
probe_jobs.json) with the SAME title and location screens as sweep.py, drop
companies you've already applied to or built a packet for, drop generic-slug
boards whose JDs never actually name the company (a common false-positive --
some ATS slugs are shared scaffolding, not a real company's board), and write
jd/<ats>_<req>.txt for survivors.

This replaces the original mechanism, which `exec`'d a slice of sweep.py's
source as a shortcut to reuse its screen functions. That is now a clean
import from ats_common.py instead -- same screening logic, no source-slicing.

Config-driven (see ../../config.example.yaml):
  paths.data_root       -- directory holding probe_jobs*.json and where jd/, to_screen.tsv land
  paths.submissions_tsv -- your submissions view, relative to data_root
  paths.build_reqs_tsv  -- your built-packet index, relative to data_root
  sourcing.title_include_regex / title_exclude_regex / target_metro_regex / target_state_abbr
    -- same keys sweep.py reads; keep them consistent so discovery and the main
       sweep use the same screen.

Usage:
  python3 filter_discover.py [--config path] [--data-dir DIR]
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, resolve_path, add_config_arg  # noqa: E402
from ats_common import (  # noqa: E402
    build_title_regexes, make_loc_ok, strip_html as strip,
    DEFAULT_TARGET_METRO, DEFAULT_TARGET_STATE_ABBR,
)


def norm(c):
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\s*\(.*?\)", "", (c or "").lower()))


def load_known(submissions_tsv, build_reqs_tsv):
    known = {}
    for path, col in ((submissions_tsv, 2), (build_reqs_tsv, 0)):
        if not path or not os.path.isfile(path):
            continue
        for l in open(path):
            x = l.rstrip("\n").split("\t")
            if len(x) > 3 and not l.startswith("#"):
                known.setdefault(norm(x[col]), os.path.basename(path))
    return known


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=None, help="Directory with probe_jobs*.json (default: paths.data_root)")
    add_config_arg(ap)
    args = ap.parse_args()

    cfg = load_config(args.config)
    data_dir = args.data_dir or resolve_path(cfg, "paths.data_root") or "."
    submissions_tsv = os.path.join(data_dir, get(cfg, "paths.submissions_tsv", "SUBMISSIONS.tsv"))
    build_reqs_tsv = os.path.join(data_dir, get(cfg, "paths.build_reqs_tsv", "BUILD_reqs.tsv"))

    title_in, title_out = build_title_regexes(lambda k, d: get(cfg, k, d))
    loc_ok = make_loc_ok(
        get(cfg, "sourcing.target_metro_regex", None) or DEFAULT_TARGET_METRO,
        get(cfg, "sourcing.target_state_abbr", None) or DEFAULT_TARGET_STATE_ABBR,
    )

    known = load_known(submissions_tsv, build_reqs_tsv)

    jobs = []
    for fn in ("probe_jobs_r1.json", "probe_jobs.json"):
        p = os.path.join(data_dir, fn)
        if os.path.exists(p):
            for entry in json.load(open(p)):
                for j in entry["jobs"]:
                    j["company"] = entry["company"]
                    j["name_mentions"] = entry["name_mentions"]
                    j["njobs"] = entry["njobs"]
                    jobs.append(j)

    jd_dir = os.path.join(data_dir, "jd")
    os.makedirs(jd_dir, exist_ok=True)
    drops = collections.Counter()
    keep = []
    seen = set()
    for j in jobs:
        k = (j["ats"], j["req"])
        if k in seen:
            continue
        seen.add(k)
        locs = [x.strip() for x in (j.get("loc") or "").split("|")]
        if not title_in.search(j["title"]) or title_out.search(j["title"]):
            drops["title"] += 1
            continue
        g0 = loc_ok(locs, j.get("remote"))
        if not g0:
            drops["location"] += 1
            continue
        if norm(j["company"]) in known or norm(j["slug"]) in known:
            drops["company-known"] += 1
            continue
        if j["name_mentions"] == 0:
            drops["board-never-names-company"] += 1
            continue
        j["gate0"] = g0
        keep.append(j)
        open(os.path.join(jd_dir, f"{j['ats']}_{j['req']}.txt"), "w").write(
            f"company: {j['company']} (board slug {j['slug']})\ntitle: {j['title']}\nats: {j['ats']}\nreq: {j['req']}\n"
            f"url: {j['url']}\nlocations (API): {j.get('loc', '')} | remote flag={j.get('remote')}\n"
            f"gate0 screen: {g0}\ncompensation (API): {j.get('comp') or 'none in API'}\n\n{strip(j.get('content', ''))}\n"
        )

    with open(os.path.join(data_dir, "to_screen.tsv"), "w") as f:
        f.write("company\tslug\tats\treq\ttitle\tgate0\tlocations\tcomp\turl\n")
        for j in keep:
            f.write(
                "\t".join(
                    [
                        j["company"], j["slug"], j["ats"], j["req"], j["title"], j["gate0"],
                        (j.get("loc") or "")[:150], (j.get("comp") or "")[:150], j["url"],
                    ]
                )
                + "\n"
            )
    print("jobs", len(seen), "kept", len(keep), dict(drops))
    print(collections.Counter(j["gate0"] for j in keep))


if __name__ == "__main__":
    main()
