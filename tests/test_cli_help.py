#!/usr/bin/env python3
# TEST: every executable tool under tools/ (and scripts/demo.sh) answers --help:
#   exit 0, prints usage text, needs no config, uses no network, writes no files.
#
# "No config" is proved by pointing $JOBSTACK_CONFIG at a path that does not exist: any
# tool that tried to load its config would exit non-zero. "No network" is proved by routing
# HTTP(S) through a dead proxy. "No writes" is proved by snapshotting the repo tree and the
# working directory before and after.

import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))


def executables():
    out = []
    for d, _, files in os.walk(os.path.join(REPO_ROOT, "tools")):
        if "__pycache__" in d:
            continue
        for f in sorted(files):
            if f.endswith((".py", ".sh")):
                out.append(os.path.join(d, f))
    out.append(os.path.join(REPO_ROOT, "scripts", "demo.sh"))
    return sorted(out)


def snapshot(root):
    seen = set()
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in (".git", "__pycache__")]
        for f in files:
            p = os.path.join(d, f)
            seen.add((p, os.path.getmtime(p)))
    return seen


class TestHelp(unittest.TestCase):
    def test_tool_list_is_not_empty(self):
        self.assertGreater(len(executables()), 20)

    def test_every_tool_answers_help(self):
        env = dict(os.environ)
        env.update(JOBSTACK_CONFIG="/nonexistent/ajs-help-test/config.yaml",
                   HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
                   http_proxy="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9",
                   PYTHONDONTWRITEBYTECODE="1")
        env.pop("JOBSTACK_DATA_ROOT", None)
        before = snapshot(REPO_ROOT)
        with tempfile.TemporaryDirectory() as cwd:
            for tool in executables():
                rel = os.path.relpath(tool, REPO_ROOT)
                cmd = ["bash", tool, "--help"] if tool.endswith(".sh") else [sys.executable, tool, "--help"]
                with self.subTest(rel):
                    r = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
                    self.assertEqual(r.returncode, 0, f"{rel} --help exited {r.returncode}\n{r.stdout}\n{r.stderr}")
                    self.assertGreater(len(r.stdout.strip()), 40, f"{rel} --help printed almost nothing")
                    self.assertNotIn("Traceback", r.stdout + r.stderr)
            self.assertEqual(os.listdir(cwd), [], "a --help run wrote files into the working directory")
        self.assertEqual(snapshot(REPO_ROOT), before, "a --help run changed files in the repo")


if __name__ == "__main__":
    unittest.main()
