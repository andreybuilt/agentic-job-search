#!/usr/bin/env python3
# TEST: book_link.py's two-phase booking gate, with no browser and no network.
#
#   - the confirm code and the gate decision are pure functions: a matching code is allowed;
#     a changed field, a missing code, a different slot or a different URL is refused
#   - the real CalendlyBooking driver, run against a FAKE page object: the review phase
#     fills, reads every control back from the page, issues a code and never presses the
#     final button; the confirm phase reads back BEFORE the click; a field the page holds
#     differently from what was filled, or a slot rendered differently, never reaches click
#   - render.chrome_path is read after the config loads and is the binary tried first

import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, REPO_ROOT)
CONFIG = os.path.join(REPO_ROOT, "config.example.yaml")
TOOL = os.path.join(REPO_ROOT, "tools", "build", "book_link.py")

from tools.build import book_link as BL  # noqa: E402
from tools.build import browser_actions as B  # noqa: E402

URL = "https://calendly.com/example/intro"
SUBMIT = 'button[type="submit"]'


def rows(**actual):
    return [{"field": k, "intended": v, "actual": v, "ok": True} for k, v in actual.items()]


class TestGatePure(unittest.TestCase):
    RB = rows(name="Jordan Rivera", email="jordan.rivera@example.com")

    def code(self, url=URL, slot="2027-01-05T09:30:00-08:00", rb=None):
        return BL.confirm_code("book", url, slot, rb if rb is not None else self.RB)

    def test_code_is_ten_hex_and_stable(self):
        c = self.code()
        self.assertRegex(c, r"^[0-9a-f]{10}$")
        self.assertEqual(c, self.code())

    def test_match_is_allowed(self):
        ok, _ = BL.gate(self.code(), self.code(), self.RB)
        self.assertTrue(ok)
        ok, _ = BL.gate(self.code().upper(), self.code(), self.RB)
        self.assertTrue(ok, "a code typed back in upper case is the same code")

    def test_any_changed_field_is_refused(self):
        reviewed = self.code()
        for f in ("name", "email"):
            with self.subTest(f):
                rb = [dict(r) for r in self.RB]
                for r in rb:
                    if r["field"] == f:
                        r["actual"] = r["intended"] = r["actual"] + "x"
                ok, why = BL.gate(reviewed, self.code(rb=rb), rb)
                self.assertFalse(ok)
                self.assertIn("does not match", why)

    def test_added_or_removed_field_is_refused(self):
        reviewed = self.code()
        more = self.RB + rows(answer_q0="yes")
        self.assertFalse(BL.gate(reviewed, self.code(rb=more), more)[0])
        less = self.RB[:1]
        self.assertFalse(BL.gate(reviewed, self.code(rb=less), less)[0])

    def test_missing_code_is_refused(self):
        for supplied in (None, "", "   "):
            with self.subTest(repr(supplied)):
                ok, _ = BL.gate(supplied, self.code(), self.RB)
                self.assertFalse(ok)

    def test_different_slot_is_refused(self):
        reviewed = self.code(slot="2027-01-05T09:30:00-08:00")
        ok, _ = BL.gate(reviewed, self.code(slot="2027-01-05T10:00:00-08:00"), self.RB)
        self.assertFalse(ok)

    def test_different_url_is_refused(self):
        reviewed = self.code()
        ok, _ = BL.gate(reviewed, self.code(url="https://calendly.com/someone-else/intro"), self.RB)
        self.assertFalse(ok)

    def test_a_readback_mismatch_is_refused_even_with_a_matching_code(self):
        rb = [dict(r) for r in self.RB]
        rb[1]["actual"], rb[1]["ok"] = "Jordan.Rivera@example.com", False
        c = self.code(rb=rb)
        ok, why = BL.gate(c, c, rb)
        self.assertFalse(ok)
        self.assertIn("email", why)

    def test_an_empty_readback_is_refused(self):
        c = self.code(rb=[])
        self.assertFalse(BL.gate(c, c, [])[0])


# ---------------------------------------------------------------- fake page
class FakeLocator:
    def __init__(self, page, key, sel=None):
        self.page, self.key, self.sel = page, key, sel

    @property
    def first(self):
        return self

    def count(self):
        return 0 if self.sel in self.page.missing else 1

    def is_enabled(self):
        return True

    def click(self):
        self.page.log.append(("click", self.key))
        self.page.on_click(self.key)

    def fill(self, value):
        self.page.log.append(("fill", self.sel))
        self.page.values[self.sel] = self.page.mangle.get(self.sel, lambda v: v)(value)

    def input_value(self):
        self.page.log.append(("read", self.sel))
        return self.page.values.get(self.sel, "")


