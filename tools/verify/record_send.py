#!/usr/bin/env python3
"""
record_send.py -- record a destination-confirmed send: writes a SUBMITTED.md in the
packet folder, appends one row to the direct-send ledger, and rebuilds the read-only
submissions view so every other tool sees it immediately.

Usage: python3 record_send.py [<data-root>] <spec.json> [--config PATH]
       <data-root> defaults to paths.data_root from your config.

spec.json is a list of objects, one per confirmed send:
    [{"packet": "AcmeCorp/270115_SeniorEngineer", "req": "R123", "employer": "Acme Corp",
      "role": "Senior Engineer", "date": "2027-01-15", "ats": "greenhouse",
      "evidence": "confirmation email", "md": "# Submitted\\n..."}]

"packet" is the packet folder relative to <data-root> (the same layout packetlib builds:
<Company>/<YYMMDD_Role>). SUBMITTED.md goes to <data-root>/<packet>/90_SENT/.

Every path stays inside <data-root>. "packet" and paths.direct_ledger_tsv must be relative,
must not contain "..", and must resolve (symlinks followed) to a location under the
resolved data root; anything else is refused before a single file is written.

The ledger file name comes from paths.direct_ledger_tsv. A new ledger starts with a header
row, so build_submissions.py never mistakes the first send for a header. A req already in
the ledger is not appended twice.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, resolve_path, add_config_arg  # noqa: E402

LEDGER_HEADER = ["req_id", "packet_dir", "employer", "role", "submitted_at", "ats", "evidence"]
REQUIRED = ("packet", "req", "employer", "role", "date", "ats", "evidence", "md")


class Escape(Exception):
    pass


def contained(root_real, rel, what):
    """Resolve <root>/<rel> and return it only if it stays under root_real (a realpath).
    Refuses absolute values, '..' components, and symlinks that point outside the root."""
    if not isinstance(rel, str) or not rel.strip():
        raise Escape(f"{what} is empty")
    if os.path.isabs(rel) or rel.startswith("~") or (len(rel) > 1 and rel[1] == ":"):
        raise Escape(f"{what} must be relative to the data root, got an absolute path: {rel!r}")
    parts = rel.replace("\\", "/").split("/")
    if ".." in parts:
        raise Escape(f"{what} must not contain '..': {rel!r}")
    target = os.path.realpath(os.path.join(root_real, rel))
    if os.path.commonpath([root_real, target]) != root_real or target == root_real:
        raise Escape(f"{what} resolves outside the data root: {rel!r} -> {target}")
    return target


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("args", nargs="+", metavar="[data-root] spec.json")
    add_config_arg(ap)
    a = ap.parse_args(argv)
    if len(a.args) > 2:
        ap.error("expected [data-root] spec.json")
    cfg = load_config(a.config)
    data_root = a.args[0] if len(a.args) == 2 else resolve_path(cfg, "paths.data_root")
    spec_path = a.args[-1]
    if not data_root or not os.path.isdir(data_root):
        sys.exit(f"[record_send] data root does not exist: {data_root}")
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    if not isinstance(spec, list) or not spec:
        sys.exit("[record_send] spec.json must be a non-empty JSON list")
    for r in spec:
        if not isinstance(r, dict):
            sys.exit(f"[record_send] each spec entry must be a JSON object: {r!r}")
        missing = [k for k in REQUIRED if not r.get(k)]
        if missing:
            sys.exit(f"[record_send] spec entry is missing {missing}: {r}")
        bad = [k for k in REQUIRED if not isinstance(r[k], str)]
        if bad:
            sys.exit(f"[record_send] spec fields must be strings, not {bad}: {r}")

    root_real = os.path.realpath(data_root)
    try:
        ledger = contained(root_real, str(get(cfg, "paths.direct_ledger_tsv", "LEDGER_direct.tsv")),
                           "paths.direct_ledger_tsv")
        # check every entry BEFORE writing anything, so one bad entry writes nothing at all
        sent_files = [contained(root_real, os.path.join(r["packet"], "90_SENT", "SUBMITTED.md"),
                                f"packet {r['packet']!r}") for r in spec]
    except Escape as e:
        sys.exit(f"[record_send] REFUSE: {e}")
    for r, sent_file in zip(spec, sent_files):
        pk = r["packet"]
        os.makedirs(os.path.dirname(sent_file), exist_ok=True)
        with open(sent_file, "w", encoding="utf-8") as f:
            f.write(r["md"].strip() + "\n")

        existing = ""
        if os.path.exists(ledger):
            with open(ledger, encoding="utf-8") as f:
                existing = f.read()
        with open(ledger, "a", encoding="utf-8") as f:
            if not existing.strip():
                f.write("\t".join(LEDGER_HEADER) + "\n")
            elif not existing.endswith("\n"):
                f.write("\n")
            if "\n" + r["req"] + "\t" not in "\n" + existing:
                f.write("\t".join([r["req"], pk, r["employer"], r["role"], r["date"], r["ats"], r["evidence"]]) + "\n")
                print(f"recorded {r['req']} ({r['employer']}, {r['role']}) -> {ledger}", flush=True)
            else:
                print(f"already in the ledger, not appended again: {r['req']}", flush=True)

    build_submissions = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_submissions.py")
    cmd = [sys.executable, build_submissions, data_root]
    if a.config:
        cmd += ["--config", a.config]
    subprocess.run(cmd, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
