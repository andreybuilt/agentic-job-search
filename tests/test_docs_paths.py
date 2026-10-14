#!/usr/bin/env python3
# TEST: every repo path a Markdown file names in backticks exists.
#
# A "repo path" is a backticked token that starts with one of the repo's top-level folders
# (tools/, templates/, docs/, tests/, scripts/, .github/) or is a root-level file name we
# ship (README.md, CLAUDE.md, config.example.yaml, ...). Only the first word counts, so
# `tools/x.py --flag` checks tools/x.py. Tokens with placeholders (<...>, *, ...) are skipped.
# Also checks that docs/PIPELINE.md's stage count matches its own diagram.

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
PREFIXES = ("tools/", "templates/", "docs/", "tests/", "scripts/", ".github/")
ROOT_FILES = {"README.md", "CLAUDE.md", "AGENTS.md", "LICENSE", "CHANGELOG.md", "SECURITY.md",
              "CONTRIBUTING.md", "config.example.yaml", "pyproject.toml", "requirements.txt"}
SKIP_FILES = {"BUILD_NOTES.md"}  # never ships
TICK = re.compile(r"`([^`\n]+)`")


def md_files():
    for d, dirs, files in os.walk(REPO_ROOT):
        dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", "fixtures")]
        for f in files:
            if f.endswith(".md") and f not in SKIP_FILES:
                yield os.path.join(d, f)


def candidates(text):
    for tok in TICK.findall(text):
        first = tok.strip().split()[0] if tok.strip() else ""
        first = first.rstrip(".,;:)")
        if any(c in first for c in "<>*{}$") or "..." in first:
            continue
        if first.startswith(PREFIXES) or first in ROOT_FILES:
            yield first


class TestDocPaths(unittest.TestCase):
    def test_the_extractor_finds_paths(self):
        found = set(candidates("see `tools/verify/claim_audit.py --rules x` and `README.md`, not `<file>`"))
        self.assertEqual(found, {"tools/verify/claim_audit.py", "README.md"})

    def test_every_backticked_repo_path_exists(self):
        missing = []
        for p in md_files():
            with open(p, encoding="utf-8") as f:
                text = f.read()
            for path in candidates(text):
                if not os.path.exists(os.path.join(REPO_ROOT, path)):
                    missing.append(f"{os.path.relpath(p, REPO_ROOT)}: {path}")
        self.assertEqual(missing, [], "paths named in docs that do not exist:\n" + "\n".join(missing))

    def test_pipeline_stage_count_matches_the_diagram(self):
        with open(os.path.join(REPO_ROOT, "docs", "PIPELINE.md"), encoding="utf-8") as f:
            text = f.read()
        nodes = set(re.findall(r"\b([A-Z])\[[^\]]+\]", text.split("```mermaid", 1)[1].split("```", 1)[0]))
        words = {8: "Eight", 9: "Nine", 10: "Ten"}
        self.assertTrue(text.startswith(f"# The pipeline\n\n{words[len(nodes)]} stages."),
                        f"diagram has {len(nodes)} stages")


if __name__ == "__main__":
    unittest.main()