class FakePage:
    """Just enough of a Playwright Page for CalendlyBooking. Clicking the time button makes
    the form page render `slot_line`; clicking submit renders `after_submit`."""

    def __init__(self, slot_line="9:30am - 10:00am, Tuesday, January 5, 2027",
                 mangle=None, after_submit="You are scheduled!", missing=()):
        self.log, self.values, self.frames = [], {}, []
        self.slot_line, self.after_submit = slot_line, after_submit
        self.mangle, self.missing = dict(mangle or {}), set(missing)
        self.body = "Select a Day"

    def goto(self, url, **kw):
        self.log.append(("goto", url))

    def wait_for_timeout(self, ms):
        pass

    def wait_for_selector(self, sel, **kw):
        pass

    def inner_text(self, sel):
        return self.body

    def locator(self, sel, has_text=None):
        key = sel if has_text is None else f"{sel}|{getattr(has_text, 'pattern', has_text)}"
        return FakeLocator(self, key, sel)

    def get_by_role(self, role, name=None):
        return FakeLocator(self, f"role:{role}:{getattr(name, 'pattern', name)}")

    def on_click(self, key):
        if key.startswith("button[data-container=time-button]"):
            self.body = "Enter Details\n" + self.slot_line + "\nName\nEmail"
        elif key == SUBMIT:
            self.body = self.after_submit


