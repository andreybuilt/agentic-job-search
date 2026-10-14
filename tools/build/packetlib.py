#!/usr/bin/env python3
"""packetlib: the shared machinery a per-company packet builder (resume + cover letter)
would otherwise re-implement by hand every time.

This is a library, not a command. Copy tools/build/TEMPLATE_build.py to start a builder.
Running this file directly prints this help.

A builder script holds only what is genuinely per-batch: its CONTENT (taglines,
summaries, rows, letter paragraphs, gap sentence) and its POLICY (role-specific banned
terms, scope dates, prior letters to de-duplicate against). This module holds the
mechanism, and every edit to a base HTML file checks its anchor first, so a silent no-op
cannot ship a packet that renders clean while carrying another role's leftover text.

  * Every check is a hard refusal (SystemExit "REFUSE: ..."), not an `assert`, so running
    Python with -O cannot switch the guards off.
  * Renders through render-resume_v3.sh (5 fail-closed gates; see that script), passing
    your config file explicitly.
  * The banned-names list (gates.banned_names_file) is ALWAYS enforced at source, on top
    of the builder's own banned-term list. It cannot be configured away.
  * Writes only inside paths.data_root. No git repository is needed.

Config keys read (see config.example.yaml):
  candidate.name, candidate.city, candidate.email, candidate.phone, candidate.linkedin,
  candidate.website       -- header and contact line; every one is required
  paths.data_root         -- root of your packet tree (bases, letters, frozen JDs live here)
  gates.banned_names_file -- names that must never appear (also read by the render gate)
  render.font_family      -- the one font the rendered PDFs may contain
  policy.stale_head_tokens_csv, policy.sensitive_terms_csv -- extra refusals

No real name, employer, or company is hardcoded anywhere in this file.
"""
import glob, hashlib, html, os, pickle, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
from tools.common.config import load_config, get, require, resolve_path, resolve_config_path  # noqa: E402

S = '<span class="sep">&middot;</span>'
RENDER = os.path.join(HERE, "render-resume_v3.sh")
AUDIT = os.path.normpath(os.path.join(HERE, "..", "verify", "claim_audit.py"))
GATE = os.path.normpath(os.path.join(HERE, "..", "verify", "b9_check.py"))

# Set by configure(). Nothing is read at import time, so importing this module (or running
# a builder with --help) needs no config file and no particular working directory.
_CFG = None
CONFIG_PATH = None
CANDIDATE_NAME = None
DATA_ROOT = None
CACHE_DIR = None
NAMES_FILE = None
STALE_HEAD_TOKENS = []
SENSITIVE_TERMS = []
CONTACT_KEYS = ("city", "email", "phone", "linkedin", "website")


def _check(cond, msg):
    """A refusal that survives `python -O` (an assert would not)."""
    if not cond:
        raise SystemExit(f"REFUSE: {msg}")


def configure(config_path=None):
    """Load the config (same resolution as every tool) and set this module's globals.
    Returns the loaded config dict."""
    global _CFG, CONFIG_PATH, CANDIDATE_NAME, DATA_ROOT, CACHE_DIR, NAMES_FILE
    global STALE_HEAD_TOKENS, SENSITIVE_TERMS
    CONFIG_PATH = str(resolve_config_path(config_path))
    _CFG = load_config(CONFIG_PATH)
    CANDIDATE_NAME = require(_CFG, "candidate.name")
    for k in CONTACT_KEYS:
        require(_CFG, f"candidate.{k}")
    DATA_ROOT = resolve_path(_CFG, "paths.data_root")
    _check(DATA_ROOT, "paths.data_root is not set in your config")
    DATA_ROOT = os.path.realpath(DATA_ROOT)
    CACHE_DIR = os.path.join(DATA_ROOT, "_build_cache")
    NAMES_FILE = resolve_path(_CFG, "gates.banned_names_file")
    _check(NAMES_FILE, "gates.banned_names_file is not set in your config")
    STALE_HEAD_TOKENS = [t.strip() for t in str(get(_CFG, "policy.stale_head_tokens_csv", "") or "").split(",") if t.strip()]
    SENSITIVE_TERMS = [t.strip() for t in str(get(_CFG, "policy.sensitive_terms_csv", "") or "").split(",") if t.strip()]
    return _CFG


