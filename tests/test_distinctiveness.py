#!/usr/bin/env python3
# TEST: cover-letter distinctiveness / six-gram overlap check
#
# Exercises the REAL tool (tools/build/check-distinct.py) as a subprocess against real
# fixture HTML letters -- no fallback/reference implementation. If tools/build/check-
# distinct.py is missing or its CLI contract changes, this test fails loudly rather than
# silently passing against a stand-in.
#
# Cases:
#   - self-overlap positive control (a letter vs. itself: the measure must fire)
#   - two genuinely different letters: must be reported DISTINCT (exit 0)
#   - two near-duplicate letters (same template, swapped company/role): must be reported
#     NOT DISTINCT (exit 1) -- this is the KNOWN-BAD case: a near-duplicate pair the gate
#     must actually reject, not just a case it happens to pass.
#   - ordering sanity: the near-duplicate pair must share strictly more six-grams than the
#     genuinely distinct pair.

import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures", "distinctiveness")
TOOL = os.path.normpath(os.path.join(HERE, "..", "tools", "build", "check-distinct.py"))


def run(a, b, n=6):
    if not os.path.isfile(TOOL):
        raise unittest.SkipTest(f"required tool missing: {TOOL}")
    r = subprocess.run(
        [sys.executable, TOOL, os.path.join(FIXTURES, a), os.path.join(FIXTURES, b), str(n)],
        capture_output=True,
        text=True,
    )
    return r.returncode, r.stdout, r.stderr


class TestCoverLetterDistinctiveness(unittest.TestCase):
    def test_tool_exists(self):
        self.assertTrue(os.path.isfile(TOOL), f"real tool not found at {TOOL} -- nothing else in this file can mean anything without it")

    def test_positive_control_self_overlap(self):
        """A letter checked against itself must report full overlap (every six-gram
        shared) -- if this fails, the measure itself is broken, not the fixtures."""
        code, out, err = run("similar_1.html", "similar_1.html")
        self.assertEqual(code, 1, f"self-compare must report shared phrases (exit 1); got {code}\n{out}\n{err}")
        self.assertIn("control (self-overlap)", out)

    def test_distinct_letters_pass(self):
        """Two genuinely different letters must be reported distinct (exit 0, zero shared
        six-grams)."""
        code, out, err = run("distinct_1.html", "distinct_2.html")
        self.assertEqual(code, 0, f"expected genuinely distinct letters to pass; got exit {code}\n{out}\n{err}")
        self.assertIn("shared 6-grams: 0", out)

    def test_known_bad_near_duplicate_letters_are_rejected(self):
        """KNOWN-BAD CASE: two near-duplicate letters (identical template, only the company
        name and role swapped) are exactly what this gate exists to catch -- two
        applications at different companies that read as the same spray letter. The gate
        MUST reject this pair (exit 1, nonzero shared six-grams), not pass it."""
        code, out, err = run("similar_1.html", "similar_2.html")
        self.assertEqual(code, 1, f"KNOWN-BAD near-duplicate pair was NOT rejected -- the gate failed to catch spray-letter duplication\n{out}\n{err}")
        self.assertIn("shared 6-grams:", out)
        shared_line = [l for l in out.splitlines() if l.strip().startswith("shared 6-grams:")][0]
        shared_count = int(shared_line.split(":")[1].strip())
        self.assertGreater(shared_count, 10, f"expected a large shared six-gram count for a near-duplicate pair, got {shared_count}")

    def test_similar_pair_shares_more_than_distinct_pair(self):
        """Ordering sanity: the near-duplicate pair must share strictly more six-grams
        than the genuinely distinct pair (which should share zero)."""
        _, out_similar, _ = run("similar_1.html", "similar_2.html")
        _, out_distinct, _ = run("distinct_1.html", "distinct_2.html")
        similar_n = int([l for l in out_similar.splitlines() if "shared 6-grams:" in l][0].split(":")[1].strip())
        distinct_n = int([l for l in out_distinct.splitlines() if "shared 6-grams:" in l][0].split(":")[1].strip())
        self.assertGreater(similar_n, distinct_n)


if __name__ == "__main__":
    unittest.main()