class TestTwoPhaseFlowOnAFakePage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        BL._init_config(CONFIG)

    def start(self, s="2027-01-05T09:30"):
        return BL.parse_iso(s)

    def flow(self, page, supplied=None, start=None, record_dir=None, email="jordan.rivera@example.com"):
        start = start or self.start()
        drv = B.CalendlyBooking(page, URL, start, "Jordan Rivera", email, {"question_0": "Remote"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = BL.run_flow(drv, "book", URL, BL.slot_key(start=start), supplied, record_dir=record_dir)
        return rc, buf.getvalue()

    def review_code(self, record_dir=None):
        rc, out = self.flow(FakePage(), record_dir=record_dir)
        self.assertEqual(rc, BL.EXIT_REVIEWED, out)
        return re.search(r"CONFIRM CODE: ([0-9a-f]{10})", out).group(1)

    def test_review_reads_back_and_never_presses_the_final_button(self):
        page = FakePage()
        rc, out = self.flow(page)
        self.assertEqual(rc, BL.EXIT_REVIEWED, out)
        self.assertNotIn(("click", SUBMIT), page.log)
        reads = {s for k, s in page.log if k == "read"}
        self.assertEqual(reads, {'input[name="full_name"]', 'input[name="email"]', '[name="question_0"]'})
        self.assertIn("CONFIRM CODE:", out)
        self.assertIn("9:30am - 10:00am, Tuesday, January 5, 2027", out)

    def test_confirm_reads_back_before_the_click_then_reports_booked(self):
        code = self.review_code()
        page = FakePage()
        rc, out = self.flow(page, supplied=code)
        self.assertEqual(rc, BL.EXIT_BOOKED, out)
        self.assertIn("BOOKED", out)
        i_click = page.log.index(("click", SUBMIT))
        last_read = max(i for i, (k, _) in enumerate(page.log) if k == "read")
        last_fill = max(i for i, (k, _) in enumerate(page.log) if k == "fill")
        self.assertLess(last_fill, last_read)
        self.assertLess(last_read, i_click, "every read-back must happen before the final click")
        self.assertEqual(page.log.count(("click", SUBMIT)), 1)

    def test_a_field_the_page_changed_never_reaches_click(self):
        code = self.review_code()
        # the widget rewrote the email after fill (e.g. an autocomplete), so the page holds
        # something other than what the human approved
        page = FakePage(mangle={'input[name="email"]': lambda v: v.replace(".com", ".co")})
        rc, out = self.flow(page, supplied=code)
        self.assertEqual(rc, BL.EXIT_REFUSED, out)
        self.assertNotIn(("click", SUBMIT), page.log)
        # and the review of such a page issues no code at all
        page = FakePage(mangle={'input[name="email"]': lambda v: v.replace(".com", ".co")})
        rc, out = self.flow(page)
        self.assertEqual(rc, BL.EXIT_REFUSED, out)
        self.assertNotIn("CONFIRM CODE", out)

    def test_a_missing_control_never_reaches_click(self):
        page = FakePage(missing={'[name="question_0"]'})
        rc, out = self.flow(page)
        self.assertEqual(rc, BL.EXIT_REFUSED, out)
        rc, out = self.flow(FakePage(missing={'[name="question_0"]'}), supplied=self.review_code())
        self.assertEqual(rc, BL.EXIT_REFUSED, out)

    def test_a_different_rendered_slot_is_refused_with_a_diff(self):
        with tempfile.TemporaryDirectory() as rec:
            code = self.review_code(record_dir=rec)
            page = FakePage(slot_line="9:30am - 10:30am, Tuesday, January 5, 2027")
            rc, out = self.flow(page, supplied=code, record_dir=rec)
        self.assertEqual(rc, BL.EXIT_REFUSED, out)
        self.assertNotIn(("click", SUBMIT), page.log)
        self.assertIn("slot (as rendered): reviewed", out)

    def test_a_code_for_another_slot_is_refused(self):
        code = self.review_code()
        page = FakePage(slot_line="10:00am - 10:30am, Tuesday, January 5, 2027")
        rc, out = self.flow(page, supplied=code, start=self.start("2027-01-05T10:00"))
        self.assertEqual(rc, BL.EXIT_REFUSED, out)
        self.assertNotIn(("click", SUBMIT), page.log)

    def test_slot_not_shown_on_the_page_issues_no_code(self):
        page = FakePage(slot_line="10:00am - 10:30am, Tuesday, January 5, 2027")
        rc, out = self.flow(page)  # asked for 9:30, page shows 10:00
        self.assertEqual(rc, BL.EXIT_REFUSED, out)
        self.assertIn("NOT FOUND ON PAGE", out)

    def test_missing_code_never_reaches_click(self):
        page = FakePage()
        rc, out = self.flow(page, supplied="")
        self.assertEqual(rc, BL.EXIT_REFUSED, out)
        self.assertNotIn(("click", SUBMIT), page.log)

    def test_no_confirmation_text_is_unconfirmed(self):
        code = self.review_code()
        page = FakePage(after_submit="Something went wrong")
        rc, out = self.flow(page, supplied=code)
        self.assertEqual(rc, BL.EXIT_ERROR, out)
        self.assertIn("UNCONFIRMED", out)

    def test_rendered_start_only_matches_a_range_start(self):
        start = self.start("2027-01-05T10:00")
        self.assertEqual(B.find_rendered_start("9:30am - 10:00am, Tuesday, January 5, 2027", start), "")
        self.assertTrue(B.find_rendered_start("10:00am - 10:30am, Tuesday, January 5, 2027", start))


class FakeDriver:
    def __init__(self, log, rb):
        self.log, self.rb = log, rb

    def prepare(self):
        self.log.append("prepare")

    def read_back(self):
        self.log.append("read_back")
        return self.rb

    def click_final(self):
        self.log.append("click_final")

    def wait_confirmation(self):
        self.log.append("wait_confirmation")
        return "confirmed"


class TestRunFlowOrder(unittest.TestCase):
    def test_order_and_mismatch(self):
        rb = rows(name="A")
        code = BL.confirm_code("book", URL, "s", rb)
        log = []
        with redirect_stdout(io.StringIO()):
            self.assertEqual(BL.run_flow(FakeDriver(log, rb), "book", URL, "s", code), BL.EXIT_BOOKED)
        self.assertEqual(log, ["prepare", "read_back", "click_final", "wait_confirmation"])
        log = []
        with redirect_stdout(io.StringIO()):
            self.assertEqual(BL.run_flow(FakeDriver(log, rows(name="B")), "book", URL, "s", code), BL.EXIT_REFUSED)
        self.assertNotIn("click_final", log)
        log = []
        with redirect_stdout(io.StringIO()):
            self.assertEqual(BL.run_flow(FakeDriver(log, rb), "book", URL, "s", None), BL.EXIT_REVIEWED)
        self.assertNotIn("click_final", log)


# ---------------------------------------------------------------- chrome path (codex_r2 #5)
class FakeChromium:
    def __init__(self, fail_channel=False):
        self.calls, self.fail_channel = [], fail_channel

    def launch(self, **kw):
        self.calls.append(kw)
        if kw.get("channel") and self.fail_channel:
            raise RuntimeError("no chrome channel")
        return "browser"


class FakeP:
    def __init__(self, **kw):
        self.chromium = FakeChromium(**kw)


class TestChromePath(unittest.TestCase):
    def tearDown(self):
        BL._init_config(CONFIG)

    def test_nothing_is_computed_at_import(self):
        self.assertFalse(hasattr(BL, "CHROME"), "the Chrome path must not be a module constant read before config")

    def test_configured_chrome_path_is_used(self):
        with tempfile.TemporaryDirectory() as d:
            binary = os.path.join(d, "my-chrome")
            open(binary, "w").close()
            cfg = os.path.join(d, "config.yaml")
            with open(CONFIG, encoding="utf-8") as f:
                text = f.read()
            self.assertIn('chrome_path: ""', text)
            with open(cfg, "w", encoding="utf-8") as f:
                f.write(text.replace('chrome_path: ""', f'chrome_path: "{binary}"'))
            BL._init_config(cfg)
            self.assertEqual(BL.chrome_path(), binary)
            p = FakeP()
            B.launch(p, BL.chrome_path())
            self.assertEqual(p.chromium.calls[0], {"executable_path": binary, "headless": True},
                             "a configured binary is the first one tried")

    def test_unconfigured_falls_back_to_channel_then_bundled(self):
        p = FakeP(fail_channel=True)
        B.launch(p, "")
        self.assertEqual(p.chromium.calls, [{"channel": "chrome", "headless": True}, {"headless": True}])


class TestCli(unittest.TestCase):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, TOOL, "--config", CONFIG, *args],
                              capture_output=True, text=True, timeout=60)

    def test_plan_opens_nothing(self):
        r = self.run_tool("book", URL, "2027-01-05T10:00", "--name", "Jordan Rivera",
                          "--email", "jordan.rivera@example.com", "--plan")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("Nothing opened", r.stdout)
        self.assertIn("read back every filled control", r.stdout)

    def test_confirm_needs_a_code(self):
        r = self.run_tool("book", URL, "2027-01-05T10:00", "--name", "x", "--email", "x@example.com", "--confirm")
        self.assertEqual(r.returncode, 2)
        self.assertIn("expected one argument", r.stderr)

    def test_plan_and_confirm_are_exclusive(self):
        r = self.run_tool("book", URL, "2027-01-05T10:00", "--name", "x", "--email", "x@example.com",
                          "--plan", "--confirm", "abcdef0123")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not allowed with", r.stderr)


