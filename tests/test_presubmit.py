#!/usr/bin/env python3
# TEST: presubmit.sh, against the REAL tool, as a subprocess. No browser needed -- the
# gate only reads plain files from a data_root.
#
# Cases:
#   - the mandatory mail-search flag: calling without --mailbox-hits must refuse (exit 1)
#     -- this is the gate's whole reason to exist (see its own header comment: built
#     after a real double-submission where every tracked file was silent).
#   - KNOWN-BAD: a fixture SUBMISSIONS.tsv already carries this req -> GATE FAILED, exit 1.
#   - KNOWN-GOOD: every tracker present, the req in the build export, mailbox 0 -> GATE
#     PASSED, exit 0.
#   - FAIL-SAFE: a data_root with no tracker files must NOT print GATE PASSED.
#   - LIVENESS: only live_state LIVE passes; ERROR, blank and any other value fail.
#   - a DO_NOT_SUBMIT.md marker at the packet root is a hard stop regardless of anything
#     else being clean.

import os
import stat
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
TOOL = os.path.join(REPO_ROOT, "tools", "verify", "presubmit.sh")
CONFIG = os.path.join(REPO_ROOT, "config.example.yaml")
BUILD_HEADER = "company\treq_id\tats\ttitle\tbuilt_utc\turl\tpacket_dir\tsource\tflag\tlive_checked_at\tlive_state\n"


def seed(data_root, build_rows=()):
    """Create every tracker file, empty, as a user does on day one."""
    for name in ("QUEUE.md", "SUBMISSIONS.tsv", "LEDGER_mailbox.tsv", "LEDGER_candidates.tsv"):
        open(os.path.join(data_root, name), "w").close()
    with open(os.path.join(data_root, "BUILD_reqs.tsv"), "w") as f:
        f.write(BUILD_HEADER)
        for r in build_rows:
            f.write("\t".join(r) + "\n")


def run(data_root, *args):
    if not os.path.isfile(TOOL):
        raise unittest.SkipTest(f"required tool missing: {TOOL}")
    r = subprocess.run(
        ["bash", TOOL, *args, "--data-root", data_root, "--config", CONFIG],
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout, r.stderr


class TestPresubmit(unittest.TestCase):
    def test_tool_exists_and_is_executable(self):
        self.assertTrue(os.path.isfile(TOOL))
        self.assertTrue(os.stat(TOOL).st_mode & stat.S_IXUSR, "presubmit.sh should be executable")

    def test_missing_mailbox_hits_refuses(self):
        """The mandatory mail-search flag is mandatory: no default, no bypass."""
        with tempfile.TemporaryDirectory() as data_root:
            code, out, err = run(data_root, "AcmeCorp/x", "R12345")
            self.assertNotEqual(code, 0, f"missing --mailbox-hits must refuse\n{out}\n{err}")
            self.assertIn("NOT RUN", out)

    def test_known_bad_already_submitted_req_fails(self):
        """KNOWN-BAD CASE: the fixture submissions table already carries this exact req.
        The gate must fail closed (exit 1), never let a second send through."""
        with tempfile.TemporaryDirectory() as data_root:
            seed(data_root)
            with open(os.path.join(data_root, "SUBMISSIONS.tsv"), "w") as f:
                f.write("req_id\tpacket_dir\temployer\trole\tsubmitted_at\toutcome\toutcome_at\tchannel\n")
                f.write("R12345\tAcmeCorp/x\tAcme Corp\tSenior Platform Engineer\t2027-01-01\tNONE\t\t\n")
            code, out, err = run(data_root, "AcmeCorp/x", "R12345", "--mailbox-hits", "0")
            self.assertNotEqual(code, 0, f"KNOWN-BAD: an already-submitted req was not caught\n{out}\n{err}")
            self.assertIn("GATE FAILED", out)
            self.assertIn("already submitted", out)

    def test_known_good_clean_data_root_passes(self):
        """KNOWN-GOOD: every tracker exists, nothing tracked for this req, the req is in the
        build export and LIVE, live mail search passed as 0 hits -> GATE PASSED, exit 0."""
        with tempfile.TemporaryDirectory() as data_root:
            seed(data_root, [("Acme Corp", "R12345", "greenhouse", "Senior Platform Engineer", "", "",
                              "AcmeCorp/x/20_MD", "packet.json", "", "2027-01-01", "LIVE")])
            code, out, err = run(data_root, "AcmeCorp/x", "R12345", "--mailbox-hits", "0")
            self.assertEqual(code, 0, f"clean data root should pass\n{out}\n{err}")
            self.assertIn("GATE PASSED", out)
            self.assertIn("0 acks (caller-verified, live)", out)

    def test_missing_trackers_fail_safe(self):
        """FAIL-SAFE: an empty data root (no tracker files at all) must never print GATE
        PASSED. Missing history cannot be told apart from a wrong path."""
        with tempfile.TemporaryDirectory() as data_root:
            code, out, err = run(data_root, "AcmeCorp/x", "R12345", "--mailbox-hits", "0")
            self.assertNotEqual(code, 0, f"missing trackers must fail\n{out}\n{err}")
            self.assertNotIn("GATE PASSED", out)
            self.assertIn("MISSING", out)

    def test_help_exits_zero(self):
        r = subprocess.run(["bash", TOOL, "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("Usage", r.stdout)

    def test_do_not_submit_marker_is_a_hard_stop(self):
        """A DO_NOT_SUBMIT.md file at the packet root must fail the gate even when every
        other check is clean."""
        with tempfile.TemporaryDirectory() as data_root:
            seed(data_root)
            packet_dir = os.path.join(data_root, "AcmeCorp", "x")
            os.makedirs(packet_dir)
            with open(os.path.join(packet_dir, "DO_NOT_SUBMIT.md"), "w") as f:
                f.write("Held by a human decision -- do not send.\n")
            code, out, err = run(data_root, "AcmeCorp/x", "R12345", "--mailbox-hits", "0")
            self.assertNotEqual(code, 0, f"a DO_NOT_SUBMIT.md marker must fail the gate\n{out}\n{err}")
            self.assertIn("DO_NOT_SUBMIT.md present", out)

    def test_only_live_passes(self):
        """codex_r2 #2: ERROR (the check could not run), a blank live_state, and any value
        other than LIVE must fail the gate. Unknown liveness is not a pass."""
        for state in ("ERROR", "", "THIN", "NOT ON BOARD", "live", "UNKNOWN", "CLOSED"):
            with self.subTest(live_state=state), tempfile.TemporaryDirectory() as data_root:
                seed(data_root, [("Acme Corp", "R12345", "greenhouse", "Senior Platform Engineer", "", "",
                                  "AcmeCorp/x/20_MD", "packet.json", "", "2027-01-01", state)])
                code, out, err = run(data_root, "AcmeCorp/x", "R12345", "--mailbox-hits", "0")
                self.assertEqual(code, 1, f"live_state {state!r} must fail the gate\n{out}\n{err}")
                self.assertIn("GATE FAILED", out)
                self.assertNotIn("GATE PASSED", out)
                self.assertIn("LIVENESS", out)


if __name__ == "__main__":
    unittest.main()
