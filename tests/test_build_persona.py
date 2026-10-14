#!/usr/bin/env python3
# TEST: a packet built with someone else's config carries none of the example persona.
#
# Builds with tools/build/TEMPLATE_build.py against a temp data root whose bases are copies
# of the shipped templates, using a config for a different fictional person. The assembled
# resume and letter must carry that person's details and none of the example persona's.
# Also: a missing contact field stops the build, and no tool hardcodes the persona.

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
BUILD_DIR = os.path.join(REPO_ROOT, "tools", "build")
TEMPLATE_BUILD = os.path.join(BUILD_DIR, "TEMPLATE_build.py")
EXAMPLE_PERSONA = ("Jordan Rivera", "jordan.rivera", "555-010")
OTHER = {
    "name": "Casey Morgan", "email": "casey.morgan@example.com", "phone": "+44 1632 960000",
    "city": "Capital City, CC", "linkedin": "linkedin.com/in/casey-morgan-example",
    "website": "casey-morgan.example.com",
}


def make_config(path, data_root, drop=None):
    with open(os.path.join(REPO_ROOT, "config.example.yaml"), encoding="utf-8") as f:
        text = f.read()
    for key, value in OTHER.items():
        text = re.sub(rf'^(  {key}: ).*$', rf'\g<1>"{value}"', text, count=1, flags=re.M)
    if drop:
        text = re.sub(rf"^  {drop}: .*\n", "", text, count=1, flags=re.M)
    text = text.replace('data_root: "./data"', f'data_root: "{data_root}"')
    text = text.replace('"./tools/examples/', '"' + os.path.join(REPO_ROOT, "tools", "examples") + "/")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_data_root(root):
    os.makedirs(os.path.join(root, "_Packets"))
    shutil.copy(os.path.join(REPO_ROOT, "templates", "resume.example.html"),
                os.path.join(root, "_Packets", "BASE_Resume.html"))
    shutil.copy(os.path.join(REPO_ROOT, "templates", "cover_letter.example.html"),
                os.path.join(root, "_Packets", "BASE_CoverLetter.html"))
    jd = os.path.join(root, "ExampleCo", "270101_RoleSlug", "10_SOURCE", "270101-JD")
    os.makedirs(jd)
    with open(os.path.join(jd, "ExampleCo_RoleSlug_JD.md"), "w", encoding="utf-8") as f:
        f.write("# Role Title As Posted\n\n- **req:** `1234567` on **greenhouse**\n"
                "- **captured relative to submission:** AT BUILD TIME, before submission\n")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestBuildPersona(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = os.path.join(self.tmp.name, "data")
        make_data_root(self.data)
        self.cfg = os.path.join(self.tmp.name, "config.yaml")
        if BUILD_DIR not in sys.path:
            sys.path.insert(0, BUILD_DIR)

    def tearDown(self):
        self.tmp.cleanup()

    def test_other_persona_build_has_no_example_strings(self):
        make_config(self.cfg, self.data)
        T = load("template_build_under_test", TEMPLATE_BUILD)
        import packetlib as L
        PACKETS, cfg = T.build(self.cfg)
        resume, letter = L.assemble(PACKETS[0], cfg)
        both = resume + letter
        for s in EXAMPLE_PERSONA:
            self.assertNotIn(s, both, f"example persona string {s!r} leaked into a non-example build")
        for v in OTHER.values():
            self.assertIn(v, both, f"config value {v!r} missing from the build")
        self.assertIn('<span class="target">ExampleCo</span>', resume)

    def test_dry_run_cli_passes_outside_any_git_repo(self):
        make_config(self.cfg, self.data)
        r = subprocess.run([sys.executable, TEMPLATE_BUILD, "--config", self.cfg, "--dry"],
                           cwd=self.tmp.name, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dry ok: RoleSlug", r.stdout)

    def test_missing_contact_field_stops_the_build(self):
        make_config(self.cfg, self.data, drop="phone")
        r = subprocess.run([sys.executable, TEMPLATE_BUILD, "--config", self.cfg, "--dry"],
                           cwd=self.tmp.name, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("candidate.phone", r.stdout + r.stderr)

    def test_no_tool_hardcodes_the_example_persona(self):
        rx = re.compile(r"jordan|rivera|555-010|springfield", re.I)
        hits = []
        for d, _, files in os.walk(os.path.join(REPO_ROOT, "tools")):
            if "__pycache__" in d:
                continue
            for f in files:
                p = os.path.join(d, f)
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh, 1):
                        if rx.search(line):
                            hits.append(f"{os.path.relpath(p, REPO_ROOT)}:{n}")
        self.assertEqual(hits, [], f"example persona hardcoded in tools/: {hits}")


if __name__ == "__main__":
    unittest.main()