class TestAshbyRowMatch(unittest.TestCase):
    """Codex round 3: an Ashby row is matched by its START time, never by a range end."""

    def setUp(self):
        import datetime as dt
        from tools.build import browser_actions as ba
        self.ba = ba
        self.ten = dt.datetime(2027, 1, 5, 10, 0)

    def test_range_ending_at_the_slot_is_not_the_slot(self):
        self.assertFalse(self.ba.row_starts_at("9:30am - 10:00am  Book", self.ten))
        self.assertFalse(self.ba.row_starts_at("9:30am–10:00am Book", self.ten))

    def test_range_starting_at_the_slot_is_the_slot(self):
        self.assertTrue(self.ba.row_starts_at("10:00am - 10:30am  Book", self.ten))
        self.assertTrue(self.ba.row_starts_at("10:00 AM Book", self.ten))

    def test_no_time_or_other_time_is_not_the_slot(self):
        self.assertFalse(self.ba.row_starts_at("", self.ten))
        self.assertFalse(self.ba.row_starts_at("Book", self.ten))
        self.assertFalse(self.ba.row_starts_at("11:00am - 11:30am", self.ten))
        self.assertFalse(self.ba.row_starts_at("110:00am", self.ten))

    def test_prepare_picks_the_row_that_starts_at_the_slot(self):
        """Rows in page order: 9:30-10:00 first, then 10:00-10:30. The second must be chosen."""
        class Row:
            def __init__(self, text): self.text = text
            def inner_text(self): return self.text
        class Rows:
            def __init__(self, rows): self.rows = rows
            def count(self): return len(self.rows)
            def nth(self, i): return self.rows[i]
        rows = Rows([Row("9:30am - 10:00am Book"), Row("10:00am - 10:30am Book")])
        picked = next((rows.nth(i) for i in range(rows.count()) if self.ba.row_starts_at(rows.nth(i).inner_text(), self.ten)), None)
        self.assertIsNotNone(picked)
        self.assertEqual(picked.text, "10:00am - 10:30am Book")


if __name__ == "__main__":
    unittest.main()