def _need_config():
    _check(_CFG is not None, "packetlib.configure() was not called before building")


def contact_line(sep=None):
    """The contact line for a resume or letter header, built ONLY from config:
    city | email | phone | linkedin | website. Every field is required."""
    _need_config()
    sep = sep or '<span class="sep">|</span>'
    return sep.join(html.escape(str(require(_CFG, f"candidate.{k}"))) for k in CONTACT_KEYS)


def facts_forbidden():
    """The configured banned-names list. Exits 2 (refuses) if it is missing or empty."""
    _need_config()
    sys.path.insert(0, HERE)
    import forbidden_names_gate as fng
    return fng.load_names(NAMES_FILE)


# ---------------------------------------------------------------------------------------------------- base surgery
def _read(rel):
    _need_config()
    p = os.path.join(DATA_ROOT, rel)
    _check(os.path.isfile(p), f"base file not found under paths.data_root: {p}")
    with open(p, encoding="utf-8") as f:
        return f.read()


def head_of(path, title):
    d = _read(path)
    _check("<body>" in d, f"no <body> tag in {path}")
    h = d[:d.index("<body>") + len("<body>")]
    h = re.sub(r"<!--.*?-->\s*", "", h, count=1, flags=re.S)   # drop the base provenance comment
    h = re.sub(r"<title>.*?</title>", f"<title>{title}</title>", h)
    for tok in STALE_HEAD_TOKENS:
        _check(tok not in h, f"stale placeholder token {tok!r} left in head of {path}")
    return h


def tail_of(path, start_marker="<h2>Experience</h2>"):
    d = _read(path)
    _check(start_marker in d, f"anchor {start_marker!r} not in {path}")
    return d[d.index(start_marker):]


def retarget(tail, company):
    new, n = re.subn(r'<span class="target">[^<]*</span>', f'<span class="target">{company}</span>', tail)
    _check(n == 1, f"expected exactly 1 target span, found {n}")
    print(f"target span replaced: {n} (checked == 1) -> {company}")
    return new


def swap_row(tail, label, new_row):
    anchor = f'<div class="comp-row"><b>{label}</b>'
    _check(anchor in tail, f"row anchor {anchor!r} not in the base: refusing a silent no-op")
    start = tail.index(anchor)
    end = tail.index("</div>", start) + 6
    out = tail[:start] + new_row + tail[end:]
    _check(new_row in out, f"row swap for {label!r} did not land")
    return out


def letter_css(path):
    d = _read(path)
    _check("<style>" in d and "</style>" in d, f"no <style> block in {path}")
    return d[d.index("<style>"):d.index("</style>") + len("</style>")]


def letter(css, title, tagline, meta, company, paras, contact, name=None):
    name = name or CANDIDATE_NAME
    ps = "\n\n".join(f'<p class="body">{p}</p>' for p in paras)
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
{css}
</head>
<body>
<div class="header">
  <div class="name">{name.upper()}</div>
  <div class="tagline">{tagline}</div>
  <div class="contact">{contact}</div>
</div>

<div class="meta">{meta}</div>

<div class="salutation">Dear {company} team,</div>

{ps}

<div class="sign">
  <div class="nm">{name}</div>
</div>
</body>
</html>
'''


def top(tagline, summary, bullets, contact, name=None):
    name = name or CANDIDATE_NAME
    lis = "\n".join(f"  <li>{b}</li>" for b in bullets)
    return f'''

<div class="header">
  <div class="name">{name.upper()}</div>
  <div class="tagline">{tagline}</div>
  <div class="contact">{contact}</div>
