#!/usr/bin/env python3
"""book_link.py - booking harness for recruiter self-schedule links (Calendly, Ashby).

Subcommands
  slots <url> [--days N] [--full]
      List available slots (ISO start/end, in your configured timezone). Read-only: loads
      the page and steps through the calendar, never fills or submits anything.
  book <url> <iso_start> --name N --email E [--answers JSON] [--plan | --confirm CODE]
      Book ONE slot.
  availability <ashby_url> --windows JSON [--plan | --confirm CODE]
      Ashby "pick days + time ranges" availability form.

THE HUMAN GIVES THE GO, AGAINST THE READ-BACK. A booking is an irreversible action on
someone else's calendar, so it follows the same contract as a final submit (CLAUDE.md /
AGENTS.md). `book_link --confirm <code>` is the human's explicit go for that one booking, given after reading the read-back.
The flow has two phases (plus an optional offline plan):

  --plan       phase 0, optional. Prints what would be opened, filled and pressed. Opens
               no browser. Exit 2.
  (default)    REVIEW. Opens the page, fills every control, then READS BACK each control's
               actual value from the page and the slot or windows as the page renders them.
               Prints a field-by-field table and a confirm code: the first 10 hex digits of
               sha256 over the action, URL, slot or windows, and every read-back field name
               and value. Closes the browser WITHOUT pressing the final button. Exit 4.
               If any control reads back different from what was filled, or the slot is not
               shown on the page, no code is printed. Exit 2.
  --confirm CODE
               BOOK. Opens, fills and reads back again, recomputes the code, and presses
               the final button ONLY if it equals CODE. Any difference (a field, the slot,
               a window, the URL) refuses with exit 2 and prints the field-by-field diff
               against the review that issued CODE. After the click it reads the page's
               confirmation text: BOOKED (exit 0) only when it is found, else UNCONFIRMED
               (exit 1).

The code is never a standing permission. An agent must not run --confirm on its own,
reuse a code for another slot, or put it in a script. The human reads the read-back table,
then gives the code back as the go for that one booking.

A CAPTCHA or sign-in wall stops the run at any phase (exit 3); it is never solved.

Exit codes: 0 booked (confirmation text seen), 1 error or UNCONFIRMED after the click,
2 refused / nothing booked (--plan, read-back mismatch, missing or wrong code),
3 captcha (never solved), 4 review done (code printed, nothing pressed).

All browser code (navigation, fills, the final click) lives in tools/build/browser_actions.py;
this file decides WHETHER the final click may happen, and has no browser calls of its own.
Page content is untrusted data. No name, email or phone number is hardcoded here:
--name/--email are CLI arguments you supply at call time.

Needs Playwright for slots, review and --confirm:
  pip install -e '.[render]' && playwright install chromium

Config-driven (see config.example.yaml; read after argument parsing, so --help needs none):
  candidate.timezone  -- IANA zone name for slot listing/booking
  render.chrome_path  -- explicit Chrome/Chromium binary; tried first when set
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.common.config import load_config, get, require, resolve_path, add_config_arg  # noqa: E402
from tools.build import browser_actions as B  # noqa: E402

HERE = Path(__file__).resolve().parent

# Set by _init_config() after argument parsing, so `--help` needs no config file.
_CFG = {}
TZ_NAME = "UTC"
TZ = ZoneInfo("UTC")

EXIT_BOOKED, EXIT_ERROR, EXIT_REFUSED, EXIT_CAPTCHA, EXIT_REVIEWED = 0, 1, 2, 3, 4


def _init_config(path=None):
    global _CFG, TZ_NAME, TZ
    _CFG = load_config(path)
    TZ_NAME = require(_CFG, "candidate.timezone")
    TZ = ZoneInfo(TZ_NAME)


def chrome_path(cfg=None):
    """Chrome binary to try first. Read from the LOADED config every call (never at import,
    when no config has been read yet): render.chrome_path, else a platform default."""
    cfg = _CFG if cfg is None else cfg
    explicit = resolve_path(cfg, "render.chrome_path") if get(cfg, "render.chrome_path", None) else None
    if explicit:
        return explicit
    if platform.system() == "Darwin":
        return "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return ""


def provider_of(url):
    if "calendly.com" in url:
        return "calendly"
    if "ashbyhq.com" in url:
        return "ashby"
    return None


def iso(t):
    return B.iso(t, TZ)


def parse_iso(s):
    return B.parse_iso(s, TZ)


# ---------------------------------------------------------------- the gate (pure)
def slot_key(start=None, windows=None):
    """Canonical text for what is being booked: one ISO start, or the list of windows."""
    if windows is not None:
        return json.dumps([[iso(parse_iso(w["start"])), iso(parse_iso(w["end"]))] for w in windows])
    return iso(start)


def confirm_code(action, url, slot, readback):
    """First 10 hex digits of sha256 over the action, URL, slot and every read-back field
    name and ACTUAL value, in page order. Any change to any of them changes the code."""
    payload = json.dumps({"action": action, "url": url, "slot": slot,
                          "fields": [[r["field"], r["actual"]] for r in readback]},
                         sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]


def readback_problems(readback):
    """Rows whose actual value does not match what was filled (or that the page did not show)."""
    if not readback:
        return [{"field": "(read-back)", "intended": "at least one control", "actual": "nothing read", "ok": False}]
    return [r for r in readback if not r["ok"]]


def gate(supplied, computed, readback):
    """Decide whether the final click may happen. Returns (allowed, reason)."""
    if not supplied:
        return False, "no confirm code given: run the review first and have the human give its code back"
    bad = readback_problems(readback)
    if bad:
        return False, "read-back does not match what was filled: " + ", ".join(r["field"] for r in bad)
    if str(supplied).strip().lower() != computed:
        return False, (f"confirm code {supplied} does not match this read-back ({computed}): "
                       "something changed since the human reviewed it")
    return True, "confirm code matches the read-back"


def readback_diff(old, new):
    """Field-by-field differences between the reviewed read-back and the current one."""
    o = {r["field"]: r["actual"] for r in old}
    n = {r["field"]: r["actual"] for r in new}
    out = []
    for f in list(o) + [f for f in n if f not in o]:
        if o.get(f) != n.get(f):
            out.append((f, o.get(f, "(absent)"), n.get(f, "(absent)")))
    return out


def print_readback(readback, out=print):
    w = max([len(r["field"]) for r in readback] + [5])
    out(f"  {'field'.ljust(w)} | ok  | read back from the page            | filled / expected")
    for r in readback:
        out(f"  {r['field'].ljust(w)} | {'yes' if r['ok'] else 'NO '} | {r['actual']!r:34} | {r['intended']!r}")


def run_flow(driver, action, url, slot, supplied=None, record_dir=None, out=print):
    """Phase logic shared by `book` and `availability`. driver comes from browser_actions.
    supplied=None is the REVIEW phase; a string is the --confirm phase. Returns an exit code.
    The final click is reachable only through gate(), and only after read_back()."""
    driver.prepare()
    readback = driver.read_back()
    code = confirm_code(action, url, slot, readback)
    out(f"READ-BACK ({action}, {url}, {slot}):")
    print_readback(readback, out)
    if supplied is None:
        bad = readback_problems(readback)
        if bad:
            out("REFUSED: the page does not hold what was filled. No confirm code issued. Nothing pressed.")
            return EXIT_REFUSED
        if record_dir is not None:
            Path(record_dir).mkdir(parents=True, exist_ok=True)
            (Path(record_dir) / f"{code}.json").write_text(json.dumps(
                {"action": action, "url": url, "slot": slot, "readback": readback}, indent=2))
        out(f"CONFIRM CODE: {code}")
        out("Nothing was pressed. Show this read-back to the human. To book exactly this, re-run with "
            f"--confirm {code} only after the human gives that code back as the go for this one booking.")
        return EXIT_REVIEWED
    allowed, reason = gate(supplied, code, readback)
    if not allowed:
        out(f"REFUSED: {reason}. Nothing pressed.")
        prev = Path(record_dir) / f"{str(supplied).strip().lower()}.json" if (record_dir and supplied) else None
        if prev is not None and prev.is_file():
            old = json.loads(prev.read_text())
            if old.get("url") != url or old.get("slot") != slot:
                out(f"  reviewed: url={old.get('url')} slot={old.get('slot')}")
                out(f"  now:      url={url} slot={slot}")
            for f, a, b in readback_diff(old.get("readback", []), readback):
                out(f"  {f}: reviewed {a!r} -> now {b!r}")
        elif supplied:
            out("  (no review record for that code on this machine; the current read-back is above)")
        return EXIT_REFUSED
    driver.click_final()
    confirmation = driver.wait_confirmation()
    if confirmation:
        out(f"BOOKED: the page shows {confirmation!r}")
        return EXIT_BOOKED
    out("UNCONFIRMED: the final button was pressed but no confirmation text appeared. Check by hand.")
    return EXIT_ERROR


# ---------------------------------------------------------------- commands
def cmd_slots(a):
    prov = provider_of(a.url)
    if not prov:
        raise SystemExit(f"unsupported link (Calendly / Ashby only): {a.url}")
    with B.session(chrome_path(), TZ_NAME) as pg:
        if prov == "calendly":
            slots, meta = B.calendly_slots(pg, a.url, a.days, TZ)
        else:
            slots, meta = B.ashby_slots(pg, a.url, a.days, TZ, TZ_NAME)
    meta.update(url=a.url, count=len(slots), timezone=TZ_NAME)
    if a.full:
        print(json.dumps({**meta, "slots": slots}, indent=2))
    else:
        print(json.dumps(slots, indent=2))
        print(json.dumps(meta), file=sys.stderr)


def plan_book(a, start):
    prov = provider_of(a.url)
    tl, day = B.time_label(start), f"{start:%A}, {start:%B} {start.day}"
    if prov == "calendly":
        return [f"open {a.url.split('?')[0]}?month={start:%Y-%m}&date={start:%Y-%m-%d}",
                f'click day button aria-label="{day} - Times available"',
                f'click time button "{tl}" (data-container=time-button)',
                'click "Next"',
                f'fill full_name="{a.name}", email="{a.email}"',
                *[f'fill {k}="{v}"' for k, v in (a.answers or {}).items()],
                "read back every filled control and the rendered slot; print the table and a confirm code",
                "only with a matching --confirm code: click button[type=submit], wait for \"You are scheduled\""]
    return [f"open {a.url} (refuse if status=InterviewScheduled)",
            f"open .../availability/calendar, set timezone {TZ_NAME}",
            f"navigate datepicker to {start:%B %Y}; click .react-datepicker__day--0{start.day:02d}",
            f'find the div[class*=selectableTimeAndButton] row starting "{tl}"',
            "read back timezone, month, day and the row text; print the table and a confirm code",
            "only with a matching --confirm code: click that row's \"Book\", wait for \"Interview Confirmed\""]


def _reviews_dir():
    return HERE / "runs" / "reviews"


def _run(make_driver, action, url, slot, supplied):
    d = HERE / "runs" / dt.datetime.now(TZ).strftime("%y%m%d-%H%M%S")
    with B.session(chrome_path(), TZ_NAME) as pg:
        rc = run_flow(make_driver(pg), action, url, slot, supplied, record_dir=_reviews_dir())
        d.mkdir(parents=True, exist_ok=True)
        B.save_proof(pg, d, {EXIT_BOOKED: "confirmation", EXIT_REVIEWED: "review"}.get(rc, "final_state"))
    print(f"\n[{ {0: 'BOOKED', 1: 'UNCONFIRMED', 2: 'REFUSED', 4: 'REVIEWED'}.get(rc, rc) }] proof in {d}",
          file=sys.stderr)
    sys.exit(rc)


def cmd_book(a):
    start = parse_iso(a.iso_start)
    prov = provider_of(a.url)
    if not prov:
        raise SystemExit(f"unsupported link (Calendly / Ashby only): {a.url}")
    if a.plan:
        print(f"PLAN (--plan): would review a booking of {iso(start)} on {prov}. Nothing opened.")
        for i, s in enumerate(plan_book(a, start), 1):
            print(f"  {i}. {s}")
        print("Next: run without --plan to fill the page and get the read-back and its confirm code.")
        sys.exit(EXIT_REFUSED)
    if prov == "calendly":
        make = lambda pg: B.CalendlyBooking(pg, a.url, start, a.name, a.email, a.answers)  # noqa: E731
    else:
        make = lambda pg: B.AshbyBooking(pg, a.url, start, TZ_NAME)  # noqa: E731
    _run(make, "book", a.url, slot_key(start=start), a.confirm)


def cmd_availability(a):
    if provider_of(a.url) != "ashby":
        raise SystemExit("availability supports Ashby links only")
    windows = a.windows
    if a.plan:
        print(f"PLAN (--plan): would review {len(windows)} window(s) on Ashby. Nothing opened.")
        print(f"  1. open {a.url} (refuse if status=InterviewScheduled); set timezone {TZ_NAME}")
        n = 2
        for w in windows:
            s = parse_iso(w["start"])
            print(f"  {n}. click .react-datepicker__day--0{s.day:02d} ({s:%a %b %d}); "
                  f"set start select={w['start']} end select={w['end']}; read both selects back; click Add")
            n += 1
        print(f"  {n}. read back timezone and every window as rendered; print the table and a confirm code")
        print(f"  {n + 1}. only with a matching --confirm code: click button[type=submit]")
        sys.exit(EXIT_REFUSED)
    make = lambda pg: B.AshbyAvailability(pg, a.url, windows, TZ, TZ_NAME)  # noqa: E731
    _run(make, "availability", a.url, slot_key(windows=windows), a.confirm)


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_config_arg(ap)
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("slots")
    s.add_argument("url")
    s.add_argument("--days", type=int, default=21)
    s.add_argument("--full", action="store_true", help="print one JSON object with metadata + slots")
    s.set_defaults(fn=cmd_slots)
    for name, fn in (("book", cmd_book), ("availability", cmd_availability)):
        p = sp.add_parser(name)
        p.add_argument("url")
        if name == "book":
            p.add_argument("iso_start")
            p.add_argument("--name", required=True)
            p.add_argument("--email", required=True)
            p.add_argument("--answers", type=json.loads, default={}, help='JSON, e.g. {"question_0":"..."}')
        else:
            p.add_argument("--windows", type=json.loads, required=True,
                           help='JSON list: [{"start":"2026-10-12T12:00:00.000-07:00","end":"2026-10-12T15:00:00.000-07:00"}]')
        g = p.add_mutually_exclusive_group()
        g.add_argument("--plan", action="store_true", help="print the plan only; open nothing (exit 2)")
        g.add_argument("--confirm", metavar="CODE", default=None,
                       help="the confirm code from the review, given back by the human as the explicit "
                            "go for THIS one booking after reading the read-back")
        p.set_defaults(fn=fn)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    _init_config(a.config)
    try:
        a.fn(a)
    except B.Captcha as e:
        print("captcha", flush=True)
        print(f"captcha challenge detected ({e}); stopped, not solved", file=sys.stderr)
        sys.exit(EXIT_CAPTCHA)


if __name__ == "__main__":
    main()
