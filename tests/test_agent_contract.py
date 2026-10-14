#!/usr/bin/env python3
# TEST: the agent operating contract is one text, and the code honors it.
#
#   - CLAUDE.md and AGENTS.md are identical apart from the one-line filename note
#   - the safety contract sentence, and the booking sentence, are word-for-word the same
#     in every doc that states them
#   - ARCHITECTURAL BOUNDARY: every browser call lives in tools/build/browser_actions.py.
#     An AST scan of every other Python file under tools/ fails on a playwright import or
#     any browser mutation call; a text scan covers .sh and .js files. Inside
#     browser_actions.py, the final button is pressed only in methods named click_final.
#   - book_link.py decides whether click_final may run; the behavioural proof that read-back
#     precedes the click and that a mismatch never clicks is in tests/test_book_link.py.
#
# This is a review aid, not a guarantee. A static scan can be evaded (exec of a built
# string, a renamed module). It makes the boundary visible and catches the ordinary ways
# of crossing it; a reviewer still reads browser_actions.py.

import ast
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))

CONTRACT = ("The final submit is the human's. Either the human clicks it, or, after reviewing the "
            "agent's field-by-field read-back, the human gives an explicit go for THAT ONE submission "
            "and the agent clicks. No standing permission. CAPTCHAs, sign-ins, e-signatures, payments: "
            "human only, always.")
BOOKING = ("`book_link --confirm <code>` is the human's explicit go for that one booking, "
           "given after reading the read-back.")

BROWSER_MODULE = os.path.join("tools", "build", "browser_actions.py")
BOOK_LINK = os.path.join("tools", "build", "book_link.py")

# Methods that change a page. Called on anything, outside browser_actions.py, they fail.
MUTATORS = {"click", "dblclick", "tap", "press", "press_sequentially", "type", "fill", "clear",
            "check", "uncheck", "set_checked", "select_option", "set_input_files",
            "dispatch_event", "drag_to", "drag_and_drop", "request_submit"}
EVALUATORS = {"evaluate", "evaluate_handle", "eval_on_selector", "eval_on_selector_all",
              "add_script_tag", "add_init_script"}
JS_ACTION = re.compile(r"click|submit|requestSubmit", re.I)
TEXT_ACTION = re.compile(r"playwright|puppeteer|selenium|requestSubmit|form\.submit|\.submit\(\)|\.click\(", re.I)


def read(rel):
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def flat(text):
    return re.sub(r"\s+", " ", text)


