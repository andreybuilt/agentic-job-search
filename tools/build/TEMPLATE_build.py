#!/usr/bin/env python3
"""TEMPLATE for a packet builder on packetlib. Copy this file to your own build script,
fill in the POLICY and CONTENT blocks inside build(), and keep everything else.

    python3 <this file> --help
    python3 <this file> [--config PATH] --cache   # six-grams of every in-scope letter -> <data_root>/_build_cache/
    python3 <this file> [--config PATH] --pre     # six-gram pre-check of my letters vs the cache and each other (exit 1 = rewrite)
    python3 <this file> [--config PATH] --dry     # assemble + every guard, writes nothing
    python3 <this file> [--config PATH] [slug ..] # write HTML, render via render-resume_v3.sh, claim_audit, pages, fonts
    python3 <this file> [--config PATH] --gate    # b9_check over mine + the date sets

What it needs under paths.data_root (all paths below are relative to it):
  _Packets/BASE_Resume.html       a base resume: a <body> tag, an "<h2>Experience</h2>"
                                  heading where the tailored tail starts, and exactly one
                                  <span class="target">...</span>. A copy of
                                  templates/resume.example.html works as-is.
  _Packets/BASE_CoverLetter.html  any HTML file with a <style> block for the letter. A copy of
                                  templates/cover_letter.example.html works as-is.
  <Company>/<YYMMDD_Role>/10_SOURCE/<jd_dir>/*_JD.md
                                  the frozen job description, written by
                                  tools/build/capture_jd.py before you build.

Every contact detail (name, city, email, phone, LinkedIn, website) comes from the
candidate block of your config. A missing one stops the build. Nothing about the person is
written in this file.

Rules that should travel with every builder you write: read your own FACTS.md in full
first; every claim traces to FACTS, a dated source resume, or a base line already sourced
to them; one forward "gap" sentence per letter at most; stop at VERIFIED, never ship an
unverified claim. The banned-names list (gates.banned_names_file) is enforced by packetlib
whether or not the same names are in BANNED below. It cannot be configured away.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import packetlib as L  # noqa: E402


def build(config_path=None):
    """Return (PACKETS, cfg) for this batch. Loads your config first."""
    L.configure(config_path)
    contact = L.contact_line()

    # ======================================================================================== POLICY (per batch)
    COMPANY = "ExampleCo"
    BASE = "_Packets/BASE_Resume.html"            # your base resume (target span is replaced with COMPANY)
    BANNED = ("ExampleBannedTermOne", "ExampleBannedTermTwo")   # role-specific terms this batch must not contain
    cfg = dict(
        company=COMPANY, date="January 1, 2027", letter_contact=contact, banned=BANNED,
        onsite=False,                                  # True: the letter may not pitch remote work
        letter_css=L.letter_css("_Packets/BASE_CoverLetter.html"),
        tail_marker="<h2>Experience</h2>",             # where the base resume's reusable tail starts
        tail_must_not_contain=(),                      # base text a row swap must have removed
        jd_dir="270101-JD",                            # <pdir>/10_SOURCE/<jd_dir>/*_JD.md, frozen by capture_jd.py first
        date_sets=("270101",),
        prior_letters=(),                              # earlier letters to this company, de-duplicated against
        build_id="bNx",
        resume_pages=1, letter_pages=1,                # page counts the verify step expects
    )

    # ======================================================================================== CONTENT (per packet)
    PACKETS = []
    P = dict(base=BASE, folder=COMPANY, pdir=f"{COMPANY}/270101_RoleSlug", slug="RoleSlug",
             role="Role Title As Posted", req="Greenhouse 1234567",
             tagline="...", opening="I am applying ...", gap="... is where I would build depth ...", gap_terms=(),
             rows=[],                                  # [(comp-row label, replacement <div class="comp-row">...</div>)]
             )
    P["resume_top"] = L.top(P["tagline"], "summary ...", ["why this role ..."], contact)
    P["paras"] = [P["opening"] + " ...", "...", P["gap"] + " ..."]
    PACKETS.append(P)
    return PACKETS, cfg


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None, help="Path to your config YAML (default: the standard resolution order)")
    ap.add_argument("--cache", action="store_true", help="cache six-grams of every in-scope letter")
    ap.add_argument("--pre", action="store_true", help="six-gram pre-check against the cache")
    ap.add_argument("--dry", action="store_true", help="assemble and guard, write nothing")
    ap.add_argument("--gate", action="store_true", help="run b9_check over this batch and the date sets")
    ap.add_argument("slugs", nargs="*", help="build only these packet slugs (default: all)")
    a = ap.parse_args(argv)
    PACKETS, cfg = build(a.config)
    flags = [f"--{n}" for n in ("cache", "pre", "dry", "gate") if getattr(a, n)]
    return L.main(PACKETS, cfg, flags + a.slugs)


if __name__ == "__main__":
    sys.exit(main())
