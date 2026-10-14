#!/usr/bin/env python3
# TEST: tools/common/config.py and config.example.yaml.
#
#   - resolution order: --config > $JOBSTACK_CONFIG > ./config.yaml > <repo>/config.yaml,
#     and NEVER config.example.yaml; nothing found -> SystemExit naming the cp command
#   - the YAML subset: flow lists parse, unsupported syntax is rejected loudly
#   - schema, both directions: every dotted key a tool reads exists in config.example.yaml,
#     and every leaf key in config.example.yaml is read by some tool
#   - the fictional persona is the same in config.example.yaml and templates/FACTS.example.md

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, REPO_ROOT)

from tools.common import config as C  # noqa: E402

EXAMPLE = os.path.join(REPO_ROOT, "config.example.yaml")
FACTS = os.path.join(REPO_ROOT, "templates", "FACTS.example.md")

# get(cfg, "a.b"), require(cfg, "a.b"), resolve_path(load_config(x), "a.b"), cfg_get("a.b", ...),
# tracker("a.b", ...): a known reader call whose first quoted argument is a dotted key
KEY_READ = re.compile(
    r"""\b(?:get|require|resolve_path|cfg_get|tracker)\((?:[^"'\n]*?,\s*)?["']([a-z0-9_]+(?:\.[a-z0-9_]+)+)["']"""
)
# f"candidate.{k}" style reads, expanded from the literal tuple they iterate
CONTACT_KEYS = ("city", "email", "phone", "linkedin", "website")


def tool_files():
    for d, _, files in os.walk(os.path.join(REPO_ROOT, "tools")):
        if "__pycache__" in d:
            continue
        for f in files:
            if f.endswith((".py", ".sh")):
                yield os.path.join(d, f)


def keys_read_by_tools():
    keys = set()
    for p in tool_files():
        if p.endswith(os.path.join("common", "config.py")):
            continue  # the loader's own docstring example is not a read
        with open(p, encoding="utf-8") as f:
            keys |= set(KEY_READ.findall(f.read()))
    keys |= {f"candidate.{k}" for k in CONTACT_KEYS}  # packetlib.contact_line()
    return keys


def leaf_keys(d, prefix=""):
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict) and v:
            yield from leaf_keys(v, key + ".")  # a read of the mapping itself counts (see below)
        else:
            yield key


def has_key(cfg, dotted):
    node = cfg
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


@contextlib.contextmanager
def isolated(cwd, env_value=None, repo_root=None):
    """Run with a given cwd, $JOBSTACK_CONFIG and REPO_ROOT, restoring all three after."""
    old_cwd, old_env, old_root = os.getcwd(), os.environ.get(C.ENV_VAR), C.REPO_ROOT
    os.chdir(cwd)
    if env_value is None:
        os.environ.pop(C.ENV_VAR, None)
    else:
        os.environ[C.ENV_VAR] = env_value
    if repo_root is not None:
        C.REPO_ROOT = C.Path(repo_root)
    try:
        yield
    finally:
        os.chdir(old_cwd)
        C.REPO_ROOT = old_root
        if old_env is None:
            os.environ.pop(C.ENV_VAR, None)
        else:
            os.environ[C.ENV_VAR] = old_env


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TestResolutionOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.repo, self.cwd = os.path.join(t, "repo"), os.path.join(t, "work")
        write(os.path.join(self.repo, "config.yaml"), 'who: "repo"\n')
        write(os.path.join(self.repo, "config.example.yaml"), 'who: "example"\n')
        write(os.path.join(self.cwd, "config.yaml"), 'who: "cwd"\n')
        self.envfile = os.path.join(t, "env.yaml")
        write(self.envfile, 'who: "env"\n')
        self.flagfile = os.path.join(t, "flag.yaml")
        write(self.flagfile, 'who: "flag"\n')

    def tearDown(self):
        self.tmp.cleanup()

    def who(self, explicit=None):
        return C.load_config(explicit)["who"]

    def test_flag_beats_everything(self):
        with isolated(self.cwd, self.envfile, self.repo):
            self.assertEqual(self.who(self.flagfile), "flag")

    def test_env_beats_cwd_and_repo(self):
        with isolated(self.cwd, self.envfile, self.repo):
            self.assertEqual(self.who(), "env")

    def test_cwd_beats_repo(self):
        with isolated(self.cwd, None, self.repo):
            self.assertEqual(self.who(), "cwd")

    def test_repo_root_is_last(self):
        os.remove(os.path.join(self.cwd, "config.yaml"))
        with isolated(self.cwd, None, self.repo):
            self.assertEqual(self.who(), "repo")

    def test_never_falls_back_to_the_example(self):
        os.remove(os.path.join(self.cwd, "config.yaml"))
        os.remove(os.path.join(self.repo, "config.yaml"))
        err = io.StringIO()
        with isolated(self.cwd, None, self.repo), self.assertRaises(SystemExit) as cm, \
                contextlib.redirect_stderr(err):
            C.load_config()
        self.assertIn("cp config.example.yaml config.yaml", str(cm.exception))

    def test_missing_explicit_path_is_an_error_not_a_fallthrough(self):
        with isolated(self.cwd, None, self.repo), self.assertRaises(SystemExit):
            C.load_config(os.path.join(self.tmp.name, "nope.yaml"))
        with isolated(self.cwd, os.path.join(self.tmp.name, "nope.yaml"), self.repo), \
                self.assertRaises(SystemExit):
            C.load_config()

    def test_relative_paths_resolve_against_the_config_file(self):
        write(self.flagfile, 'paths:\n  data_root: "./data"\n')
        with isolated(self.cwd, None, self.repo):
            cfg = C.load_config(self.flagfile)
        got = C.resolve_path(cfg, "paths.data_root")
        self.assertEqual(os.path.realpath(got), os.path.realpath(os.path.join(self.tmp.name, "data")))


