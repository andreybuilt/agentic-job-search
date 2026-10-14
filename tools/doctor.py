#!/usr/bin/env python3
"""doctor.py -- check that this machine can run the stage you are about to run.

    python3 tools/doctor.py                  # core: Python, config, facts file, gate lists
    python3 tools/doctor.py --stage render   # core + Chrome/Playwright, poppler, your font
    python3 tools/doctor.py --stage book     # core + Playwright (tools/build/book_link.py)
    python3 tools/doctor.py --stage all
    python3 tools/doctor.py --config path/to/config.yaml

Prints a checklist. Each line is OK, WARN or FAIL. Exit 0 when nothing required for the
requested stage FAILs, 1 otherwise. Never uses the network. The font check renders a
one-line test page in a temporary directory and reads the fonts back with pdffonts, because
"the font file is installed" and "Chrome can see the font" are different facts.
"""
import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

MIN_PY = (3, 10)
results = []


def report(status, label, detail=""):
    results.append(status)
    print(f"  [{status:<4}] {label}" + (f": {detail}" if detail else ""))


def check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PY
    report("OK" if ok else "FAIL", "Python", f"{v.major}.{v.minor}.{v.micro} (need {MIN_PY[0]}.{MIN_PY[1]}+)")


def _example_name(C):
    """The persona name in config.example.yaml, read from the file (never typed here)."""
    try:
        with open(os.path.join(HERE, "..", "config.example.yaml"), encoding="utf-8") as f:
            return C.get(C.parse_yaml_lite(f.read()), "candidate.name")
    except (OSError, C.ConfigError):
        return None


def check_config(explicit):
    """Return the loaded config, or None (after reporting FAIL)."""
    from tools.common import config as C

    path = None
    for p in C.candidate_paths(explicit):
        if p.is_file():
            path = p
            break
        if explicit or os.environ.get(C.ENV_VAR):
            break  # an explicit choice that is missing does not fall through
    if path is None:
        report("FAIL", "config", f"no config.yaml found. {C.MISSING_HINT}")
        return None
    try:
        cfg = C.parse_yaml_lite(path.read_text(encoding="utf-8"))
    except C.ConfigError as e:
        report("FAIL", "config", f"{path}: {e}")
        return None
    cfg[C.CONFIG_DIR_KEY] = str(path.resolve().parent)
    report("OK", "config", str(path))

    missing = [k for k in ("name", "email", "phone", "city", "linkedin", "website")
               if not C.get(cfg, f"candidate.{k}")]
    if missing:
        report("FAIL", "candidate contact fields", "missing " + ", ".join(missing))
    elif C.get(cfg, "candidate.name") == _example_name(C):
        report("WARN", "candidate", "still the fictional example persona; edit the candidate block")
    else:
        report("OK", "candidate", C.get(cfg, "candidate.name"))

    facts = C.resolve_path(cfg, "paths.facts_md")
    if not facts:
        report("FAIL", "facts file", "paths.facts_md is not set")
    elif not os.path.isfile(facts):
        report("FAIL", "facts file", f"{facts} not found (cp templates/FACTS.example.md FACTS.md)")
    else:
        report("OK", "facts file", facts)

    for key in ("gates.banned_names_file", "gates.banned_claims_file", "gates.claim_rules_file", "gates.b9_rules_file"):
        p = C.resolve_path(cfg, key)
        if p and os.path.isfile(p):
            note = " (shipped example; replace with your own)" if os.sep + "examples" + os.sep in p else ""
            report("WARN" if note else "OK", key, p + note)
        else:
            report("FAIL", key, f"{p or 'not set'} not found")

    data_root = C.resolve_path(cfg, "paths.data_root")
    if data_root and os.path.isdir(data_root):
        report("OK", "data root", data_root)
    else:
        report("WARN", "data root", f"{data_root} does not exist yet (mkdir -p it)")
    return cfg


def have_playwright():
    return importlib.util.find_spec("playwright") is not None


def check_render(cfg):
    from tools.common import config as C

    sys.path.insert(0, os.path.join(HERE, "build"))
    import render_pdf

    chrome = render_pdf.find_chrome(C.get(cfg, "render.chrome_path", None) if cfg else None)
    if chrome:
        report("OK", "Chrome/Chromium", chrome)
    elif have_playwright():
        report("OK", "Chrome/Chromium", "none found; Playwright is installed (run `playwright install chromium` once)")
    else:
        report("FAIL", "Chrome/Chromium", "none found and no Playwright: install Chrome, or pip install playwright")

    tools = {t: shutil.which(t) for t in ("pdftotext", "pdffonts", "pdfinfo")}
    for t, p in tools.items():
        report("OK" if p else "FAIL", t, p or "not found (install poppler: poppler-utils / brew install poppler)")

    font = str((C.get(cfg, "render.font_family", None) if cfg else None) or "Carlito")
    if not (chrome or have_playwright()) or not tools["pdffonts"]:
        report("FAIL", f"font {font}", "cannot test without a browser and pdffonts")
        return
    with tempfile.TemporaryDirectory() as d:
        src, out = os.path.join(d, "t.html"), os.path.join(d, "t.pdf")
        with open(src, "w", encoding="utf-8") as f:
            f.write(f'<html><body style="font-family: \'{font}\'">doctor font test</body></html>')
        try:
            if chrome:
                render_pdf.render_with_chrome(chrome, src, out)
            else:
                render_pdf.render_with_playwright(src, out)
            fonts = subprocess.run(["pdffonts", out], capture_output=True, text=True).stdout.splitlines()[2:]
        except (SystemExit, OSError) as e:
            report("FAIL", f"font {font}", f"test render failed: {e}")
            return
    names = sorted({ln.split()[0].split("+")[-1] for ln in fonts if ln.strip()})
    want = font.replace(" ", "").lower()
    if names and all(n.lower().startswith(want) for n in names):
        report("OK", f"font {font}", "the browser renders with it")
    else:
        report("FAIL", f"font {font}", f"test page rendered with {names or 'no fonts'}; install {font} "
               "where your browser can see it (README, Prerequisites)")


def check_book():
    if have_playwright():
        report("OK", "Playwright", "installed")
    else:
        report("FAIL", "Playwright", "not installed: pip install playwright && playwright install chromium")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=("core", "render", "book", "all"), default="core",
                    help="what you are about to run (default: core)")
    ap.add_argument("--config", default=None, help="Path to your config YAML")
    a = ap.parse_args(argv)

    print(f"agentic-job-search doctor (stage: {a.stage})")
    check_python()
    cfg = check_config(a.config)
    if a.stage in ("render", "all"):
        check_render(cfg)
    if a.stage in ("book", "all"):
        check_book()
    fails = results.count("FAIL")
    warns = results.count("WARN")
    print(f"\n{len(results)} checks: {len(results) - fails - warns} OK, {warns} WARN, {fails} FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