</div>

<h2>Summary</h2>
<div class="summary">{summary}</div>

<h2>Why This Role</h2>
<ul>
{lis}
</ul>

'''


def section(heading, lead, bullets, inline_label="", inline=""):
    """A generic resume section: heading, one lead line, bullets, optional inline line."""
    lis = "\n".join(f"<li>{b}</li>" for b in bullets)
    tail = f'<div class="inline"><b>{inline_label}:</b> {inline}</div>\n' if inline_label else ""
    return f'''<h2>{heading}</h2>
<div class="lead">{lead}</div>
<ul>
{lis}
</ul>
{tail}
'''


# ---------------------------------------------------------------------------------------------------- guards
def guard(rel, text, banned, is_letter=False, gap="", gap_terms=(), onsite=False):
    """Every content check a packet build wants, plus the forbidden-names list that the
    caller cannot remove. The SENSITIVE_TERMS co-occurrence check is a generic mechanism --
    fill policy.sensitive_terms_csv in config with your own never-say-this-near-that pairs;
    none are hardcoded here."""
    _check("\u2014" not in text, f"em dash in {rel}")
    body = re.sub(r"<title>.*?</title>|<style>.*?</style>", "", text, flags=re.S)
    if is_letter:
        body = re.sub(r'<div class="meta">.*?</div>', "", body, flags=re.S)   # the meta line carries the SOURCE title
    for name in facts_forbidden():
        _check(not re.search(rf"(?<![A-Za-z]){re.escape(name)}", body, re.I), f"forbidden name {name!r} in {rel}")
    for bad in banned:
        rx = (rf"(?<![A-Za-z]){re.escape(bad)}(?![a-z])" if bad[0].isalpha() and len(bad) <= 4
              else rf"(?<![A-Za-z]){re.escape(bad)}")
        _check(not re.search(rx, body, re.I if len(bad) > 4 else 0), f"banned term {bad!r} in {rel}")
    for term in SENSITIVE_TERMS:
        _check(term not in body, f"sensitive term {term!r} (from policy.sensitive_terms_csv) in {rel}")
    for term in gap_terms:
        for m in re.finditer(re.escape(term), body, re.I):
            ctx = html.unescape(body[max(0, m.start() - 300):m.end() + 300])
            _check(gap and gap in ctx, f"{term!r} outside the gap sentence in {rel}")
    if is_letter:
        _check("Citizen" not in text, f"citizenship status in the letter {rel}; keep it out of the letter body")
        if onsite:
            _check(not re.search(r"\bremote", body, re.I), "onsite role: the letter must not pitch remote work")
        _check("&ndash;" not in text and "\u2013" not in text, f"en dash in the letter {rel}")
        _check(text.count(gap) == 1, f"the gap sentence must appear exactly once in {rel}")


def write(rel, text, banned, **kw):
    _need_config()
    p = os.path.join(DATA_ROOT, rel)
    _check(os.path.realpath(p).startswith(DATA_ROOT + os.sep), f"refusing to write outside paths.data_root: {p}")
    guard(rel, text, banned, **kw)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote", p)
    return p


# ---------------------------------------------------------------------------------------------------- assembly
def name_of(P):
    return f"{P['folder']}-{P['slug']}"


def paths(P):
    """P["version"] (e.g. "_v2") versions up beside a used file instead of overwriting it."""
    d = os.path.join(DATA_ROOT, P["pdir"], "20_MD")
    v = P.get("version", "")
    _need_config()
    stem = CANDIDATE_NAME.split()[-1]
    return (os.path.join(d, f"{stem}_Resume_{name_of(P)}{v}.html"),
            os.path.join(d, f"{stem}_CoverLetter_{name_of(P)}{v}.html"))


def pdfs(P):
    return tuple(p[:-5] + ".pdf" for p in paths(P))


def assemble(P, cfg):
    """Return (resume_html, letter_html) for one packet without writing anything."""
    _need_config()
    company = cfg["company"]
    tail = tail_of(P["base"], cfg.get("tail_marker", "<h2>Experience</h2>"))
    for label, row in P.get("rows", ()):
        tail = swap_row(tail, label, row)
    for stale in cfg.get("tail_must_not_contain", ()):
        _check(stale not in tail, f"base text {stale!r} survived the row swaps")
    resume = (head_of(P["base"], f"{CANDIDATE_NAME} Resume - {company} {html.unescape(P['role'])}")
              + P["resume_top"] + retarget(tail, company))
    meta = f"{cfg['date']} &nbsp;&middot;&nbsp; {company} &nbsp;&middot;&nbsp; {P['role']} ({P['req']})"
    let = letter(cfg["letter_css"], f"{CANDIDATE_NAME} Cover Letter - {company} {html.unescape(P['role'])}", P["tagline"],
                 meta, company, P["paras"], cfg["letter_contact"])
    _check(P["paras"][0].startswith(P["opening"]), f"{P['slug']}: the first paragraph must start with the opening sentence")
    _check(sum(P["gap"] in x for x in P["paras"]) == 1, f"{P['slug']}: the gap sentence must be in exactly one paragraph")
    return resume, let


def check_jd(P, cfg):
    jd = glob.glob(os.path.join(DATA_ROOT, P["pdir"], f"10_SOURCE/{cfg['jd_dir']}/*_JD.md"))
    _check(len(jd) == 1, f"frozen JD missing for {P['pdir']}")
    with open(jd[0], encoding="utf-8") as f:
        body = f.read()
    _check("AT BUILD TIME, before submission" in body and "- **req:** `" in body, f"JD header incomplete: {jd[0]}")
    _check(P["req"].split()[-1] in body, f"req id not in JD header: {jd[0]}")
    print("JD ok:", os.path.relpath(jd[0], DATA_ROOT))


def render(p, company):
    pdf = p[:-5] + ".pdf"
    if os.path.exists(pdf):
        os.remove(pdf)                       # never let a stale PDF pass for a fresh render
    r = subprocess.run(["bash", RENDER, p, company, "--config", CONFIG_PATH], capture_output=True, text=True)
    print(r.stdout.strip(), r.stderr.strip())
    _check(r.returncode == 0, f"render failed for {p}")


def verify(P, company, resume_pages=2, letter_pages=1):
    ok_all = True
    rpdf, lpdf = pdfs(P)
    print(f"\n######## {P['pdir']}")
    words = len(re.sub(r"<[^>]+>", " ", " ".join(P["paras"])).split())
    print(f"== letter body words: {words}")
    print("== opening sentence:\n" + P["opening"] + "\n== gap sentence:\n" + P["gap"])
    a = subprocess.run([sys.executable, AUDIT, P["pdir"], "--config", CONFIG_PATH], cwd=DATA_ROOT,
                       capture_output=True, text=True)
    print("== claim_audit\n" + a.stdout + a.stderr)
    ok_all &= a.returncode == 0
    wanted_font = str(get(_CFG, "render.font_family", "Carlito") or "Carlito").replace(" ", "")
    for f, want in ((rpdf, resume_pages), (lpdf, letter_pages)):
        info = subprocess.run(["pdfinfo", f], capture_output=True, text=True).stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        fonts = subprocess.run(["pdffonts", f], capture_output=True, text=True).stdout.splitlines()[2:]
        names = sorted({ln.split()[0].split("+")[-1] for ln in fonts if ln.strip()})
        with open(f, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        ok = pages == want and names and all(n.lower().startswith(wanted_font.lower()) for n in names)
        ok_all &= bool(ok)
        print(f"  {'ok  ' if ok else 'FAIL'} {os.path.basename(f)} ({len(os.path.basename(f))} chars) pages={pages} "
              f"(want {want}) fonts={names} sha256={sha[:12]}")
    return ok_all


# ---------------------------------------------------------------------------------------------------- de-duplication
def _gate_module():
    sys.path.insert(0, os.path.dirname(GATE))
    import b9_check as g
    return g


def scope_letters(PACKETS, cfg):
    mine = {pdfs(P)[1] for P in PACKETS}
    s = set()
    stem = CANDIDATE_NAME.split()[-1]
    for d in cfg["date_sets"]:
        s |= set(glob.glob(os.path.join(DATA_ROOT, f"*/{d}_*/20_MD/{stem}_CoverLetter_*.pdf")))
    return sorted(s - mine)


def letter_text(P, cfg):
    meta = f"{cfg['date']} · {cfg['company']} · {P['role']} ({P['req']})"
    t = meta + "\nDear " + cfg["company"] + " team,\n" + "\n".join(P["paras"]) + "\n" + CANDIDATE_NAME
    return html.unescape(re.sub(r"<[^>]+>", " ", t))


def cache(PACKETS, cfg):
    g = _gate_module()
    ps = scope_letters(PACKETS, cfg) + [os.path.join(DATA_ROOT, p) for p in cfg.get("prior_letters", ())]
    others = {p: g.sixgrams(g.body(g.pdftext(p))) for p in ps}
    os.makedirs(CACHE_DIR, exist_ok=True)
    out = os.path.join(CACHE_DIR, f"{cfg['build_id']}_others.pkl")
    with open(out, "wb") as f:
        pickle.dump(others, f)
    print(f"cached six-grams for {len(others)} letters -> {out}")


def precheck(PACKETS, cfg):
    g = _gate_module()
    cache_file = os.path.join(CACHE_DIR, f"{cfg['build_id']}_others.pkl")
    _check(os.path.isfile(cache_file), f"no six-gram cache at {cache_file}; run the builder with --cache first")
    with open(cache_file, "rb") as f:
        others = pickle.load(f)  # written by cache() above, in your own data_root
    rules = resolve_path(_CFG, "gates.b9_rules_file")
    _check(rules, "gates.b9_rules_file is not set in your config")
    banned_rx, protected = g.load_rules(rules)
    prot = g.protected_grams(protected)
    total = 0
    mine = {P["slug"]: g.sixgrams(letter_text(P, cfg)) for P in PACKETS}
    for P in PACKETS:
        gm = mine[P["slug"]]
        words = len(re.sub(r"<[^>]+>", " ", " ".join(P["paras"])).split())
        banned = [k for k, rx in banned_rx.items() if re.search(rx, letter_text(P, cfg), re.I)]
        hits = {}
        for k, go in others.items():
            for x in (gm & go) - prot:
                hits.setdefault(" ".join(x), []).append(os.path.basename(k)[19:60])
        for c2, g2 in mine.items():
            if c2 != P["slug"]:
                for x in (gm & g2) - prot:
                    hits.setdefault(" ".join(x), []).append("MINE:" + c2)
        print(f"== {P['slug']}: {words} words, {len(hits)} overlapping six-grams vs {len(others)} letters + mine, banned={banned}")
        for k, v in sorted(hits.items()):
            print(f"   {k:60s} {len(v)} {v[:3]}")
        total += len(hits) + len(banned)
    return total


def run_gate(PACKETS, cfg):
    mine_pdfs = [f for P in PACKETS for f in pdfs(P)]
    others = scope_letters(PACKETS, cfg)
    n = len(PACKETS) + len(others)
    print(f"argv: {len(mine_pdfs) + len(others)} files ({n} letters -> expect {n * (n - 1) // 2} pairs)", flush=True)
    try:
        r = subprocess.run([sys.executable, GATE, "--config", CONFIG_PATH] + mine_pdfs + others,
                           capture_output=True, text=True, timeout=2400)
    except subprocess.TimeoutExpired:
        print("REFUSE: b9_check did not finish within 40 minutes")
        return 1
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, f"{cfg['build_id']}_gate.txt"), "w", encoding="utf-8") as f:
        f.write(r.stdout + r.stderr)
    lines = r.stdout.splitlines()
    pair_lines = [ln for ln in lines if "six-gram overlap" in ln]
    # b9_check prints each name cut to 28 chars, so match on THAT, not on the company prefix.
    # Matching on the full prefix found 0 pairs for any company name of 8+ chars and passed
    # without testing anything. Refuse when a cut name is shared with an out-of-set letter,
    # because the gate output cannot then say which letter a line is about.
    cut = lambda p: os.path.basename(p)[:28]
    mine28 = {cut(pdfs(P)[1]) for P in PACKETS}
    clash = mine28 & {cut(o) for o in others}
    if clash:
        print(f"REFUSE: gate names are ambiguous at 28 chars (shared with other letters): {sorted(clash)}")
        return 1
    mine_pairs = [ln for ln in pair_lines if any(m in ln for m in mine28)]
    bad = [ln for ln in mine_pairs if not ln.rstrip().endswith("discretionary=0")]
    k = len(PACKETS)
    want = k * (n - k) + k * (k - 1) // 2
    print(f"exit {r.returncode}; pairs involving my letters: {len(mine_pairs)} (want {want}); "
          f"with discretionary>0: {len(bad)}")
    if len(mine_pairs) != want:
        print("REFUSE: pair count does not match: the gate did not test every pair involving these letters")
        return 1
    for ln in bad:
        print("  ", ln)
    fails = [ln for ln in lines if re.match(r"\s+(FAIL|!!)", ln)]
    print(f"file lines FAIL/!! (all set): {len(fails)}")
    for ln in fails:
        print("  ", ln.rstrip())
    return 1 if (bad or r.returncode) else 0


# ---------------------------------------------------------------------------------------------------- one entry point
def main(PACKETS, cfg, argv=None):
    """--cache | --pre | --gate | --dry (assemble + guard, write nothing) | [slug ...] build, render, verify."""
    argv = sys.argv[1:] if argv is None else argv
    if "--cache" in argv:
        cache(PACKETS, cfg); return 0
    if "--pre" in argv:
        return 1 if precheck(PACKETS, cfg) else 0
    if "--gate" in argv:
        return run_gate(PACKETS, cfg)
    only = [a for a in argv if not a.startswith("--")]
    todo = [P for P in PACKETS if not only or P["slug"] in only]
    for P in todo:
        check_jd(P, cfg)
    kw = dict(onsite=cfg.get("onsite", False))
    if "--dry" in argv:
        for P in todo:
            r, l = assemble(P, cfg)
            rp, lp = paths(P)
            guard(rp, r, cfg["banned"], gap=P["gap"], gap_terms=P.get("gap_terms", ()), **kw)
            guard(lp, l, cfg["banned"], is_letter=True, gap=P["gap"], gap_terms=P.get("gap_terms", ()), **kw)
            print("dry ok:", P["slug"])
        return 0
    ok_all = True
    for P in todo:
        r, l = assemble(P, cfg)
        rp, lp = paths(P)
        for p in (rp, lp):
            _check(not (P.get("version") and os.path.exists(p)), f"{p} exists: pick the next version, never overwrite")
        write(os.path.relpath(rp, DATA_ROOT), r, cfg["banned"], gap=P["gap"], gap_terms=P.get("gap_terms", ()), **kw)
        write(os.path.relpath(lp, DATA_ROOT), l, cfg["banned"], is_letter=True, gap=P["gap"],
              gap_terms=P.get("gap_terms", ()), **kw)
        for p in (rp, lp):
            render(p, cfg["company"])
        ok_all &= verify(P, cfg["company"], cfg.get("resume_pages", 2), cfg.get("letter_pages", 1))
    print("\nOVERALL (build, audit, pages, fonts):", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 1


if __name__ == "__main__":
    # A library, not a command: print the module help and exit 0 for any invocation.
    print(__doc__)
    sys.exit(0)
