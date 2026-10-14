#!/usr/bin/env python3
"""browser_actions.py - the ONE module in this repo that drives a browser.

Every Playwright import, every page navigation, every fill, every select change and every
click lives here, and nowhere else under tools/. tests/test_agent_contract.py parses every
other Python file under tools/ and fails if it imports playwright or calls a browser
mutation method (.click, .fill, .press, .check, .select_option, .dispatch_event, .type,
an evaluate() that clicks or submits, requestSubmit, form.submit). That makes the
boundary easy to review: to see everything this toolkit can do in a browser, read this
file. It is a review aid, not a guarantee: a determined contributor can still write code
that evades a static check, which is why the boundary is also documented in CONTRIBUTING.md.

Inside this file, the irreversible click (the one that books a slot or submits a form) is
made only in a method named click_final(), and tools/build/book_link.py calls click_final()
only after it has read back every filled control from the page and the human's confirm code
matches that read-back. The test suite checks both.

Contents:
  launch(), session()        start headless Chrome/Chromium (render.chrome_path honored)
  render_html_to_pdf()       the Playwright fallback used by render_pdf.py
  calendly_slots(), ashby_slots()
                             read-only slot listing (navigates calendars, fills nothing)
  CalendlyBooking, AshbyBooking, AshbyAvailability
                             prepare() opens the page and fills the controls,
                             read_back() reads each control's ACTUAL value from the DOM,
                             click_final() presses the final button,
                             wait_confirmation() returns the confirmation text or None.

Page content is untrusted data: nothing here acts on page text beyond matching the known
controls and the known confirmation phrases.

This is a library. `python3 browser_actions.py --help` prints this text and exits.
"""
import contextlib
import datetime as dt
import re
from pathlib import Path

UA_TIMEOUT = 60000


# ---------------------------------------------------------------- pure helpers
def iso(t, tz):
    return t.astimezone(tz).isoformat()


def parse_iso(s, tz):
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=tz)
    return t.astimezone(tz)


def time_label(t):
    """9:30am style label as Calendly/Ashby render it."""
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d}{'am' if t.hour < 12 else 'pm'}"


TIME_TOKEN = re.compile(r"(?<![\d:])(\d{1,2}:\d{2}\s*[ap]m)", re.I)


def row_starts_at(row_text, start):
    """True when the FIRST time shown in a slot row is `start`. A row like
    '9:30am - 10:00am' therefore never counts as the 10:00am slot: 10:00am is its END."""
    m = TIME_TOKEN.search(row_text or "")
    return bool(m) and re.sub(r"\s+", "", m.group(1)).lower() == time_label(start).lower()


def find_rendered_start(body, start):
    """The line of page text that shows `start` as the START of a time range on the right
    date, e.g. '9:30am - 10:00am, Tuesday, January 5, 2027'. '' when there is none.
    A label only counts when a dash follows it, so the END of another range never matches."""
    tl = time_label(start)
    day = f"{start:%B} {start.day}"
    pat = re.compile(rf"(?<![\d:]){re.escape(tl)}\s*[-–—]", re.I)
    for line in body.splitlines():
        if pat.search(line) and day in line:
            return line.strip()[:200]
    return ""


# ---------------------------------------------------------------- browser start
def launch(p, chrome_path=""):
    """Start headless Chrome. A configured render.chrome_path (passed in as chrome_path)
    is tried first; then Playwright's installed-Chrome channel; then bundled Chromium."""
    if chrome_path and Path(chrome_path).exists():
        try:
            return p.chromium.launch(executable_path=chrome_path, headless=True)
        except Exception:
            pass
    try:
        return p.chromium.launch(channel="chrome", headless=True)
    except Exception:
        return p.chromium.launch(headless=True)


@contextlib.contextmanager
def session(chrome_path, tz_name):
    """Yields one fresh page in its own context; closes the browser on every exit path."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = launch(p, chrome_path)
        try:
            ctx = b.new_context(timezone_id=tz_name, locale="en-US",
                                viewport={"width": 1280, "height": 1000})
            yield ctx.new_page()
        finally:
            b.close()


def render_html_to_pdf(src_abs, out_abs):
    """Render a local HTML file to PDF with Playwright's bundled Chromium. Raises ImportError
    when Playwright is not installed; render_pdf.py turns that into a refusal."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{src_abs}")
        page.pdf(path=out_abs, print_background=True)
        browser.close()


class Captcha(Exception):
    pass


