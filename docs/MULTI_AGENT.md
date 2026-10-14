# Running several agents on one job search

You do not need this to use the toolkit. A single Claude Code or Codex session doing one job
at a time is the whole system for most people. This document is for the case where you want
to split the work across several concurrent agents (for speed, or because you're running this
for more than one person).

## Why split at all

A job search has genuinely separate concerns with different risk profiles: finding and scoring
roles is low-stakes and high-volume; building and verifying a packet is medium-stakes and
benefits from a second pass; submitting touches someone else's system and a human boundary;
interview follow-up touches a calendar and other people's time. Splitting lets you run the
low-stakes, high-volume agent (sourcing) aggressively while keeping the submit agent
conservative.

## The agents

- **Build** -- scores and builds packets. Stops at "verified, ready to send." Never submits
  anything.
- **Submit** -- fills forms in an isolated browser profile and reads every field back. It
  follows the safety contract, which is the same in `CLAUDE.md`, `AGENTS.md` and `README.md`:

  > The final submit is the human's. Either the human clicks it, or, after reviewing the agent's field-by-field read-back, the human gives an explicit go for THAT ONE submission and the agent clicks. No standing permission. CAPTCHAs, sign-ins, e-signatures, payments: human only, always.
- **Interview** -- the post-reply agent: scheduling, call prep, debriefs. Never touches
  application state (it doesn't decide whether to accept/decline/negotiate) and never drafts in
  the candidate's voice without the human approving the send.
- **POCs / take-homes** -- any take-home assignment or proof-of-concept exercise a company asks
  for. Keep this separate from Build/Submit because a take-home's code quality and claims are
  held to a much higher scrutiny bar if it ever comes up in an interview (Lesson 5.2: don't
  claim you built and tested something your own files show was only an exploratory probe).
- **Socials** -- optional, out of scope for the core pipeline. If you run one, treat it exactly
  like the others: one owner, reports to the orchestrator, never messages the human directly.
- **Orchestrator** -- the sole channel to the human. Every other agent reports to it. It decides
  anything that isn't the human's to decide, and escalates only: spend, anything irreversible,
  security findings, or a genuine personal choice (which offer, which city, how to answer a
  comp question).

## The one-channel rule

Multiple agents independently messaging the human causes duplicated asks and contradictions the
human has to arbitrate (Lesson 6.1). Pick exactly one orchestrator. Every agent's output goes to
the orchestrator, never straight to the human, even if the agent could technically reach the
human directly.

## Mailbox / handoff pattern

A simple, generic pattern that works for any transport (a shared folder, a lightweight message
queue, or just files in a git repo other agents poll):

1. Each agent owns exactly one canonical file or tracker (Lesson 6.3). Decide ownership before
   two agents' outputs could touch the same file, not after a collision.
2. An agent that finds something out of its own scope writes a one-line item to the orchestrator's
   inbox (a flat file, one row per item, never edited in place -- append only) instead of acting
   on it or routing it itself.
3. The orchestrator drains its inbox at the start of its own turn, assigns each item a
   sequential, never-reused ID in a durable register (Lesson 6.6), and either answers it,
   forwards it to the owning agent, or escalates it to the human.
4. Verify an agent's self-reported success against the actual system before relaying it as fact
   (Lesson 6.2). "The mail-watch script ran on schedule" is not the same claim as "the mail-watch
   script found and filed 3 new messages" -- check for non-zero, correct output, not just that
   the process exited cleanly.

## Concurrency costs, honestly

Several same-shaped agents on shared infrastructure caused real lock contention and
inconsistent edits to shared trackers in the original version of this stack, but peer agents
running in parallel also caught each other's wrong conclusions multiple times. That benefit does
not keep scaling: budget for lock contention past roughly three or four concurrent agents
touching the same shared state, and institute an explicit peer cross-check before any
consequential claim gets written to a shared record, rather than assuming parallelism is free
(Lesson 6.5).
