#!/usr/bin/env python3
# TEST: forbidden-name scan, against the REAL tool (tools/verify/verify_readback.py)
#
# No fallback/reference implementation. If the real tool is missing or its function
# signatures change, this test fails loudly rather than silently passing against a
# stand-in that proves nothing about the shipped gate.
#
# Also exercises tools/build/forbidden_names_gate.py's pattern()/load_names() directly
# (both gates read the same plain names list, config key gates.banned_names_file)
# (pure regex, no PDF/pdftotext dependency needed for this part).
#
# Cases:
#   - KNOWN-BAD: a packet whose rendered cover letter contains a planted banned name
#     (from a fixture banned-names list) must be caught as an error by verify_readback's
#     check().
#   - KNOWN-GOOD: a clean packet with no banned name must produce zero banned-name errors.
#   - case-insensitivity and whole-word boundary behavior of forbidden_names_gate.pattern().

import importlib.util
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
VERIFY_READBACK = os.path.join(REPO_ROOT, "tools", "verify", "verify_readback.py")
FORBIDDEN_GATE = os.path.join(REPO_ROOT, "tools", "build", "forbidden_names_gate.py")
BANNED_CLAIMS_EXAMPLE = os.path.join(REPO_ROOT, "tools", "examples", "banned_claims.example.yaml")
BANNED_NAMES_FIXTURE = os.path.join(FIXTURES, "banned_names.fixture.txt")


def _load_module(path, name):
    if not os.path.isfile(path):
        raise unittest.SkipTest(f"required tool missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestVerifyReadbackBannedNames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load_module(VERIFY_READBACK, "verify_readback")
        cls.names = cls.m.load_banned_names(BANNED_NAMES_FIXTURE)
        cls.phrases = cls.m.load_banned_phrases(BANNED_CLAIMS_EXAMPLE)

    def test_known_bad_planted_name_is_caught(self):
        """KNOWN-BAD CASE: a cover letter that leaked a banned name must be flagged as an
        error, not a warning, not silence."""
        r = self.m.check(os.path.join(FIXTURES, "packets", "banned_packet"), self.names, self.phrases)
        banned_hits = [e for e in r["errors"] if e.startswith("BANNED NAME")]
        self.assertTrue(
            banned_hits,
            f"KNOWN-BAD fixture (a planted banned name in the rendered cover letter) was NOT caught. "
            f"errors were: {r['errors']}",
        )
        self.assertIn("globex-project-nightingale", banned_hits[0])

    def test_known_good_clean_packet_has_no_banned_name_errors(self):
        """A packet with no banned name present must not be flagged -- otherwise the gate
        is crying wolf and will get ignored."""
        r = self.m.check(os.path.join(FIXTURES, "packets", "clean_packet"), self.names, self.phrases)
        banned_hits = [e for e in r["errors"] if e.startswith("BANNED NAME")]
        self.assertEqual(banned_hits, [], f"clean packet was incorrectly flagged: {banned_hits}")

    def test_refuses_on_empty_names_list(self):
        """Fail-closed: an empty banned-names file must refuse (SystemExit), never
        silently check nothing."""
        with tempfile.TemporaryDirectory() as d:
            empty = os.path.join(d, "empty_names.txt")
            open(empty, "w").close()
            with self.assertRaises(SystemExit):
                self.m.load_banned_names(empty)


class TestForbiddenNamesGatePattern(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = _load_module(FORBIDDEN_GATE, "forbidden_names_gate")

    def test_known_bad_name_matches_case_insensitively(self):
        """KNOWN-BAD CASE: the banned name, in different case and with normal word
        spacing around it, must still match."""
        rx = self.m.pattern("globex-project-nightingale")
        self.assertIsNotNone(rx.search("supporting GLOBEX-PROJECT-NIGHTINGALE, a confidential initiative"))

    def test_known_good_text_does_not_match(self):
        """Clean text with no banned name present must not match."""
        rx = self.m.pattern("globex-project-nightingale")
        self.assertIsNone(rx.search("supporting the deployment pipeline migration at Acme Corp"))

    def test_whole_word_boundary_does_not_false_positive(self):
        """A short banned name must not match as a substring of an unrelated longer word
        -- e.g. a banned name 'lume' must not match inside 'volume'."""
        rx = self.m.pattern("lume")
        self.assertIsNone(rx.search("the script raises the volume of requests slowly"))
        self.assertIsNotNone(rx.search("we are not allowed to mention Lume by name"))

    def test_load_names_refuses_on_comment_only_list(self):
        """Fail-closed: a names file holding only comments must refuse."""
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "names.txt")
            with open(bad, "w") as f:
                f.write("# just a comment, no names\n")
            with self.assertRaises(SystemExit):
                self.m.load_names(bad)

    def test_load_names_reads_the_shared_plain_list(self):
        """The render gate reads the SAME plain list verify_readback reads."""
        names = self.m.load_names(BANNED_NAMES_FIXTURE)
        self.assertIn("globex-project-nightingale", names)

    def test_refuses_on_missing_file(self):
        with self.assertRaises(SystemExit):
            self.m.load_names(os.path.join(FIXTURES, "does_not_exist.txt"))


if __name__ == "__main__":
    unittest.main()