def check_captcha(pg):
    """A visible challenge frame (reCAPTCHA bframe, hCaptcha, Cloudflare) = captcha.
    The invisible reCAPTCHA anchor Calendly always loads does NOT count."""
    for f in pg.frames:
        u = f.url
        if any(k in u for k in ("recaptcha/api2/bframe", "recaptcha/enterprise/bframe",
                                 "hcaptcha.com/captcha", "challenges.cloudflare.com")):
            try:
                el = f.frame_element()
                box = el.bounding_box()
                if box and box["width"] > 50 and box["height"] > 50 and el.is_visible():
                    raise Captcha(u[:80])
            except Captcha:
                raise
            except Exception:
                continue
    body = ""
    try:
        body = pg.inner_text("body")[:4000].lower()
    except Exception:
        pass
    if "verify you are human" in body or "are you a robot" in body:
        raise Captcha("text challenge")


def save_proof(pg, d, name):
    (d / f"{name}.txt").write_text(pg.inner_text("body"))
    pg.screenshot(path=str(d / f"{name}.png"), full_page=True)


def _row(field, intended, actual, ok=None):
    return {"field": field, "intended": str(intended), "actual": str(actual),
            "ok": (str(intended) == str(actual)) if ok is None else bool(ok)}


# ---------------------------------------------------------------- calendly
def calendly_slots(pg, url, days, tz):
    ranges, lookup = [], {}

    def on_resp(r):
        try:
            if "/calendar/range" in r.url:
                ranges.append(r.json())
            elif "/event_types/lookup" in r.url:
                lookup.update(r.json())
        except Exception:
            pass

    pg.on("response", on_resp)
    pg.goto(url, wait_until="networkidle", timeout=UA_TIMEOUT)
    pg.wait_for_timeout(1500)
    check_captcha(pg)
    end = dt.datetime.now(tz).date() + dt.timedelta(days=days)
    # the page fetches one month at a time; step forward until the window is covered
    for _ in range(4):
        last = max((d["date"] for r in ranges for d in r.get("days", [])), default=None)
        if last and dt.date.fromisoformat(last) >= end:
            break
        nxt = pg.locator('button[aria-label="Go to next month"]')
        if nxt.count() == 0 or not nxt.first.is_enabled():
            break
        n = len(ranges)
        nxt.first.click()
        for _ in range(20):
            if len(ranges) > n:
                break
            pg.wait_for_timeout(250)
    dur = int(lookup.get("duration") or 30)
    seen, out = set(), []
    for r in ranges:
        for d in r.get("days", []):
            for s in d.get("spots", []):
                if s.get("status") != "available":
                    continue
                st = parse_iso(s["start_time"], tz)
                if st.date() > end or st in seen:
                    continue
                seen.add(st)
                out.append({"start": iso(st, tz), "end": iso(st + dt.timedelta(minutes=dur), tz)})
    out.sort(key=lambda x: x["start"])
    meta = {"provider": "calendly", "event": lookup.get("name"), "duration_min": dur,
            "status": "open" if out else "no_slots"}
    return out, meta


class CalendlyBooking:
    """One Calendly booking. prepare() fills; read_back() reads; click_final() books."""

    def __init__(self, pg, url, start, name, email, answers):
        self.pg, self.url, self.start = pg, url, start
        self.name, self.email, self.answers = name, email, dict(answers or {})
        self.filled = []  # (field label, selector, intended value)

    def prepare(self):
        pg, start = self.pg, self.start
        base = self.url.split("?")[0]
        pg.goto(f"{base}?month={start:%Y-%m}&date={start:%Y-%m-%d}",
                wait_until="networkidle", timeout=UA_TIMEOUT)
        check_captcha(pg)
        day = f"{start:%A}, {start:%B} {start.day} - Times available"
        btn = pg.locator(f'button[aria-label="{day}"]')
        if btn.count():
            btn.first.click()
        tl = time_label(start)
        pg.locator("button[data-container=time-button]",
                   has_text=re.compile(rf"^\s*{re.escape(tl)}\s*$")).first.click()
        pg.get_by_role("button", name=re.compile(r"^Next")).first.click()
        pg.wait_for_selector('input[name="full_name"], input[name="name"]', timeout=UA_TIMEOUT)
        check_captcha(pg)
        name_sel = 'input[name="full_name"]' if pg.locator('input[name="full_name"]').count() else 'input[name="name"]'
        self.filled = [("name", name_sel, self.name), ("email", 'input[name="email"]', self.email)]
        self.filled += [(f"answer {k}", f'[name="{k}"]', str(v)) for k, v in self.answers.items()]
        for _label, sel, value in self.filled:
            loc = self.pg.locator(sel)
            if loc.count():
                loc.first.fill(value)

    def read_back(self):
        """Every filled control's ACTUAL value, read from the DOM after filling, plus the
        slot as the page renders it. A control that is missing reads back as ''."""
        rows = []
        for label, sel, value in self.filled:
            loc = self.pg.locator(sel)
            actual = loc.first.input_value() if loc.count() else ""
            rows.append(_row(label, value, actual))
        rendered = find_rendered_start(self.pg.inner_text("body"), self.start)
        rows.insert(0, _row("slot (as rendered)", f"starts {time_label(self.start)} on "
                            f"{self.start:%B} {self.start.day}", rendered or "NOT FOUND ON PAGE",
                            ok=bool(rendered)))
        return rows

    def click_final(self):
        self.pg.locator('button[type="submit"]').first.click()

    def wait_confirmation(self):
        for _ in range(60):
            self.pg.wait_for_timeout(500)
            check_captcha(self.pg)
            body = self.pg.inner_text("body")
            if "You are scheduled" in body:
                return "You are scheduled"
        return None


