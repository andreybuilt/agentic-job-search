# Contributing

Thanks for helping. A few rules keep this repo safe to share.

## Run the tests

```sh
bash tests/run-all.sh      # must end with OVERALL: PASS
bash scripts/demo.sh       # must end with DEMO PASSED
```

Both need only Python 3.10+. They use no network and no personal data.

## No real personal data, ever

Every example uses the fictional persona in `config.example.yaml` and
`templates/FACTS.example.md` (Jordan Rivera, `example.com` addresses, 555-010 phone numbers)
or another obviously fictional one. No real names, employers, customers, addresses, phone
numbers, pay figures or job ids in code, tests, docs, issues or pull requests.

## Add a lesson

Lessons live in `docs/LESSONS.md`. Each one is a **CLAIM**, then what happened (or the
general pattern), then **DO INSTEAD**. Write it so it is about the pattern, not a person:
no employer names, no quoted feedback, nothing that identifies who it happened to. If the
lesson changed a tool, say which one.

## Add or change a gate

A gate is only worth having if it can be shown to fire. Every gate change ships with:

1. a known-bad fixture the gate must catch, and a known-good one it must pass
   (under `tests/fixtures/`);
2. a control: a test, or a built-in self-check like the ones in `claim_audit.py` and
   `b9_check.py`, that fails if the matcher stops matching anything;
3. fail-closed behavior: a missing or empty list or an unreadable input is a refusal.

Read list and rule files from config keys (see `config.example.yaml`), never hardcode names.
If you add a config key, add it to `config.example.yaml`; `tests/test_config.py` checks both
directions.

## Never add a submit verb

No tool may submit an application, solve a CAPTCHA, sign in, sign, or pay. The only final
button in the repo is the interview booking in `tools/build/book_link.py`:
`book_link --confirm <code>` is the human's explicit go for that one booking, given after reading the read-back.
Every browser call (Playwright import, navigation, fill, click) belongs in
`tools/build/browser_actions.py`, and its final presses belong in methods named
`click_final`. `tests/test_agent_contract.py` parses every other file under `tools/` and fails
on a browser import or mutation call. It is a review aid, not a guarantee: reviewers still
read any change to `browser_actions.py` line by line.

## Every tool answers --help

A new executable under `tools/` must exit 0 on `--help` without a config file, network access
or writes. `tests/test_cli_help.py` runs every tool to check.
