#!/usr/bin/env python3
# TEST: record_send.py -> build_submissions.py -> presubmit.sh, end to end on a temp data root.
#
# The bug this guards: build_submissions.py used to drop the first row of every ledger as a
# "header", while record_send.py wrote the direct ledger with no header. The FIRST recorded
# send vanished, and the double-submit guard missed exactly the send it exists to catch.

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
CONFIG = os.path.join(REPO_ROOT, "config.example.yaml")
RECORD = os.path.join(REPO_ROOT, "tools", "verify", "record_send.py")
BUILD = os.path.join(REPO_ROOT, "tools", "verify", "build_submissions.py")
PRESUBMIT = os.path.join(REPO_ROOT, "tools", "verify", "presubmit.sh")

SEND = {"packet": "AcmeCorp/270115_SeniorEngineer", "req": "R123", "employer": "Acme Corp",
        "role": "Senior Engineer", "date": "2027-01-15", "ats": "greenhouse",
        "evidence": "confirmation email", "md": "# Submitted\n"}


def data_rows(path):
    with open(path, encoding="utf-8") as f:
        lines = [l.rstrip("\n").split("\t") for l in f if l.strip() and not l.startswith("#")]
    return lines[1:]  # SUBMISSIONS.tsv always starts with its header


class TestRoundTrip(unittest.TestCase):
    def record(self, data_root, sends):
        spec = os.path.join(data_root, "spec.json")
        with open(spec, "w", encoding="utf-8") as f:
            json.dump(sends, f)
        return subprocess.run([sys.executable, RECORD, data_root, spec, "--config", CONFIG],
                              capture_output=True, text=True)

    def test_first_send_is_visible_everywhere(self):
        with tempfile.TemporaryDirectory() as d:
            r = self.record(d, [SEND])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            with open(os.path.join(d, "LEDGER_direct.tsv"), encoding="utf-8") as f:
                self.assertTrue(f.readline().startswith("req_id\t"), "a new ledger must start with its header")
            rows = data_rows(os.path.join(d, "SUBMISSIONS.tsv"))
            self.assertEqual(len(rows), 1, f"expected the one send in SUBMISSIONS.tsv, got {rows}")
            self.assertEqual(rows[0][0], "R123")
            self.assertTrue(os.path.isfile(os.path.join(d, SEND["packet"], "90_SENT", "SUBMITTED.md")))

            for name in ("QUEUE.md", "LEDGER_mailbox.tsv", "LEDGER_candidates.tsv", "BUILD_reqs.tsv"):
                open(os.path.join(d, name), "a").close()
            p = subprocess.run(["bash", PRESUBMIT, SEND["packet"], "R123", "--mailbox-hits", "0",
                                "--data-root", d, "--config", CONFIG], capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0, p.stdout)
            self.assertIn("req already submitted", p.stdout)
            self.assertNotIn("GATE PASSED", p.stdout)

    def test_recording_twice_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            self.record(d, [SEND])
            self.record(d, [SEND])
            self.assertEqual(len(data_rows(os.path.join(d, "SUBMISSIONS.tsv"))), 1)
            with open(os.path.join(d, "LEDGER_direct.tsv"), encoding="utf-8") as f:
                self.assertEqual(sum(1 for l in f if l.startswith("R123\t")), 1)

    def test_headerless_legacy_ledger_keeps_its_first_row(self):
        """A ledger written before this fix has no header. Its first row is data."""
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "LEDGER_direct.tsv"), "w", encoding="utf-8") as f:
                f.write("R999\tGlobex/x\tGlobex Industries\tEngineer\t2027-01-02\tlever\temail\n")
            r = subprocess.run([sys.executable, BUILD, d, "--config", CONFIG], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual([x[0] for x in data_rows(os.path.join(d, "SUBMISSIONS.tsv"))], ["R999"])

    def test_spec_with_a_missing_field_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            bad = dict(SEND)
            del bad["req"]
            r = self.record(d, [bad])
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(os.path.exists(os.path.join(d, "LEDGER_direct.tsv")))


class TestStaysInsideTheDataRoot(unittest.TestCase):
    """codex_r2 #4: no spec value or config value may make record_send write outside the
    resolved data root. Each attempt must exit non-zero and write NOTHING, anywhere."""

    def attempt(self, packet=None, ledger=None, setup=None):
        with tempfile.TemporaryDirectory() as outer:
            root = os.path.join(outer, "data")
            os.makedirs(root)
            if setup:
                setup(outer, root)
            # an absolute value is given as a callable of the temp dir, so even a broken
            # implementation can only ever write inside this test's own temp directory
            packet = packet(outer) if callable(packet) else packet
            ledger = ledger(outer) if callable(ledger) else ledger
            config = CONFIG
            if ledger is not None:
                config = os.path.join(outer, "config.yaml")
                with open(CONFIG, encoding="utf-8") as f:
                    text = f.read()
                self.assertIn('direct_ledger_tsv: "LEDGER_direct.tsv"', text)
                with open(config, "w", encoding="utf-8") as f:
                    f.write(text.replace('direct_ledger_tsv: "LEDGER_direct.tsv"', f'direct_ledger_tsv: "{ledger}"'))
            send = dict(SEND)
            if packet is not None:
                send["packet"] = packet
            spec = os.path.join(outer, "spec.json")
            with open(spec, "w", encoding="utf-8") as f:
                json.dump([dict(SEND, req="R1"), send], f)  # a good entry first: it must not be written either
            before = sorted(os.path.relpath(os.path.join(d, x), outer)
                            for d, ds, fs in os.walk(outer) for x in ds + fs)
            r = subprocess.run([sys.executable, RECORD, root, spec, "--config", config],
                               capture_output=True, text=True)
            after = sorted(os.path.relpath(os.path.join(d, x), outer)
                           for d, ds, fs in os.walk(outer) for x in ds + fs)
            return r, before, after

    def assertRefused(self, *a, **kw):
        r, before, after = self.attempt(*a, **kw)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("REFUSE", r.stderr + r.stdout)
        self.assertEqual(before, after, "a refused record_send must not write any file")

    def test_control_a_normal_packet_is_written(self):
        r, before, after = self.attempt()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(os.path.join("data", "AcmeCorp", "270115_SeniorEngineer", "90_SENT", "SUBMITTED.md"), after)

    def test_traversing_packet(self):
        self.assertRefused(packet="../../target")
        self.assertRefused(packet="AcmeCorp/../../escape")

    def test_absolute_packet(self):
        self.assertRefused(packet=lambda outer: os.path.join(outer, "abs-escape"))

    def test_symlinked_packet_escaping_the_root(self):
        def link(outer, root):
            os.makedirs(os.path.join(outer, "elsewhere"))
            os.symlink(os.path.join(outer, "elsewhere"), os.path.join(root, "Evil"))
        self.assertRefused(packet="Evil/270115_Role", setup=link)

    def test_absolute_ledger_in_config(self):
        self.assertRefused(ledger=lambda outer: os.path.join(outer, "abs-escape.tsv"))

    def test_traversing_ledger_in_config(self):
        self.assertRefused(ledger="../LEDGER_direct.tsv")

    def test_symlinked_ledger_escaping_the_root(self):
        def link(outer, root):
            open(os.path.join(outer, "outside.tsv"), "w").close()
            os.symlink(os.path.join(outer, "outside.tsv"), os.path.join(root, "LEDGER_link.tsv"))
        self.assertRefused(ledger="LEDGER_link.tsv", setup=link)

    def test_non_string_packet(self):
        r, before, after = self.attempt(packet=["AcmeCorp"])
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(before, after)


class TestBuildSubmissionsContainment(unittest.TestCase):
    """Codex round 3: build_submissions.py's own containment check must be able to fail a test."""

    def run_build(self, d, value):
        cfg = os.path.join(d, "cfg.yaml")
        with open(CONFIG, encoding="utf-8") as f:
            text = f.read()
        text = text.replace('submissions_tsv: "SUBMISSIONS.tsv"', f'submissions_tsv: "{value}"')
        self.assertIn(value, text, "config template no longer carries paths.submissions_tsv")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(text)
        return subprocess.run([sys.executable, BUILD, os.path.join(d, "root"), "--config", cfg],
                              capture_output=True, text=True)

    def check_refused(self, value, outside):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "root"))
            r = self.run_build(d, value.replace("{D}", d))
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("outside the data root", r.stdout + r.stderr)
            self.assertFalse(os.path.exists(outside.replace("{D}", d)), "wrote outside the data root")

    def test_control_inside_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "root"))
            r = self.run_build(d, "SUBMISSIONS.tsv")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(os.path.isfile(os.path.join(d, "root", "SUBMISSIONS.tsv")))

    def test_absolute_path_is_refused(self):
        self.check_refused("{D}/escaped.tsv", "{D}/escaped.tsv")

    def test_traversal_is_refused(self):
        self.check_refused("../escaped.tsv", "{D}/escaped.tsv")

    def test_symlink_escape_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            os.mkdir(os.path.join(d, "root"))
            os.mkdir(os.path.join(d, "out"))
            os.symlink(os.path.join(d, "out"), os.path.join(d, "root", "link"))
            r = self.run_build(d, "link/escaped.tsv")
            self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse(os.path.exists(os.path.join(d, "out", "escaped.tsv")))


if __name__ == "__main__":
    unittest.main()