# ---------------------------------------------------------------- ashby
ASHBY_TIME = re.compile(r"(\d{1,2}:\d{2}\s*[ap]m)\s*[-–—]\s*(\d{1,2}:\d{2}\s*[ap]m)", re.I)


def _hm(date, label, tz):
    t = dt.datetime.strptime(label.replace(" ", "").lower(), "%I:%M%p")
    return dt.datetime.combine(date, t.time(), tz)


def ashby_request(pg, url):
    got = {}

    def on_resp(r):
        if "op=ApiFindMeetingAvailabilityRequest" in r.url:
            try:
                got.update(r.json()["data"]["result"]["meetingAvailabilityRequest"] or {})
            except Exception:
                pass

    pg.on("response", on_resp)
    pg.goto(url, wait_until="networkidle", timeout=UA_TIMEOUT)
    pg.wait_for_timeout(1500)
    check_captcha(pg)
    return got


def ashby_set_tz(pg, tz_name):
    """Pick the configured timezone in the timezone select via React onChange (no-op if absent)."""
    pg.evaluate("""(tz) => {
      for (const s of document.querySelectorAll('select')) {
        const o = [...s.options].find(o => o.value === tz || o.text.replace(' ', '_') === tz);
        if (!o) continue;
        const k = Object.keys(s).find(k => k.startsWith('__reactProps'));
        s.value = o.value;
        if (k && s[k].onChange) s[k].onChange({target: s, currentTarget: s});
        else s.dispatchEvent(new Event('change', {bubbles: true}));
      }
    }""", tz_name)


def ashby_read_tz(pg, tz_name):
    """The timezone select's ACTUAL selected option, read from the DOM."""
    got = pg.evaluate("""(tz) => {
      for (const s of document.querySelectorAll('select')) {
        if (![...s.options].some(o => o.value === tz || o.text.replace(' ', '_') === tz)) continue;
        const o = s.options[s.selectedIndex];
        return o ? (o.value === tz || o.text.replace(' ', '_') === tz ? tz : o.value) : '';
      }
      return '';
    }""", tz_name)
    return got or "(no timezone select on the page)"


def ashby_month_label(pg):
    loc = pg.locator(".react-datepicker__current-month")
    return loc.first.inner_text().strip() if loc.count() else ""


def ashby_selected_day(pg):
    loc = pg.locator(".react-datepicker__day--selected")
    return loc.first.inner_text().strip() if loc.count() else ""


