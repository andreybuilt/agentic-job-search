#!/usr/bin/env python3
# TEST: claim_audit.py, against the REAL tool, as a subprocess.
#
# NOTE ON FIXTURES: claim_audit.py normally reads a RENDERED PDF (via pdftotext). This
# environment cannot reliably render a PDF (no headless Chrome / PDF writer available in
# every CI runner), so claim_audit.py was extended to also accept a plain `.txt` file in
# the same `20_MD/*Resume*`/`*CoverLetter*` naming slot as a stand-in for rendered text --
# see find_rendered()/txt() in tools/verify/claim_audit.py. This test uses that path. A
# real PDF still works identically (txt() dispatches on file extension); this is
# documented, not a silent fallback the tool guesses at.
#
# Cases:
#   - KNOWN-BAD: a packet whose text claims something the example rules do not support
#     (sole ownership of an identity provider + an unqualified "I deploy Kubernetes
#     daily" claim) must exit non-zero and report both problems.
#   - KNOWN-GOOD: a packet whose text only mentions the same terms in an allowed,
#     qualified way must exit 0.
#   - controls-run-first: a rules file with a deliberately wrong CONTROLS entry must be
#     refused (exit 2) rather than silently audited.

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
TOOL = os.path.join(REPO_ROOT, "tools", "verify", "claim_audit.py")
RULES = os.path.join(REPO_ROOT, "tools", "examples", "claim_audit_rules.example.yaml")
CONFIG = os.path.join(REPO_ROOT, "config.example.yaml")
GOOD_PACKET = os.path.join(HERE, "fixtures", "claim_audit", "good_packet")
BAD_PACKET = os.path.join(HERE, "fixtures", "claim_audit", "bad_packet")


def run(*args):
    if not os.path.isfile(TOOL):
        raise unittest.SkipTest(f"required tool missing: {TOOL}")
    r = subprocess.run(
        [sys.executable, TOOL, *args, "--rules", RULES, "--config", CONFIG],
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout, r.stderr


class TestClaimAudit(unittest.TestCase):
    def test_tool_exists(self):
        self.assertTrue(os.path.isfile(TOOL))

    def test_controls_pass_on_the_shipped_example_rules(self):
        code, out, err = run()
        self.assertIn("controls:", out, f"controls did not run: {out}\n{err}")
        self.assertNotIn("CONTROLS FAILED", out)
        self.assertEqual(code, 0, "a controls-only run (no packet dirs) must exit 0")

    def test_known_good_packet_passes(self):
        """KNOWN-GOOD: terms mentioned only in an allowed, qualified way must not be
        flagged, and the tool must exit 0."""
        code, out, err = run(GOOD_PACKET)
        self.assertEqual(code, 0, f"clean packet was flagged or crashed\n{out}\n{err}")
        self.assertIn("TOTAL PROBLEMS: 0", out)

    def test_known_bad_packet_is_rejected(self):
        """KNOWN-BAD CASE: a packet claiming sole ownership of an identity provider and
        an unqualified daily-use claim the fixture rules do not support must be caught,
        and -- the actual defect this test guards against -- the process must exit
        NON-ZERO. A gate that prints problems but exits 0 cannot fail a CI run."""
        code, out, err = run(BAD_PACKET)
        self.assertIn("TOTAL PROBLEMS:", out)
        total_line = [l for l in out.splitlines() if l.strip().startswith("TOTAL PROBLEMS:")][0]
        total = int(total_line.split(":")[1].strip())
        self.assertGreater(total, 0, "expected the known-bad fixture to contain at least one flagged claim")
        self.assertNotEqual(
            code, 0,
            f"KNOWN-BAD fixture reported {total} problem(s) but exited 0 -- a gate that reports "
            f"problems with exit 0 cannot fail a CI run\n{out}\n{err}",
        )
        self.assertIn("OWNERSHIP CLAIMED", out)
        self.assertIn("Kubernetes CLAIMED", out)

    def test_controls_run_first_and_refuse_on_a_broken_rules_file(self):
        """A rules file whose CONTROLS section contains a self-contradictory entry must
        cause the audit to refuse (exit 2) rather than silently audit real text with a
        matcher that has already proven itself wrong."""
        import tempfile

        broken = os.path.join(tempfile.gettempdir(), "claim_audit_broken_rules.yaml")
        with open(broken, "w", encoding="utf-8") as f:
            f.write(
                'NEVER:\n'
                '  - label: "example"\n'
                '    pattern: "\\bfoo\\b"\n'
                'CONTROLS:\n'
                '  - text: "this sentence is about something else entirely"\n'
                '    expect: "true"\n'
            )
        try:
            r = subprocess.run(
                [sys.executable, TOOL, GOOD_PACKET, "--rules", broken, "--config", CONFIG],
                capture_output=True,
                text=True,
            )
            self.assertEqual(r.returncode, 2, f"a broken rules file must refuse with exit 2\n{r.stdout}\n{r.stderr}")
            self.assertIn("CONTROLS FAILED", r.stdout)
        finally:
            os.remove(broken)


if __name__ == "__main__":
    unittest.main()
