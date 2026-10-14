# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-13

First public release. A stranger can now clone, run the tests, and run an offline demo with
no personal data.

### Added
- `scripts/demo.sh`: a 5-minute offline demo of the anti-fabrication gates on fictional
  fixtures. It exits 0 only when every gate behaves as expected.
- `tools/doctor.py`: checks Python, config, facts file, gate list files, and for rendering,
  Chrome or Playwright, poppler, and whether the browser actually renders your font.
- `pyproject.toml` (version 1.0.0, Python 3.10+, no required dependencies, optional `render`
  extra for Playwright) and `requirements.txt`.
- CI on Python 3.10 to 3.13: tests, demo, a `--help` sweep over every tool, and the
  browser-boundary and booking-gate tests.
- `tools/build/browser_actions.py`: the one module that drives a browser. Every Playwright
  import, navigation, fill and click lives there, and its final presses live only in methods
  named `click_final`. `tests/test_agent_contract.py` parses every other file under `tools/`
  (AST, plus a text scan of shell and JS) and fails on a browser import or mutation call. It is
  a review aid, not a guarantee.
- `tests/test_book_link.py`: the confirm code and gate as pure functions, and the real Calendly
  driver run against a fake page object, proving the read-back precedes the click and that a
  changed field, a missing control, a different slot or a missing code never reaches it.
- `SECURITY.md`, `CONTRIBUTING.md`, and a pull request template.
- Tests for config resolution and parsing, the config schema in both directions, the
  record-send round trip, a build with a non-example persona, the agent contract, every
  tool's `--help`, documented paths, the b9 control, and sweep error handling.

### Changed
- Config: tools read `--config`, then `$JOBSTACK_CONFIG`, then `./config.yaml`, then
  `config.yaml` at the repo root. They never fall back to `config.example.yaml`; a missing
  config stops the tool with the `cp` command to run. Relative paths resolve against the
  config file's own folder.
- The config parser supports one-line lists (`[]`, `["a", "b"]`) and rejects unsupported
  YAML (block lists, anchors, tabs, bad indentation, duplicate keys) with a line number.
- `config.example.yaml` is the complete schema: every key a tool reads is there, and no key
  is dead. Gate inputs have one key each (`gates.banned_names_file`,
  `gates.banned_claims_file`, `gates.claim_rules_file`, `gates.b9_rules_file`) and point at
  files that exist.
- One banned-names list, in one plain format, feeds every name gate, including the rendered
  PDF gate. `templates/FACTS.example.md` points to it.
- The shipped resume and cover-letter templates use Carlito, carry the target span and a
  salutation naming the target, and pass the shipped render gates. The render gate's font
  follows `render.font_family`, and every font in the PDF must be that family.
- `tools/build/TEMPLATE_build.py` and `packetlib.py` read every contact field from config
  and stop if one is missing. They no longer require a git worktree, read nothing at import,
  and use refusals that survive `python -O` instead of `assert`.
- The safety contract is one sentence, word for word the same in `CLAUDE.md`, `AGENTS.md`,
  `docs/MULTI_AGENT.md` and `README.md`. `CLAUDE.md` and `AGENTS.md` differ only in a
  one-line filename note.
- `book_link.py` books in two phases. The default run is a review: it fills the page, reads
  every control's actual value back from the DOM plus the slot or windows as rendered, prints
  that table and a confirm code (10 hex digits of sha256 over action, URL, slot and every
  read-back field), and closes without pressing the final button (exit 4). `--confirm <code>`
  fills and reads back again and presses the final button only when the recomputed code
  matches; otherwise it refuses (exit 2) and prints the field-by-field diff. After the click it
  reports BOOKED only when the page's confirmation text appears, else UNCONFIRMED (exit 1).
  The old offline plan is `--plan`. "`book_link --confirm <code>` is the human's explicit go for
  that one booking, given after reading the read-back" is word for word the same in every doc.
- `tests/run-all.sh` passes on a fresh clone with no environment. The leak gate runs only
  when `LEAK_DENYLIST` is set.
- `docs/LESSONS.md` section 5 and lesson 7.1 are rewritten as general patterns.
- `docs/PIPELINE.md` names nine stages and every tool path correctly.

### Fixed

- Ashby booking matches a slot row by its START time, so a `9:30am - 10:00am` row is never
  taken for the 10:00am slot.
- `build_submissions.py` path containment now has its own tests (absolute, `..`, symlink).
- `record_send.py` and `build_submissions.py`: the first recorded send was dropped as a
  "header", so the double-submit guard missed it. New ledgers get a header row, and only a
  real header row is skipped. `record_send.py` takes the ledger name from config.
- `presubmit.sh` printed `GATE PASSED` when tracker files were missing. A missing tracker is
  now a failure.
- `presubmit.sh` passed a req whose liveness was `ERROR`, blank or any unknown value. Only
  `LIVE` passes now.
- `record_send.py` joined the `packet` value from spec.json and `paths.direct_ledger_tsv` onto
  the data root unchecked, so `../..`, an absolute path or a symlink could write outside it.
  Every path is now resolved and must stay under the resolved data root; one bad entry writes
  nothing. `build_submissions.py` refuses a `paths.submissions_tsv` outside the data root.
- `book_link.py` computed its Chrome path before reading the config, so `render.chrome_path`
  was ignored. It is read after the config loads and is the first binary tried.
- `sweep.py` reported a network failure as "no board". It now reports `no-board` (404 on
  every ATS) and `error` separately, and exits 3 on any error.
- `b9_check.py`: the shipped example rules failed their own control because the control
  builder turned `\bGlobex` into `bGlobex`.
- `render-resume_v3.sh` treated `cover_letter.example.html` as a resume.
- `packetlib.py` pre-check referenced attributes `b9_check.py` does not have.
- `claim_audit.py` printed a garbled packet label.
- `fetch_jd.py` and `li_post.py` read tracker names relative to the working directory
  instead of the data root.
- `--help` now exits 0 on every tool without a config file, network access or writes.
- `verify_liveness.py` no longer makes network requests when run with no arguments.

### Removed
- Two git helper scripts that committed and pushed straight to a remote `main` branch.
- Workspace-specific wording and examples from shipped files.
- Dead config keys (`comp.*`, `mail.*`, `git.*`, `render.chrome_path_*`,
  `render.fonts_allowlist`).

## [0.1.0] - 2026-10-08

Initial private release.

[1.0.0]: https://github.com/andreybuilt/agentic-job-search/releases/tag/v1.0.0
[0.1.0]: https://github.com/andreybuilt/agentic-job-search/releases/tag/v0.1.0