def ashby_slots(pg, url, days, tz, tz_name):
    req = ashby_request(pg, url)
    meta = {"provider": "ashby", "status": req.get("status"), "title": req.get("meetingTitle"),
            "duration_min": req.get("meetingDurationInMinutes"),
            "direct_booking": req.get("isDirectBookingLink")}
    sched = req.get("meetingSchedule") or []
    if sched:
        meta["booked"] = [{"title": m.get("title"), "start": iso(parse_iso(m["startTime"], tz), tz),
                           "end": iso(parse_iso(m["endTime"], tz), tz)} for m in sched]
    body = pg.inner_text("body")
    if "Interview Confirmed" in body or req.get("status") == "InterviewScheduled":
        meta["status"] = "already_booked"
        return [], meta
    if not req.get("isDirectBookingLink", True):
        meta["note"] = "not a direct-booking link: use `availability` (pick days + ranges)"
        return [], meta
    if "/availability/calendar" not in pg.url:
        cal = url.rstrip("/") + "/availability/calendar"
        pg.goto(cal, wait_until="networkidle", timeout=UA_TIMEOUT)
        pg.wait_for_timeout(1500)
        check_captcha(pg)
    ashby_set_tz(pg, tz_name)
    pg.wait_for_timeout(800)
    dur = int(req.get("meetingDurationInMinutes") or 30)
    end = dt.datetime.now(tz).date() + dt.timedelta(days=days)
    out, seen = [], set()
    for _month in range(3):
        mlabel = ashby_month_label(pg)
        try:
            mdate = dt.datetime.strptime(mlabel, "%B %Y").date()
        except ValueError:
            mdate = dt.datetime.now(tz).date().replace(day=1)
        days_loc = pg.locator(".react-datepicker__day:not(.react-datepicker__day--disabled)"
                              ":not(.react-datepicker__day--outside-month)")
        for i in range(days_loc.count()):
            el = days_loc.nth(i)
            dnum = int(el.inner_text().strip())
            date = mdate.replace(day=dnum)
            if date > end:
                break
            el.click()
            pg.wait_for_timeout(700)
            rows = pg.locator("div[class*=selectableTimeAndButton]")
            for j in range(rows.count()):
                txt = rows.nth(j).inner_text()
                m = ASHBY_TIME.search(txt) or re.search(r"(\d{1,2}:\d{2}\s*[ap]m)", txt, re.I)
                if not m:
                    continue
                st = _hm(date, m.group(1), tz)
                en = _hm(date, m.group(2), tz) if m.lastindex and m.lastindex >= 2 else st + dt.timedelta(minutes=dur)
                if st not in seen:
                    seen.add(st)
                    out.append({"start": iso(st, tz), "end": iso(en, tz)})
        if mdate.replace(day=28) >= end.replace(day=1) and mdate.month == end.month:
            break
        nxt = pg.locator(".react-datepicker__navigation--next")
        if nxt.count() == 0:
            break
        nxt.first.click()
        pg.wait_for_timeout(800)
    out.sort(key=lambda x: x["start"])
    meta["status"] = "open" if out else "no_slots"
    return out, meta


class AshbyBooking:
    """One Ashby direct booking: pick the day, find the time row; its Book button is final."""

    def __init__(self, pg, url, start, tz_name):
        self.pg, self.url, self.start, self.tz_name = pg, url, start, tz_name
        self.row = None

    def prepare(self):
        pg, start = self.pg, self.start
        req = ashby_request(pg, self.url)
        if req.get("status") == "InterviewScheduled":
            raise SystemExit("ashby: link already booked; refusing (reschedule is out of scope)")
        if "/availability/calendar" not in pg.url:
            pg.goto(self.url.rstrip("/") + "/availability/calendar", wait_until="networkidle", timeout=UA_TIMEOUT)
        check_captcha(pg)
        ashby_set_tz(pg, self.tz_name)
        target_month = f"{start:%B %Y}"
        for _ in range(3):
            if ashby_month_label(pg) == target_month:
                break
            pg.locator(".react-datepicker__navigation--next").first.click()
            pg.wait_for_timeout(600)
        pg.locator(f".react-datepicker__day--0{start.day:02d}:not(.react-datepicker__day--outside-month)").first.click()
        pg.wait_for_timeout(800)
        self.row = None
        rows = pg.locator("div[class*=selectableTimeAndButton]")
        for i in range(rows.count()):
            r = rows.nth(i)
            if row_starts_at(r.inner_text(), start):
                self.row = r
                break

    def read_back(self):
        start, tl = self.start, time_label(self.start)
        row_text = ""
        try:
            row_text = re.sub(r"\s+", " ", self.row.inner_text()).strip()[:200] if self.row is not None else ""
        except Exception:
            row_text = ""
        row_ok = row_starts_at(row_text, start)
        return [
            _row("timezone", self.tz_name, ashby_read_tz(self.pg, self.tz_name)),
            _row("month (as rendered)", f"{start:%B %Y}", ashby_month_label(self.pg)),
            _row("day (as rendered)", str(start.day), ashby_selected_day(self.pg)),
            _row("slot row (as rendered)", f"row starting {tl}", row_text or "NOT FOUND ON PAGE", ok=row_ok),
        ]

    def click_final(self):
        self.row.get_by_role("button", name=re.compile("Book")).click()

    def wait_confirmation(self):
        for _ in range(60):
            self.pg.wait_for_timeout(500)
            check_captcha(self.pg)
            if "Interview Confirmed" in self.pg.inner_text("body"):
                return "Interview Confirmed"
        return None


