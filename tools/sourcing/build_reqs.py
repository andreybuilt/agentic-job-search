#!/usr/bin/env python3
"""Export every packet BUILD has a req for, keyed on req_id.

THIS FILE CANNOT AND MUST NOT CARRY SUBMISSION STATE.
BUILD has never observed a submission. SUBMIT owns that in its own ledger TSV(s). We
join on req_id.

Three sources, in precedence order:
  1. packet.json                      -- authoritative, written by your packet builder
  2. 10_SOURCE/*/*JD*.md header       -- '- **req:** `<id>` on **<ats>** (`<token>`)'
  3. overrides.tsv                    -- hand-recovered reqs for pre-standard packets,
                                         each with the URL it was recovered FROM

Precedence is deliberate. A hand-recovered req is the weakest evidence in the file and
the `source` column always says so, because a wrong req in a join column is acted on by
another consumer.

Config-driven (see ../../config.example.yaml):
  paths.data_root  -- the root directory to glob packet.json / *JD*.md under, and
                       where BUILD_reqs.tsv is written (<data_root>/BUILD_reqs.tsv).
                       This used to be a hardcoded "three directories up" path; it is
                       now always read from config or --data-root.
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, resolve_path, add_config_arg  # noqa: E402

JD_REQ = re.compile(r'^\s*-\s*\*\*req:\*\*\s*`([^`]+)`\s*on\s*\*\*([^*]+)\*\*(?:\s*\(`([^`]*)`\))?', re.M)
JD_REQ2 = re.compile(r'^\s*-\s*\*\*req:\*\*\s*([A-Za-z][A-Za-z0-9 ]*?)\s*`([^`]+)`', re.M)  # hand-frozen: 'LinkedIn `123`', 'Comeet `04.33F`'
JD_ANYREQ = re.compile(r'^\s*-\s*\*\*req:\*\*', re.M)
ATS_URLS = {  # first-party job URLs found anywhere in a raw-text JD; the LAST group is the req id
    'amazon': re.compile(r'https?://(?:www\.)?amazon\.jobs/(?:[a-z]{2}/)?jobs/(\d+)'),
    'greenhouse': re.compile(r'https?://(?:job-)?boards\.greenhouse\.io/[\w-]+/jobs/(\d+)'),
    'ashby': re.compile(r'https?://jobs\.ashbyhq\.com/[\w.-]+/([0-9a-f-]{36})'),
    'lever': re.compile(r'https?://jobs\.lever\.co/[\w.-]+/([0-9a-f-]{36})'),
}
JD_URL = re.compile(r'^\s*-\s*\*\*source URL:\*\*\s*(\S+)', re.M)
JD_TTL = re.compile(r'^#\s+(.+)$', re.M)

FIELDS = ['company', 'req_id', 'ats', 'title', 'built_utc', 'url', 'packet_dir',
          'source', 'flag', 'live_checked_at', 'live_state']


def blank():
    return dict.fromkeys(FIELDS, '')


def put(rows, d, src, **kw):
    r = rows.setdefault(d, blank())
    r['packet_dir'] = d
    for k, v in kw.items():
        if v and not r[k]:
            r[k] = str(v)
    if src and src not in r['source']:
        r['source'] = (r['source'] + '+' + src).strip('+')
    return r


def load_tsv(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [r for r in csv.DictReader((l for l in f if not l.startswith('#')), delimiter='\t')]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", default=None, help="Root dir to glob packets under (default: paths.data_root from config)")
    ap.add_argument("--overrides", default=None, help="Path to overrides.tsv (default: <data-root>/overrides.tsv)")
    ap.add_argument("--liveness", default=None, help="Path to liveness.tsv written by verify_liveness.py (default: <data-root>/liveness.tsv)")
    ap.add_argument("--out", default=None, help="Output path for BUILD_reqs.tsv (default: <data-root>/BUILD_reqs.tsv)")
    add_config_arg(ap)
    args = ap.parse_args()

    cfg = load_config(args.config)
    data_root = os.path.abspath(args.data_root or resolve_path(cfg, "paths.data_root") or ".")
    overrides_path = args.overrides or os.path.join(data_root, 'overrides.tsv')
    liveness_path = args.liveness or os.path.join(data_root, 'liveness.tsv')
    out_path = os.path.abspath(args.out or os.path.join(data_root, get(cfg, "paths.build_reqs_tsv", "BUILD_reqs.tsv")))

    if not os.path.isdir(data_root):
        sys.exit(f"[build_reqs] data root does not exist: {data_root}")
    os.chdir(data_root)
    rows = {}

    for p in glob.glob('**/packet.json', recursive=True):
        if '_HISTORY' in p:
            continue
        try:
            with open(p, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception as e:
            print(f'  !! unparseable {p}: {e}', file=sys.stderr)
            continue
        put(rows, os.path.dirname(p), 'packet.json', company=d.get('company'),
            req_id=d.get('req_id'), ats=d.get('ats'), title=d.get('title'),
            built_utc=d.get('built_utc'), url=d.get('url'))

    for p in glob.glob('*/*/10_SOURCE/*/*JD*.md'):
        if '/_STRUCK_' in '/' + p:
            continue  # a struck packet is not a build; it was only ever skipped by accident
        with open(p, encoding='utf-8', errors='replace') as fh:
            t = fh.read(4000)
        raw_url = ''
        m = JD_REQ.search(t)
        u, ttl = JD_URL.search(t), JD_TTL.search(t)
        if m:
            rid, ats = m.group(1).strip(), m.group(2).strip()
        else:
            # Hand-frozen JDs (LinkedIn, Comeet, Jobvite, careers pages) never match the
            # standard header; without this fallback those built packets are invisible to
            # a collision check's built-not-sent roll-up.
            m2 = JD_REQ2.search(t)
            if m2:
                rid, ats = m2.group(2).strip(), m2.group(1).strip().lower()
            elif JD_ANYREQ.search(t) and u:
                rid, ats = 'page:' + u.group(1).strip().rstrip('/').split('/')[-1], 'careers-page'
            elif (hit := next(((k, x) for k, rx in ATS_URLS.items() if (x := rx.search(t))), None)):
                # JDs frozen as raw text sometimes carry their req only in a first-party URL
                # in their own body. Read it rather than skip the packet.
                ats, rid, raw_url = hit[0], hit[1].group(1), hit[1].group(0)
            else:
                # A skip here used to happen silently, making packets with raw-text JDs
                # invisible to downstream checks for days. A skip is now said out loud.
                print(f'  !! SKIPPED (no **req:** line, no source URL): {p}', file=sys.stderr)
                continue
        put(rows, os.path.join(p.split('/10_SOURCE/')[0], '20_MD'), 'frozen_JD',
            company=p.split('/')[0], req_id=rid, ats=ats,
            title=ttl.group(1).strip() if ttl else '', url=u.group(1).strip() if u else raw_url)

    for o in load_tsv(overrides_path):
        put(rows, o['packet_dir'], 'recovered', company=o.get('company'),
            req_id=o.get('req_id'), ats=o.get('ats'), title=o.get('title'),
            url=o.get('url'), flag=o.get('flag'))

    # liveness is written by verify_liveness.py / your capture_jd.py --liveness, joined on req_id
    live = {r['req_id']: r for r in load_tsv(liveness_path) if r.get('req_id')}
    for r in rows.values():
        if r['req_id'] in live:
            r['live_checked_at'] = live[r['req_id']].get('checked_at', '')
            r['live_state'] = live[r['req_id']].get('state', '')

    # A req that appears twice is not a key. Fail loudly rather than emit a broken join column.
    # SUPERSEDED rows are exempt: one req legitimately has an old packet and the rebuild that
    # replaced it. They stay in the file so nobody re-discovers the old folder as fresh work,
    # but they are not candidates for the join.
    seen = {}
    for d, r in rows.items():
        if r['req_id'] and 'SUPERSEDED' not in r['flag']:
            seen.setdefault(r['req_id'], []).append(d)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}

    with open(out_path, 'w') as f:
        f.write("# BUILD-side export of every packet this builder has a req for.\n")
        f.write("# Regenerate: python3 tools/sourcing/build_reqs.py --data-root <path>\n")
        f.write("# NO SUBMISSION STATE IS IN THIS FILE AND NONE EVER WILL BE. BUILD has never\n")
        f.write("#    observed a submission. built_utc is when the PDF was RENDERED. SUBMIT owns\n")
        f.write("#    submission state in its own ledger; we join on req_id, never the folder slug.\n")
        f.write("# source: packet.json (authoritative) > frozen_JD > recovered (weakest -- a req\n")
        f.write("#    dug out of an old URL by hand; see overrides.tsv for where each came from).\n")
        f.write("# flag:   STRUCK = submission forbidden, read the packet's DO_NOT_SUBMIT.md\n")
        f.write("#         NOT_SENT_MARKER = its sent-archive folder says nothing was ever sent\n")
        f.write("#         GATE0 = location as posted fails your location screen\n")
        f.write("#         SUPERSEDED_BY_<x> = an older packet for a req that was rebuilt; NOT fresh work\n")
        f.write("# live_state: LIVE/CLOSED/THIN/ERROR from verify_liveness.py. ERROR IS NOT CLOSED.\n")
        f.write('\t'.join(FIELDS) + '\n')
        for d in sorted(rows):
            f.write('\t'.join(rows[d][k].replace('\t', ' ').replace('\n', ' ') for k in FIELDS) + '\n')

    print(f'{len(rows)} rows -> {out_path}')
    from collections import Counter
    print('  source:', dict(Counter(r['source'] for r in rows.values())))
    print('  flag:  ', dict(Counter(r['flag'] for r in rows.values() if r['flag'])))
    print('  live:  ', dict(Counter(r['live_state'] for r in rows.values() if r['live_state'])))
    print('  no req:', sum(1 for r in rows.values() if not r['req_id']))
    if dupes:
        print(f'\n{len(dupes)} req_id(s) appear on more than one packet -- the join column is NOT unique:')
        for k, v in dupes.items():
            print(f'   {k}: {v}')
        return 1
    live_n = sum(1 for r in rows.values() if r['req_id'] and 'SUPERSEDED' not in r['flag'])
    sup_n = sum(1 for r in rows.values() if r['req_id'] and 'SUPERSEDED' in r['flag'])
    print(f'  req_id unique among the {live_n} LIVE rows: yes '
          f'({sup_n} superseded row(s) excluded -- the file DOES carry duplicate req_ids;')
    print('   join on (req_id, packet_dir) or filter SUPERSEDED, never on req_id alone)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
