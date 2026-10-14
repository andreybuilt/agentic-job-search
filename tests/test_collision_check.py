#!/usr/bin/env python3
# TEST: collision_check.py, against the REAL tool, as a subprocess, against a real
# (fixture) data_root on plain disk -- not a git ref.
#
# Cases:
#   - --controls must pass against a data_root that doesn't even exist yet (every control
#     uses its own self-contained fixture data, never the live data_root -- see the
#     docstring on controls() in tools/verify/collision_check.py for why).
#   - KNOWN-BAD: a fixture data_root whose SUBMISSIONS.tsv already contains the exact
#     employer + req being checked must report a HIT and exit non-zero.
#   - KNOWN-GOOD: a query for an employer/req that appears nowhere in the fixture
#     data_root must report CLEAR and exit 0.
#   - the "one application per company" rule: a query for an employer with a prior
#     application under a DIFFERENT req must exit 4 (not clear), not 0.

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
TOOL = os.path.join(REPO_ROOT, "tools", "verify", "collision_check.py")
CONFIG = os.path.join(REPO_ROOT, "config.example.yaml")


def run(data_root, *args):
    if not os.path.isfile(TOOL):
        raise unittest.SkipTest(f"required tool missing: {TOOL}")
    r = subprocess.run(
        [sys.executable, TOOL, "--config", CONFIG, "--data-root", data_root, *args],
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout, r.stderr


class TestCollisionCheck(unittest.TestCase):
    def test_tool_exists(self):
        self.assertTrue(os.path.isfile(TOOL))

    def test_controls_pass_against_a_nonexistent_data_root(self):
        """--controls must behave identically on a brand-new, empty data_root -- it
        proves the mechanism, not that a specific row exists in a real tracker."""
        with tempfile.TemporaryDirectory() as d:
            empty_root = os.path.join(d, "does_not_exist_yet")
            code, out, err = run(empty_root, "--controls")
            self.assertEqual(code, 0, f"--controls must pass against an empty/missing data_root\n{out}\n{err}")
            self.assertIn("controls:", out)
            self.assertNotIn("CONTROLS FAILED", out)

    def test_known_bad_existing_application_is_a_hit(self):
        """KNOWN-BAD CASE: the fixture ledger already contains this exact employer+req.
        The gate must report a HIT and exit non-zero -- resolving a real collision is
        the entire point of this tool."""
        with tempfile.TemporaryDirectory() as data_root:
            with open(os.path.join(data_root, "SUBMISSIONS.tsv"), "w") as f:
                f.write("req_id\tpacket_dir\temployer\trole\tsubmitted_at\toutcome\toutcome_at\tchannel\n")
                f.write("R12345\tAcmeCorp/x\tAcme Corp\tSenior Platform Engineer\t2027-01-01\tNONE\t\t\n")
            code, out, err = run(data_root, "--employer", "Acme Corp", "--title", "Senior Platform Engineer", "--req", "R12345")
            self.assertNotEqual(code, 0, f"KNOWN-BAD: an existing application for the exact employer+req was not flagged\n{out}\n{err}")
            self.assertIn("HIT", out)

    def test_known_good_unrelated_query_is_clear(self):
        """KNOWN-GOOD: a query for an employer/req that appears nowhere in the fixture
        ledger must report CLEAR and exit 0."""
        with tempfile.TemporaryDirectory() as data_root:
            with open(os.path.join(data_root, "SUBMISSIONS.tsv"), "w") as f:
                f.write("req_id\tpacket_dir\temployer\trole\tsubmitted_at\toutcome\toutcome_at\tchannel\n")
                f.write("R12345\tAcmeCorp/x\tAcme Corp\tSenior Platform Engineer\t2027-01-01\tNONE\t\t\n")
            code, out, err = run(data_root, "--employer", "Umbrella Analytics", "--title", "SDR", "--req", "Z99999")
            self.assertEqual(code, 0, f"unrelated query was not reported clear\n{out}\n{err}")
            self.assertIn("CLEAR", out)

    def test_one_per_company_rule_is_not_clear(self):
        """A prior application at the SAME employer under a DIFFERENT req/title is not a
        direct hit, but it is also not a plain CLEAR -- exit 4, 'one application per
        company at a time'."""
        with tempfile.TemporaryDirectory() as data_root:
            with open(os.path.join(data_root, "SUBMISSIONS.tsv"), "w") as f:
                f.write("req_id\tpacket_dir\temployer\trole\tsubmitted_at\toutcome\toutcome_at\tchannel\n")
                f.write("R12345\tAcmeCorp/x\tAcme Corp\tSenior Platform Engineer\t2027-01-01\tNONE\t\t\n")
            code, out, err = run(data_root, "--employer", "Acme Corp", "--title", "Staff Data Engineer", "--req", "R99999")
            self.assertEqual(code, 4, f"a prior application at the same employer under a different req must exit 4\n{out}\n{err}")
            self.assertIn("one-per-company", out)


if __name__ == "__main__":
    unittest.main()