class AshbyAvailability:
    """Ashby 'pick days + time ranges' form. Each window {start,end} ISO. The selects take ISO
    values like 2026-10-12T12:00:00.000-07:00 and need React onChange."""

    def __init__(self, pg, url, windows, tz, tz_name):
        self.pg, self.url, self.windows, self.tz, self.tz_name = pg, url, windows, tz, tz_name
        self.picked = []  # per window: (start, end) values the selects actually held

    def prepare(self):
        pg = self.pg
        req = ashby_request(pg, self.url)
        if req.get("status") == "InterviewScheduled":
            raise SystemExit("ashby: link already booked; refusing")
        check_captcha(pg)
        ashby_set_tz(pg, self.tz_name)
        for w in self.windows:
            s = parse_iso(w["start"], self.tz)
            for _ in range(3):
                if ashby_month_label(pg) in ("", f"{s:%B %Y}"):
                    break
                pg.locator(".react-datepicker__navigation--next").first.click()
                pg.wait_for_timeout(500)
            pg.locator(f".react-datepicker__day--0{s.day:02d}:not(.react-datepicker__day--outside-month)").first.click()
            pg.wait_for_timeout(600)
            res = pg.evaluate("""([sIso, eIso]) => {
              const pick = (sel, want) => {
                const o = [...sel.options].find(o => o.value && Date.parse(o.value) === Date.parse(want));
                if (!o) return false;
                const k = Object.keys(sel).find(k => k.startsWith('__reactProps'));
                sel.value = o.value;
                if (k && sel[k].onChange) sel[k].onChange({target: sel, currentTarget: sel});
                else sel.dispatchEvent(new Event('change', {bubbles: true}));
                return true;
              };
              const sels = [...document.querySelectorAll('select')].filter(s =>
                 [...s.options].some(o => /^\\d{4}-\\d{2}-\\d{2}T/.test(o.value)));
              if (sels.length < 2) return 'no time selects';
              const a = sels[sels.length - 2], b = sels[sels.length - 1];
              return (pick(a, sIso) && pick(b, eIso)) ? 'ok' : 'value not offered';
            }""", [w["start"], w["end"]])
            if res != "ok":
                raise SystemExit(f"ashby availability: window {w} -> {res}")
            pg.wait_for_timeout(300)
            # read back what the two selects ACTUALLY hold after React re-rendered, before Add
            held = pg.evaluate("""() => {
              const sels = [...document.querySelectorAll('select')].filter(s =>
                 [...s.options].some(o => /^\\d{4}-\\d{2}-\\d{2}T/.test(o.value)));
              if (sels.length < 2) return ['', ''];
              return [sels[sels.length - 2].value, sels[sels.length - 1].value];
            }""")
            self.picked.append((held[0], held[1]))
            add = pg.get_by_role("button", name=re.compile(r"^Add", re.I))
            if add.count():
                add.first.click()
                pg.wait_for_timeout(400)

    def read_back(self):
        rows = [_row("timezone", self.tz_name, ashby_read_tz(self.pg, self.tz_name))]
        body = self.pg.inner_text("body")
        for n, (w, held) in enumerate(zip(self.windows, self.picked), 1):
            s, e = parse_iso(w["start"], self.tz), parse_iso(w["end"], self.tz)
            for which, want, got in (("start", s, held[0]), ("end", e, held[1])):
                try:
                    same = bool(got) and parse_iso(got, self.tz) == want
                except ValueError:
                    same = False
                rows.append(_row(f"window {n} {which} select", iso(want, self.tz), got or "(empty)", ok=same))
            listed = [ln.strip()[:200] for ln in body.splitlines()
                      if time_label(s) in ln.lower() and time_label(e) in ln.lower()]
            rows.append(_row(f"window {n} (as rendered)", f"{time_label(s)} - {time_label(e)}",
                             listed[0] if listed else "NOT FOUND ON PAGE", ok=bool(listed)))
        if len(self.picked) != len(self.windows):
            rows.append(_row("windows filled", len(self.windows), len(self.picked)))
        return rows

    def click_final(self):
        self.pg.locator('button[type="submit"]').first.click()

    def wait_confirmation(self):
        for _ in range(60):
            self.pg.wait_for_timeout(500)
            check_captcha(self.pg)
            m = re.search(r"(submitted|thank you|received|confirmed)", self.pg.inner_text("body"), re.I)
            if m:
                return m.group(0)
        return None


if __name__ == "__main__":
    import argparse
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    print("browser_actions.py is a library; run tools/build/book_link.py instead.")
