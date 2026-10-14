#!/usr/bin/env python3
"""
render_pdf.py -- render a local HTML file to PDF via local headless Chrome, or Playwright's
bundled Chromium if no system Chrome/Chromium is found.

Rendering always happens on your own machine. No remote render service is used.

Chrome/Chromium resolution order:
  1. --chrome-path flag, or render.chrome_path in your config (empty = auto-detect)
  2. $CHROME_PATH environment variable
  3. macOS: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome,
     /Applications/Chromium.app/Contents/MacOS/Chromium
  4. Linux/other: google-chrome, google-chrome-stable, chromium, chromium-browser (via PATH)
  5. Playwright's bundled Chromium, if the `playwright` package is installed
     (`pip install playwright && playwright install chromium`)

If none of the above resolves, this exits non-zero with a clear message rather than
silently producing no PDF.

Usage:
  python3 render_pdf.py <input.html> <output.pdf> [--chrome-path PATH] [--config PATH]
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from tools.common.config import load_config, get, add_config_arg  # noqa: E402


def find_chrome(explicit):
    if explicit and os.path.isfile(explicit):
        return explicit
    env = os.environ.get("CHROME_PATH")
    if env and os.path.isfile(env):
        return env
    system = platform.system()
    if system == "Darwin":
        for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ):
            if os.path.isfile(p):
                return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    return None


def render_with_chrome(chrome, src_path, out_path):
    # Headless Chrome's --print-to-pdf needs a file:// URL, an absolute path, and the output
    # directory to already exist.
    src_abs = os.path.abspath(src_path)
    out_abs = os.path.abspath(out_path)
    cmd = [
        chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
        f"--print-to-pdf={out_abs}", f"file://{src_abs}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"REFUSE: chrome render failed (rc={r.returncode}): {r.stderr.strip()[:400]}")


def render_with_playwright(src_path, out_path):
    # Every Playwright call in this repo lives in tools/build/browser_actions.py.
    from tools.build import browser_actions
    try:
        browser_actions.render_html_to_pdf(os.path.abspath(src_path), os.path.abspath(out_path))
    except ImportError:
        sys.exit(
            "REFUSE: no local Chrome/Chromium found and the `playwright` package is not installed. "
            "Install Google Chrome, or `pip install playwright && playwright install chromium`."
        )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="Input HTML file")
    ap.add_argument("out", help="Output PDF path")
    ap.add_argument("--chrome-path", default=None, help="Explicit path to a Chrome/Chromium binary")
    add_config_arg(ap)
    args = ap.parse_args()

    if not os.path.isfile(args.src):
        sys.exit(f"REFUSE: no such file: {args.src}")

    # The config is read only when no --chrome-path is given, and only for render.chrome_path.
    chrome_path = args.chrome_path or get(load_config(args.config), "render.chrome_path", None)
    chrome = find_chrome(chrome_path)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    if os.path.exists(args.out):
        os.remove(args.out)  # never let a stale PDF pass for a fresh render

    if chrome:
        render_with_chrome(chrome, args.src, args.out)
    else:
        print("[render_pdf] no system Chrome/Chromium found; trying Playwright's bundled Chromium", file=sys.stderr)
        render_with_playwright(args.src, args.out)

    if not os.path.isfile(args.out) or os.path.getsize(args.out) == 0:
        sys.exit(f"REFUSE: no PDF written to {args.out}")
    print(args.out)


if __name__ == "__main__":
    main()
