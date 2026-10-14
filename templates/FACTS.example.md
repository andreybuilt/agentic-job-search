# FACTS.example.md

> ⚠️ **THIS FILE IS THE ONLY SOURCE OF BIOGRAPHICAL FACT FOR EVERY GENERATED DOCUMENT.**
> Never add, infer, or round anything not here. If a cover letter, resume, or email draft
> needs a number, a date, or a claim that isn't in this file, STOP and add it here first -- 
> never let a generator invent or estimate it. Copy this file to `FACTS.md`, fill it in with
> your own real information, and keep it out of version control (`FACTS.md` is already in
> `.gitignore`). Keep the identity lines in step with the `candidate:` block of `config.yaml`.

## Identity

- **Name:** Jordan Rivera
- **Location:** Springfield, ST
- **Email:** jordan.rivera@example.com
- **Phone:** +1-555-010-0100
- **LinkedIn:** linkedin.com/in/jordan-rivera-example
- **Website:** example.com
- **Work authorization:** Authorized to work in the United States, no sponsorship required
  *(replace with your own status -- citizenship, visa type, sponsorship needs, etc.)*
- **Education:** B.S. Computer Science, State University, 2014

## Compensation floor

- **Minimum acceptable base salary:** $130,000/year
- **Notes:** Will consider total comp (base + bonus + equity) at or above this floor; will not
  proceed past a first screen if the posted or disclosed range tops out below this number.

## Employment history (examples -- replace with your own)

1. **Acme Corp** -- Senior Platform Engineer, 2021–2024
   - Scope: owned CI/CD and release tooling for a 40-engineer product org.
2. **Globex Industries** -- Backend Engineer, 2018–2021
   - Scope: built and ran the billing-events pipeline for a subscription product.
3. **Initech** -- Software Engineer I, 2014–2018
   - Scope: internal tools team; shipped the first version of the internal admin console.

## Forbidden names

Names that must never appear in an outbound document (an employer under NDA, a confidential
customer, an unannounced project codename) do not live in this file. They live in one plain
list that every name gate reads: the file named by `gates.banned_names_file` in your
`config.yaml`. The shipped example is `tools/examples/banned_names.example.txt`.

Copy that file, replace its fictional entries with your own, and point
`gates.banned_names_file` at the copy. Keep at least one entry. An empty list is a refusal by
design, because a gate with no list checks nothing.
