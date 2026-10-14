#!/usr/bin/env python3
# TEST: smaller correctness fixes, each with its known-bad case.
#
#   - b9_check: the shipped example rules pass their own positive control (the control
#     builder used to turn "\bGlobex" into "bGlobex", so every first run was INVALID)
#   - b9_check: a rule the control cannot satisfy still makes the run INVALID (exit 2)
#   - sweep.probe: a 404 on every ATS is "no-board"; a network error is "error", never
#     "no-board"; one real board wins over errors elsewhere. No network is used.
#   - claim_audit prints the packet folder name and full file names

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools", "verify"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools", "sourcing"))

import b9_check  # noqa: E402
import sweep  # noqa: E402

B9_RULES = os.path.join(REPO_ROOT, "tools", "examples", "b9_check_rules.example.yaml")


class TestB9Control(unittest.TestCase):
    def test_example_rules_pass_their_own_control(self):
        banned, _ = b9_check.load_rules(B9_RULES)
        control = b9_check.build_control_string(banned)
        import re
        missed = [k for k, rx in banned.items() if not re.search(rx, control, re.I)]
        self.assertEqual(missed, [], f"control string {control!r} missed {missed}")

    def test_escapes_become_literals_or_spaces(self):
        c = b9_check.build_control_string({"a": r"\bGlobex\b", "b": r"\b99\.9%\s*uptime", "c": r"\(ref\)"})
        self.assertIn("Globex", c)
        self.assertNotIn("bGlobex", c)
        self.assertIn("99.9% uptime", c)
        self.assertIn("(ref)", c)

    def test_cli_example_rules_exit_zero(self):
        r = subprocess.run([sys.executable, os.path.join(REPO_ROOT, "tools", "verify", "b9_check.py"),
                            "--rules", B9_RULES], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("rules fired", r.stdout)

    def test_unsatisfiable_control_is_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "rules.yaml")
            with open(p, "w", encoding="utf-8") as f:
                f.write('banned:\n  - label: "lookahead only"\n    pattern: "(?=never)x"\n')
            r = subprocess.run([sys.executable, os.path.join(REPO_ROOT, "tools", "verify", "b9_check.py"),
                                "--rules", p], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("INVALID RUN", r.stdout)


def reader(result):
    def f(slug):
        if isinstance(result, Exception):
            raise result
        return result
    f.__name__ = "fake"
    return f


class TestSweepProbe(unittest.TestCase):
    def test_all_404_is_no_board(self):
        _, status, found, rows, errors = sweep.probe("x", readers=(reader(None), reader(None)))
        self.assertEqual(status, "no-board")

    def test_network_error_is_not_no_board(self):
        _, status, found, rows, errors = sweep.probe(
            "x", readers=(reader(None), reader(sweep.BoardError("URLError: refused"))))
        self.assertEqual(status, "error")
        self.assertTrue(errors)

    def test_a_board_wins(self):
        row = dict(ats="greenhouse", slug="x", req="1", title="t", locs=[], remote=False, comp="", url="")
        _, status, found, rows, errors = sweep.probe(
            "x", readers=(reader([row]), reader(sweep.BoardError("HTTP 503"))))
        self.assertEqual(status, "board")
        self.assertEqual(len(rows), 1)

    def test_get_json_maps_errors(self):
        # a dead proxy gives a URLError: must be BoardError, never None ("no board")
        env = dict(os.environ, HTTPS_PROXY="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9")
        code = ("import sys; sys.path.insert(0, %r); import sweep\n"
                "try:\n    sweep.get_json('https://boards-api.greenhouse.io/v1/boards/x/jobs'); print('NONE')\n"
                "except sweep.BoardError: print('BOARDERROR')\n") % os.path.join(REPO_ROOT, "tools", "sourcing")
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
        self.assertIn("BOARDERROR", r.stdout, r.stderr)


class TestClaimAuditLabel(unittest.TestCase):
    def test_label_names_the_packet_and_files(self):
        r = subprocess.run([sys.executable, os.path.join(REPO_ROOT, "tools", "verify", "claim_audit.py"),
                            os.path.join(REPO_ROOT, "tests", "fixtures", "claim_audit", "good_packet"),
                            "--rules", os.path.join(REPO_ROOT, "tools", "examples", "claim_audit_rules.example.yaml")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("good_packet: 0 problem(s)", r.stdout)
        self.assertIn("[Resume_v1.txt + CoverLetter_v1.txt]", r.stdout)


if __name__ == "__main__":
    unittest.main()
