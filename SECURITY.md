# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: open the repository's **Security**
tab and choose **Report a vulnerability** (private vulnerability reporting). Do not open a
public issue for a security problem.

Please include what you ran, what happened, and what you expected. Use fictional data in any
example. Never paste your own `FACTS.md`, `config.yaml`, a real application packet, or anyone's
personal details into a report.

## In scope

- **Leaking personal data.** Anything that makes a tool write, print, commit or send personal
  data where the user did not ask for it, or that lets the example persona or another
  person's details end up in a user's documents.
- **Gate bypasses.** Input that gets a fabricated claim, a banned name, the wrong target
  company, or a missing-history state past a gate that should refuse it (`tools/verify/`,
  `tools/build/render-resume_v3.sh`, `tools/build/forbidden_names_gate.py`,
  `tools/verify/presubmit.sh`).
- **Anything that could submit without the human.** Any path that submits an application,
  books a slot, solves a CAPTCHA, signs in, signs, or pays without the human's explicit go
  for that one action (see the safety contract in `CLAUDE.md`).
- **Prompt injection.** Fetched content (a job page, an email, a JD) that can steer an agent
  using this repo into breaking the rules in `CLAUDE.md`.

## Out of scope

- Rate limits or terms of service of the job boards the sourcing tools read.
- Problems that need an attacker to already control your machine or your config file.

## Supported versions

Only the latest release receives fixes.