class TestParser(unittest.TestCase):
    P = staticmethod(C.parse_yaml_lite)

    def test_nesting_scalars_and_comments(self):
        d = self.P('a:\n  b: "x # not a comment"  # a comment\n  c: 3\n  d: true\n  e: ~\nf: bare word\n')
        self.assertEqual(d, {"a": {"b": "x # not a comment", "c": 3, "d": True, "e": None}, "f": "bare word"})

    def test_flow_lists(self):
        d = self.P('a: []\nb: ["Carlito", "Liberation Sans"]\nc: [1, 2, 3]\nd: [\'x, y\', z]\n')
        self.assertEqual(d["a"], [])
        self.assertEqual(d["b"], ["Carlito", "Liberation Sans"])
        self.assertEqual(d["c"], [1, 2, 3])
        self.assertEqual(d["d"], ["x, y", "z"])

    def test_empty_block_is_an_empty_mapping(self):
        self.assertEqual(self.P("a:\nb: 1\n"), {"a": {}, "b": 1})

    def test_rejects_unsupported_syntax(self):
        bad = {
            "block list": "a:\n  - one\n  - two\n",
            "tab indent": "a:\n\tb: 1\n",
            "anchor": "a: &x 1\n",
            "alias": "a: *x\n",
            "block scalar": "a: |\n  text\n",
            "flow map": "a: {b: 1}\n",
            "nested list": "a: [[1], 2]\n",
            "multi-line list": 'a: ["x",\n  "y"]\n',
            "no key": "just a line\n",
            "bad indentation": "a:\n    b: 1\n  c: 2\n",
            "duplicate key": "a: 1\na: 2\n",
            "unterminated quote": 'a: "open\n',
            "document marker": "---\na: 1\n",
        }
        for name, text in bad.items():
            with self.subTest(name):
                with self.assertRaises(C.ConfigError):
                    self.P(text)

    def test_example_config_parses(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            cfg = self.P(f.read())
        self.assertEqual(cfg["candidate"]["name"], "Jordan Rivera")
        self.assertEqual(cfg["render"]["font_family"], "Carlito")


class TestSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(EXAMPLE, encoding="utf-8") as f:
            cls.cfg = C.parse_yaml_lite(f.read())
        cls.read = keys_read_by_tools()

    def test_the_grep_finds_reads(self):
        # control: the extractor must see the reads we know exist, or the next test proves nothing
        for k in ("candidate.name", "gates.banned_names_file", "sourcing.title_include_regex", "paths.queue_md"):
            self.assertIn(k, self.read)

    def test_every_key_a_tool_reads_is_in_the_example(self):
        missing = sorted(k for k in self.read if not has_key(self.cfg, k))
        self.assertEqual(missing, [], f"keys read by tools/ but absent from config.example.yaml: {missing}")

    def test_no_dead_keys_in_the_example(self):
        dead = []
        for k in leaf_keys(self.cfg):
            parts = k.split(".")
            ancestors = {".".join(parts[:i]) for i in range(1, len(parts) + 1)}
            if not ancestors & self.read:
                dead.append(k)
        self.assertEqual(dead, [], f"keys in config.example.yaml that no tool reads: {dead}")

    def test_example_gate_files_exist(self):
        for k in ("gates.banned_names_file", "gates.banned_claims_file", "gates.claim_rules_file", "gates.b9_rules_file"):
            p = C.resolve_path(self.cfg, k, base=REPO_ROOT)
            self.assertTrue(os.path.isfile(p), f"{k} points at a missing file: {p}")


class TestPersonaConsistency(unittest.TestCase):
    def test_config_and_facts_describe_the_same_person(self):
        with open(EXAMPLE, encoding="utf-8") as f:
            cand = C.parse_yaml_lite(f.read())["candidate"]
        with open(FACTS, encoding="utf-8") as f:
            facts = f.read()
        labels = {"name": "Name", "city": "Location", "email": "Email", "phone": "Phone",
                  "linkedin": "LinkedIn", "website": "Website"}
        for key, label in labels.items():
            with self.subTest(key):
                self.assertIn(f"- **{label}:** {cand[key]}\n", facts)


if __name__ == "__main__":
    unittest.main()
