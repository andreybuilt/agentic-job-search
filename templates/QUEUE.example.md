# QUEUE.example.md -- Application state tracker

## State machine

Every application moves through exactly these states, in order:

```
BUILT -> VERIFIED -> STAGED -> SUBMITTED
```

- **BUILT** -- a tailored resume/cover letter pair has been generated for this role.
- **VERIFIED** -- a human (you) has read the generated documents end-to-end, confirmed every
  fact against `FACTS.md`, and confirmed no forbidden name leaked in.
- **STAGED** -- documents are uploaded/attached in the target ATS or email draft, ready to send,
  but not yet sent.
- **SUBMITTED** -- the application has actually been transmitted.

A row can also be marked **STRUCK** (you decided not to pursue) or **REJECTED** (employer
declined). Both are terminal -- except for one real lesson: **a struck or rejected row needs an
explicit re-review whenever your screening threshold changes.** A role you struck because it
fell under your comp floor or a strike-condition last month does not silently become eligible
again when you loosen that threshold -- a stale filter setting does not self-correct on its own.
Re-run the row against the current `TARGETING.md` rubric by hand before reviving it.

## Example rows

| Company | Role | State | Date | Notes |
|---|---|---|---|---|
| Acme Corp | Senior Platform Engineer | SUBMITTED | 2026-09-02 | Warm-path referral from a former colleague |
| Globex Industries | Staff Backend Engineer | STAGED | 2026-09-15 | Waiting on final cover letter review |
| Umbrella Analytics | Backend Engineer II | STRUCK | 2026-08-28 | Posted range below comp floor -- re-check if floor changes |