def _const_strings(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def browser_violations(source, filename="<src>"):
    """Every browser import or mutation call in `source`, as 'line: what' strings."""
    out = []
    for n in ast.walk(ast.parse(source, filename)):
        if isinstance(n, ast.Import):
            out += [f"{n.lineno}: import {a.name}" for a in n.names
                    if a.name.split(".")[0] in ("playwright", "selenium", "pyppeteer")]
        elif isinstance(n, ast.ImportFrom) and n.module and \
                n.module.split(".")[0] in ("playwright", "selenium", "pyppeteer"):
            out.append(f"{n.lineno}: from {n.module} import ...")
        elif isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
            if isinstance(f, ast.Attribute) and name in MUTATORS:
                out.append(f"{n.lineno}: .{name}(...)")
            elif name in EVALUATORS and any(JS_ACTION.search(s) for s in _const_strings(n)):
                out.append(f"{n.lineno}: {name}(...) with a click/submit script")
            elif name in ("__import__", "import_module") and any(
                    s.split(".")[0] in ("playwright", "selenium", "pyppeteer") for s in _const_strings(n)):
                out.append(f"{n.lineno}: dynamic import of a browser driver")
            elif name == "getattr" and any(s in MUTATORS for s in _const_strings(n)):
                out.append(f"{n.lineno}: getattr(..., mutator)")
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and \
                re.search(r"requestSubmit|form\.submit\s*\(", n.value):
            out.append(f"{getattr(n, 'lineno', '?')}: script text that submits a form")
    return out


def tool_files(exts):
    for d, _, files in os.walk(os.path.join(REPO_ROOT, "tools")):
        if "__pycache__" in d:
            continue
        for f in sorted(files):
            if f.endswith(exts):
                p = os.path.join(d, f)
                yield os.path.relpath(p, REPO_ROOT), p


class TestContract(unittest.TestCase):
    def test_claude_and_agents_differ_only_in_the_filename_note(self):
        a, b = read("CLAUDE.md").splitlines(), read("AGENTS.md").splitlines()
        self.assertEqual(len(a), len(b))
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(len(diff), 1, f"expected exactly one differing line, got {diff}")
        x, y = diff[0]
        self.assertIn("This file is `CLAUDE.md`", x)
        self.assertIn("This file is `AGENTS.md`", y)

    def test_safety_contract_is_word_for_word_identical(self):
        for rel in ("CLAUDE.md", "AGENTS.md", os.path.join("docs", "MULTI_AGENT.md"), "README.md"):
            with self.subTest(rel):
                self.assertIn(CONTRACT, flat(read(rel)))

    def test_booking_sentence_is_word_for_word_identical(self):
        for rel in ("CLAUDE.md", "AGENTS.md", "README.md", "CONTRIBUTING.md",
                    os.path.join("docs", "PIPELINE.md"), BOOK_LINK):
            with self.subTest(rel):
                self.assertIn(BOOKING, flat(read(rel)))


class TestBrowserBoundary(unittest.TestCase):
    def test_the_detector_fires(self):
        """Control: each shape the boundary exists to stop is caught."""
        bad = [
            'import playwright',
            'from playwright.sync_api import sync_playwright',
            'import importlib; importlib.import_module("playwright.sync_api")',
            '__import__("playwright")',
            'pg.locator("#apply").click()',
            'pg.get_by_role("button", name="Submit").click()',
            'pg.click(\'button[type="submit"]\')',
            'pg.fill("#email", "x")',
            'pg.keyboard.press("Enter")',
            'loc.check()',
            'loc.select_option("x")',
            'loc.dispatch_event("click")',
            'loc.type("x")',
            'pg.evaluate("el => el.click()")',
            'pg.evaluate("document.forms[0].requestSubmit()")',
            'js = "document.querySelector(\'form\').requestSubmit()"',
            'getattr(btn, "click")()',
        ]
        for src in bad:
            with self.subTest(src):
                self.assertTrue(browser_violations(src), f"not caught: {src}")
        for src in ('subprocess.check_call(["ls"])', 'x = "submitted"', 'pg.evaluate("1+1")',
                    'json.loads("{}")', 're.compile("Submit")'):
            with self.subTest(clean=src):
                self.assertEqual(browser_violations(src), [], src)

    def test_no_browser_code_outside_browser_actions(self):
        hits = []
        for rel, p in tool_files((".py",)):
            if rel == BROWSER_MODULE:
                continue
            with open(p, encoding="utf-8") as fh:
                hits += [f"{rel}:{v}" for v in browser_violations(fh.read(), rel)]
        for rel, p in tool_files((".sh", ".js", ".mjs", ".ts")):
            with open(p, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if TEXT_ACTION.search(line) and not line.lstrip().startswith("#"):
                        hits.append(f"{rel}:{n}: {line.strip()}")
        self.assertEqual(hits, [], "browser code outside tools/build/browser_actions.py:\n" + "\n".join(hits))

    def test_browser_actions_is_where_the_browser_code_is(self):
        # control for the scan above: the module it exempts really does hold the browser code
        self.assertTrue(browser_violations(read(BROWSER_MODULE)))

    def test_final_clicks_only_in_click_final(self):
        """Inside browser_actions.py, a press of a submit button or a Book button happens only
        in a method named click_final, which book_link.run_flow reaches only through gate()."""
        tree = ast.parse(read(BROWSER_MODULE))
        final = re.compile(r'type=["\']?submit|^Book$')
        bad = []

        def walk(node, fn):
            for child in ast.iter_child_nodes(node):
                name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else fn
                if isinstance(child, ast.Constant) and isinstance(child.value, str) and final.search(child.value):
                    if fn != "click_final":
                        bad.append(f"line {child.lineno} in {fn}: {child.value!r}")
                walk(child, name)
        walk(tree, "<module>")
        self.assertEqual(bad, [])
        self.assertGreaterEqual(read(BROWSER_MODULE).count("def click_final("), 3)

    def test_book_link_calls_click_final_only_after_gate(self):
        src = read(BOOK_LINK)
        body = src[src.index("def run_flow("):]
        body = body[: body.index("\ndef ", 1)]
        i_read, i_gate, i_click = (body.index("driver.read_back()"), body.index("gate(supplied"),
                                   body.index("driver.click_final()"))
        self.assertLess(i_read, i_gate)
        self.assertLess(i_gate, i_click)
        self.assertEqual(src.count("click_final()"), 1, "book_link must press the final button in one place only")

    def test_plan_opens_no_browser(self):
        r = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, BOOK_LINK), "--config", os.path.join(REPO_ROOT, "config.example.yaml"),
             "book", "https://calendly.com/example/intro", "2027-01-05T10:00",
             "--name", "Jordan Rivera", "--email", "jordan.rivera@example.com", "--plan"],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("Nothing opened", r.stdout)


if __name__ == "__main__":
    unittest.main()
