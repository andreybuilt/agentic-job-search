# 49 Lessons From Running an AI-Assisted Job Search

These are claims, not war stories for their own sake. Each one changed how the underlying tools
or process worked. Evidence pointers into the original private project have been removed. What
matters here is the claim and what to do instead.

## 1. Targeting and positioning

1. **CLAIM:** A comp floor (or any screening threshold) stated once propagates silently and never
   self-corrects when it's wrong.
   **WHAT HAPPENED:** A comp floor was set, then corrected downward twice, each time by the
   candidate stating a new number out loud. Roles screened out under the stale, too-high floor
   were never automatically re-screened. At least one role was struck twice, on both comp and
   location, and both strikes were later found to be wrong.
   **DO INSTEAD:** Treat a comp/filter threshold as a dated, versioned parameter, not an
   assumption baked into every downstream tool. When it changes, explicitly re-walk prior
   "struck" rows rather than trusting the forward pipeline to self-heal.

2. **CLAIM:** Anonymize sensitive names in outbound materials inside the single source-of-truth
   table itself -- a rule written as a side note two sections away will be copied around before
   anyone enforces it.
   **WHAT HAPPENED:** A positioning document named prior employers' customers directly as
   "anchor" credibility labels in one section, with an anonymization rule written separately
   elsewhere in the same file. A tailoring pipeline copies whatever sits in the table it reads
   from, so roughly 29 outbound documents carried the real names verbatim before the gap was
   caught.
   **DO INSTEAD:** Put the sanitized version directly in the source-of-truth table, not as a
   side rule next to it. Test from "how does this read to the evaluator," not "is this
   technically permitted."

3. **CLAIM:** A coding/framework-fluency bar hidden inside a "deployed/forward-deployed
   engineer"-style title is a real disqualifier for a primarily customer-facing candidate -- 
   build a named screening gate for it instead of discovering it one rejection at a time.
   **WHAT HAPPENED:** Detailed rejection feedback from a customer-facing role named the real
   gaps: solution designs too complex for customer-facing advice work, framework-vs-build
   judgment, evaluation depth, agent tracing, fluency with a specific orchestration framework.
   This triggered a full repositioning and an explicit per-requirement-line screening gate.
   **DO INSTEAD:** Separate "customer-first, light scripting" roles from "ship production code
   in customer codebases" roles by reading each requirement line, not the title.

4. **CLAIM:** Re-score a long specialist background against current job-description language
   when the market shifts, instead of treating the old specialty as a flat ceiling.
   **WHAT HAPPENED:** A long-tenured specialist background was initially read as "mature
   category, premium gone." A structured line-by-line mapping of old discipline to new
   successor disciplines found that most legacy disciplines had a named successor where few
   candidates hold both halves.
   **DO INSTEAD:** When a long specialist background feels stale, build the old-to-new
   translation table against live job-description language before concluding the specialty has
   no next act.

5. **CLAIM:** Score fit against the literal nouns of a live job description, not a generic
   self-assessment.
   **WHAT HAPPENED:** A requirement-by-requirement comparison against a live posting's exact
   language found a near word-for-word match that an earlier, generic resume pass had missed
   because the job-description vocabulary didn't exist yet when that resume was drafted.
   **DO INSTEAD:** Before tailoring, extract the job description's own nouns and phrases into a
   requirement table and map each to a specific proof point.

6. **CLAIM:** A guessed applicant-tracking-system platform silently masks whether a role is
   actually open -- verify by direct query, not by inference from "this kind of company usually
   uses X."
   **WHAT HAPPENED:** Several targets were nearly marked "closed" after requests to an assumed
   job-board platform failed. The real cause was a wrong platform guess for every one of them.
   **DO INSTEAD:** Confirm the actual ATS/board platform per company before concluding a
   requisition is gone; a failed guess is not evidence of closure.

7. **CLAIM:** Warm paths and referrals convert at a materially higher rate than cold
   applications -- route structurally through them rather than submitting cold by default.
   **WHAT HAPPENED:** A packet for one target was deliberately held until routed through a warm
   contact. A cold submission to a comparable target drew a résumé-screen rejection within about
   a day, while warm-routed pipelines produced live conversations and later-stage progress.
   **DO INSTEAD:** When ranking a target list under limited time, weight by
   (fit × comp × geography) ÷ effort, sequence warm-path targets ahead of cold ones, and treat
   "packet ready" and "packet sent" as two separate gates with a routing check between them.

**Aggregate (rounded, no names):** dozens of applications tracked in one window, several outright
résumé-screen-or-later rejections, a small cluster of confirmed submissions in a single ~48-hour
push, and a later re-screen pass that cut roughly 240 candidate postings down to about 18 under a
stricter targeting gate.

## 2. Anti-fabrication: packets, facts files, claim audits, name gates

1. **CLAIM:** A name-exclusion rule applied to source Markdown does not protect the rendered
   PDF -- the two can diverge.
   **WHAT HAPPENED:** An anonymization rule stripped a client's name from the `.md` source
   files, but the render-to-PDF step was never re-checked against the same rule. A later sweep
   found most already-sent packets carried a forbidden name in the actual PDF text.
   **DO INSTEAD:** Gate the rendered, shipped file, never assume a source-level fix propagates.
   Build a post-render gate that extracts text from the actual PDF, checks it against a
   forbidden-name list from one canonical facts file, fails closed if the list can't be read or
   extracted text is suspiciously short, names the specific violation, and applies to every
   document type that ships. Prove the detector fires on a known-bad corpus and passes a
   known-clean one before trusting it.

2. **CLAIM:** Auditing only the applications you know about will systematically undercount -- 
   re-run the audit after the inventory itself is found incomplete.
   **WHAT HAPPENED:** A first overclaim audit covered a tracked set of applications. A later
   reconciliation discovered roughly 22 additional sent applications that had never made it
   into the tracker.
   **DO INSTEAD:** Before declaring an audit complete, independently verify the inventory it's
   scoped to, rather than trusting the application's own send-log as ground truth.

3. **CLAIM:** A single ground-truth ruling can retroactively re-score an entire overclaim
   audit -- severity is relative to an evolving facts file, not a fixed judgment.
   **WHAT HAPPENED:** An audit flagged a tenure claim as a HIGH-severity overclaim across dozens
   of applications. After the subject confirmed the underlying fact was accurate, every finding
   in that class had to be removed and the whole audit re-scored.
   **DO INSTEAD:** Keep a single facts/ground-truth file as the sole arbiter the audit logic
   invokes. When ground truth changes, re-run the audit mechanically rather than hand-patching
   old results.

4. **CLAIM:** The applications that reached a live interview are exactly the ones where an
   overclaim matters most -- prioritize audit review there first, not by send-date order.
   **WHAT HAPPENED:** Several interview-stage packets carried HIGH-severity findings: the cases
   with real, near-term exposure to being caught by an interviewer.
   **DO INSTEAD:** Rank remediation priority by downstream exposure (interview scheduled >
   rejected > no response), not by severity score or chronology alone.

5. **CLAIM:** An alarm and its all-clear can sit in the same inbox and still be invisible to a
   check scoped too narrowly.
   **WHAT HAPPENED:** A mail classifier flagged several "enter this code and resubmit" messages
   as possibly-lost applications. A full-mailbox search showed each one had a confirmation
   arriving within minutes from the employer's own domain, not the vendor domain the scan was
   scoped to.
   **DO INSTEAD:** Before escalating an "X might be lost" signal, search across ALL senders for
   a counterparty-side confirmation, not just the system that raised the alarm.

6. **CLAIM:** Correcting an AI agent's own wrong fact, under challenge, can itself introduce a
   NEW wrong fact if the correction isn't re-verified against the primary source.
   **WHAT HAPPENED:** Several factual claims about a career history were challenged. Most
   corrections held up, but one re-statement was itself wrong until checked directly against
   the original document, and another near-miss was resolved only by reading the correcting
   document's current body, not its stale header.
   **DO INSTEAD:** Verify every disputed factual claim against the primary source document
   itself, not a second-hand restatement.

7. **CLAIM:** A forbidden-content leak that shows up in generated outputs usually traces back
   to the shared template, not to each instance -- fix the source, not the symptom.
   **WHAT HAPPENED:** A script checking generated packets for leaked confidential names caught
   several instances, but the root cause was the shared positioning template itself, which named
   confidential names directly even though the template's own stated rule said not to.
   **DO INSTEAD:** When a gate catches a forbidden pattern across multiple generated outputs,
   trace it to the shared template/generator and fix it there.

8. **CLAIM:** An unverified claim can sit in the one canonical facts file and silently
   propagate into every application packet for weeks until something forces a check.
   **WHAT HAPPENED:** A specific claim sat in the canonical facts file and in multiple
   already-sent packets for weeks. Only after a rejection prompted scrutiny did an audit find no
   evidence behind it, forcing a sweep of dozens of already-built packets.
   **DO INSTEAD:** Run an automated claim-audit against cited source evidence before every
   submission batch, not only after a rejection prompts one.

## 3. Sourcing and board traps

1. **CLAIM:** A 404 on a job board/ATS vendor's hosted page does not mean the role is dead.
   **WHAT HAPPENED:** An ATS vendor's board page, apply page, and board root all rendered "page
   not found." The role wasn't closed -- the employer ran its own inline form on its own careers
   page, and the application was submitted the same day.
   **DO INSTEAD:** Treat the employer's own careers domain as authoritative, never a vendor
   board. A 404 on a vendor-hosted page usually means the real form is elsewhere on the
   employer's own site.

2. **CLAIM:** A zero-hit keyword match on a JS-rendered page is a broken instrument, not
   evidence of absence.
   **WHAT HAPPENED:** A plain-text fetch of a careers page returned zero hits for a role title
   because the real listings loaded into a client-side embed invisible to a text fetch.
   **DO INSTEAD:** Flag any JS-rendered page explicitly rather than trusting a text-match result
   from it. Fall back to a real browser-render/DOM tool, or ask a human, before concluding
   something isn't posted.

3. **CLAIM:** A board-platform API's "0 results" or error code can mean "this company isn't on
   this platform at all," not "no open roles" -- establish the platform's baseline behavior
   before trusting it.
   **WHAT HAPPENED:** One ATS vendor's API returns HTTP 200 with a zero-results count for a
   company that simply isn't on that platform. A different major vendor returns the same error
   code for every tenant queried, including ones that can't possibly exist.
   **DO INSTEAD:** Before trusting an automated board-probe's result as a real signal, test it
   against a known-good and a known-bad company on the same platform.

4. **CLAIM:** A blocked request can be a bot-detection artifact or a network-origin artifact -- 
   diagnose by changing one variable at a time before concluding a board is closed.
   **WHAT HAPPENED:** One vendor API returned "forbidden" to a plain scripted request but
   succeeded with a real browser user-agent string. A different company's careers API returned
   "forbidden" specifically from datacenter/cloud egress addresses and succeeded from a
   residential address.
   **DO INSTEAD:** When blocked, change the user-agent first, then the network origin, before
   concluding a board is hostile or a role is gone.

5. **CLAIM:** A keyword/entity sweep over free text needs word-boundary matching or it
   manufactures false hits.
   **WHAT HAPPENED:** A sweep matching short vendor/company names as substrings produced wildly
   inflated hit counts -- one short acronym matched over a thousand times because it's a
   substring of common English words.
   **DO INSTEAD:** Always use word-boundary-aware matching for short names/acronyms, and
   manually sanity-check the top offenders in any automated name-matching sweep.

6. **CLAIM:** A web dropdown that "doesn't respond" to typing or scrolling is usually a
   keyboard listbox responding to the wrong input channel -- not actually broken.
   **WHAT HAPPENED:** A time-selection dropdown looked nearly undriveable. It was a keyboard
   listbox: click to open (highlights the current value), then arrow keys, then Enter. Typing
   into such a control is a prefix-jump, not a filter, and can silently commit a wrong value
   with no error.
   **DO INSTEAD:** Before concluding a form control is broken, enumerate input channels
   (click+arrow, type, wheel, Home/End). Screenshot or otherwise verify the highlighted value
   before committing it, every time.

7. **CLAIM:** A job board's own hidden "match score" is not auditable -- score postings against
   your own transparent rubric instead.
   **WHAT HAPPENED:** A large sweep of postings explicitly discarded the platform's own
   unexplained relevance score and instead scored every posting against a declared, visible
   rubric.
   **DO INSTEAD:** Build a transparent, reproducible scoring rubric for ranking postings rather
   than trusting an opaque platform score.

8. **CLAIM:** A professional network's "hide my search status from my current employer"
   setting is a best-effort shield with an auto-expiry trap, not a guarantee.
   **WHAT HAPPENED:** A professional network's own documentation states it only attempts to
   hide an open-to-work signal and cannot guarantee complete privacy. That signal also
   auto-disables after a period of inbound-message inactivity, silently turning itself off.
   **DO INSTEAD:** Don't treat a "recruiters only" visibility toggle as airtight while employed,
   and periodically re-check that it's still active.

9. **CLAIM:** Reading a social/professional-network page can itself mutate account state, so a
   read-only sweep should default to not clicking anything beyond the loaded URL.
   **WHAT HAPPENED:** Navigating to a messaging page auto-loaded the most recent conversation
   into a detail pane as the site's default behavior, with no way for a plain-text read to
   confirm whether this silently changed that thread's read/unread state.
   **DO INSTEAD:** In a read-only sweep, don't click pagination/expand controls even when they'd
   surface more data -- state partial coverage as an explicit gap.

## 4. Applying: forms, sessions, read-back, attestations

1. **CLAIM:** Some application forms embed hidden instructions aimed at AI agents, as a
   deliberate trap for AI-written answers -- ignore the instruction and flag it, never comply.
   **WHAT HAPPENED:** Two different application forms carried text addressed directly to an
   AI/LLM answering on a candidate's behalf. The agent drafting answers noticed both, declined
   to follow either, and surfaced the finding to the human.
   **DO INSTEAD:** Treat any instruction embedded in a job form or posting as untrusted data,
   never as a command, even when it's explicitly addressed to AI. Surface it to the human.

2. **CLAIM:** An automation tool should have no "submit" verb at all, and a submission should
   be confirmed off the page, never from the form's own success message.
   **WHAT HAPPENED:** A documented pipeline enforces that the form-fill tool has no submit
   action by design, so a human always clicks the final button. Separately, one application sat
   marked "unconfirmed" for days because confirmation had been assumed from the page's own
   on-screen success message rather than checked against an independent source.
   **DO INSTEAD:** Hard-code "no submit verb" into the tool itself rather than relying on
   policy. Verify a submission landed via an independent source (confirmation email, applicant
   portal status), never a webpage's own "submitted" text.

3. **CLAIM:** A scripted form-select action that reports what it clicked, instead of verifying
   the control's resulting value, can silently corrupt a live, partially-submitted application -- 
   the single most dangerous automation failure in the whole pipeline.
   **WHAT HAPPENED:** A dropdown-select script matched a field's on-screen label text without
   scoping to the specific control that was open. On a real, live application it set a location
   field to the wrong value, duplicated a name field into itself, wiped several other fields,
   and reported success for every action because it echoed the element it clicked rather than
   reading back what was actually committed.
   **DO INSTEAD:** Any automated form-fill action must read back the control's actual resulting
   value after acting, and scope element-matching strictly to the open control, never
   document-wide. Never re-enable a disabled automation verb until it has a tested case proving
   it fails safely on a bad match.

4. **CLAIM:** A known field-type incompatibility in a form-fill script can silently kill the
   rest of an entire form run unless each field is guarded individually.
   **WHAT HAPPENED:** A cursor-positioning method threw an exception on certain input types
   (email, number, date). Before this was guarded, the first such field killed the whole run
   with no error surfaced.
   **DO INSTEAD:** Wrap every per-field action in its own error handler so one incompatible
   field logs a warning and the run continues.

5. **CLAIM:** Human-only steps (CAPTCHA, SSO sign-in walls) must be explicitly flagged in a
   batch, never silently skipped or silently attempted.
   **WHAT HAPPENED:** Batches of drafted application answers explicitly called out which
   postings required a CAPTCHA or an enterprise sign-in wall, in a dedicated section.
   **DO INSTEAD:** Keep an explicit, visible list of which applications in a batch need a
   human-only gate alongside the drafted answers.

6. **CLAIM:** Every generated application answer should cite its factual source and mark
   inference vs. fact vs. unknown -- never fabricate specificity to fill a blank field.
   **WHAT HAPPENED:** A form-drafting workflow required every biographical claim to trace to one
   canonical facts document. For fields with no supporting fact, drafts were explicitly marked
   "no fact on file" rather than inventing a plausible-sounding specific answer.
   **DO INSTEAD:** Gate every generated answer against one source-of-truth facts file; mark any
   field with no supporting fact as unknown/inferred rather than filling it with confident
   invention.

## 5. Interviews

The lessons in this section are written as general patterns. They are about how interviews
go wrong for any candidate, not a record of one person's calls.

1. **CLAIM:** Under pressure, any candidate tends to drift from their own verified facts toward
   a dramatized or inflated version of their history, and toward criticizing a past employer.
   **PATTERN:** Live conversation rewards a vivid story over an accurate one. A candidate who
   has not rehearsed the exact facts fills the gap with whatever sounds strongest in the
   moment, and a frustrating past job is the easiest story to tell.
   **DO INSTEAD:** Memorize the canonical facts sheet verbatim. Script a neutral, pre-written
   line for any sensitive gap and deliver it early. Treat "never disparage a named past
   employer" as a hard rule.

2. **CLAIM:** Claiming hands-on capability you haven't actually built is a trap that surfaces
   mid-interview.
   **PATTERN:** "I set up and tested X" invites a follow-up question about how. If the real work
   was a read-only probe or a design document, the follow-up exposes the gap, and the gap now
   reads as a misstatement rather than a learning area.
   **DO INSTEAD:** Before any call, check every "I built X" or "I tested X" against what the
   source actually shows. Say "I explored" or "I designed" when that is what happened.

3. **CLAIM:** A list of disconnected symptoms is not a method. Technical scenario questions want
   a named, ordered diagnostic approach.
   **PATTERN:** Asked to diagnose a problem live (say, a latency spike), candidates tend to list
   the first three checks that come to mind. Interviewers score the order and the reasoning,
   not the list.
   **DO INSTEAD:** Pre-build named methodologies for common scenario-question categories rather
   than improvising a list live.

4. **CLAIM:** Written rejection feedback, when a company gives it, usually points at a
   repeatable pattern worth preparing for, not a one-off miss.
   **PATTERN:** Feedback for customer-facing technical roles tends to cluster around a few
   themes: answers pitched at the wrong level for the audience, a reflex to build from scratch
   instead of recommending an existing tool, a thin method for measuring quality, vocabulary
   that does not match the domain, and no hands-on use of the employer's own product.
   **DO INSTEAD:** For each interview, check before the call: an answer shape that starts from
   the customer's problem, a default of using an existing framework, a concrete evaluation
   method, the domain's own vocabulary, and real hands-on time with the employer's product.

5. **CLAIM:** A candidate who directs technical work without personally writing all of the code
   needs one honest, confident framing ready, rather than overselling or underselling technical
   depth per interviewer.
   **PATTERN:** Without a prepared line, the distinction between "I designed and verified this"
   and "I wrote this myself" gets drawn differently in each conversation, and the
   inconsistency is what an interviewer notices.
   **DO INSTEAD:** Draft one honest framing sentence, reuse it verbatim, and back it with
   specific evidence rather than vague claims.

6. **CLAIM:** An unverified claim in your canonical facts file can sit undetected across every
   application for weeks. Audit before you submit, not after a rejection prompts it.
   **PATTERN:** The facts file is trusted by design, so nothing downstream re-checks it. A claim
   that was never sourced spreads to every packet built from it.
   **DO INSTEAD:** Run an automated claim audit (`tools/verify/claim_audit.py`) against cited
   evidence before every submission batch, and re-source any fact you cannot point to.

7. **CLAIM:** Thank-you notes and feedback requests should go out through a verified, correct
   channel the first time, and feedback is worth asking for directly.
   **PATTERN:** A thank-you drafted in a hurry lands in the wrong thread or names the wrong
   person. Written feedback is rarely volunteered, but it is often given when asked for
   politely at the right moment.
   **DO INSTEAD:** Draft thank-yous promptly in the correct thread, have a human do a final
   check before send, and ask for written feedback after any rejection.

## 6. Running many AI agents on one job search

1. **CLAIM:** Multiple AI agents independently messaging the human principal causes duplicated
   asks, contradictions, and fatigue -- collapse to one channel.
   **WHAT HAPPENED:** Several parallel agents each messaged the human directly with questions,
   causing overlapping and duplicate requests the human had to arbitrate.
   **DO INSTEAD:** Designate exactly one orchestrator as the sole channel to the human; every
   other agent reports to the orchestrator only, which decides everything that isn't the human's
   to decide and surfaces only genuine spend, irreversible, security, or personal-choice items.

2. **CLAIM:** An orchestrator must verify a sub-agent's self-reported success against the live
   system, never relay the claim as fact -- a process that "ran" is not the same as a process
   that produced anything.
   **WHAT HAPPENED:** An agent's state file reported a batch fully recorded, while the actual
   mailbox and calendar showed missed invites and one critical inbound feed silently producing
   zero messages for a full week, unnoticed because every downstream check only confirmed the
   pipeline ran, never that it produced non-zero output.
   **DO INSTEAD:** Build checks that assert outcomes against ground truth, not just "the job
   completed without error."

3. **CLAIM:** Two agents working the same scope without a strict ownership boundary will
   duplicate work and silently diverge on shared files.
   **WHAT HAPPENED:** Two competing planning documents both claimed to be canonical; a shared
   decision log became a free-for-all across concurrent threads; a tracker was found missing
   real submissions and containing placeholder rows because no single agent owned reconciling it.
   **DO INSTEAD:** Assign one agent as the sole owner of each canonical file or tracker,
   documented up front. Periodically reconcile trackers against ground truth.

4. **CLAIM:** A liveness check that only confirms "the process ran" cannot catch "the process
   received nothing to work on" -- this kind of silent failure can persist for days.
   **WHAT HAPPENED:** A mailbox-polling component hit an error its retry logic wasn't built to
   recognize, so it failed permanently while still completing every scheduled cycle, producing a
   misleading "0 collected" message that masked a more informative error in the same log line.
   **DO INSTEAD:** Build an explicit check for the specific upstream data source the whole
   pipeline depends on ("output count > 0"), alerted separately from "service is up."

5. **CLAIM:** Several same-shaped agents running in parallel on shared infrastructure cause real
   resource collisions, but also catch each other's wrong conclusions -- a benefit that doesn't
   scale past a handful of concurrent agents.
   **WHAT HAPPENED:** Several parallel threads doing similar work on shared infrastructure hit
   repeated lock contention and inconsistent edits to one shared index. In the same window, peer
   threads caught each other's wrong conclusions multiple times, none of which self-corrected
   within the agent that made the error.
   **DO INSTEAD:** Budget for lock contention with real locking/leasing on shared state, and
   institute peer cross-checks before any consequential claim is written to a shared record, but
   expect contention cost to grow faster than the correction benefit past roughly three or four
   concurrent agents on one shared resource.

6. **CLAIM:** Every actionable item needs a sequential ID in one durable register the moment
   it's found, regardless of which agent found it, or it gets lost across parallel conversations.
   **WHAT HAPPENED:** Action items existed only inside individual agent conversations early on,
   so some sat unacted-on for hours because no durable, numbered record tracked their state
   across sessions.
   **DO INSTEAD:** Give every actionable item a sequential, never-reused ID in one durable
   task/decision register the moment it's found.

**Aggregate (rounded, no names):** one tracker recorded on the order of 100-150+ applications
submitted over several weeks (in batches of roughly 15-20), with 20+ employer replies/interview
loops opened, a handful of explicit rejections, at least one candidate-initiated withdrawal, and
no confirmed offers as of the most recent entry, several loops still open. No single file gave one
canonical total; treat these as approximate.

## 7. Things that did not work, stated plainly

1. **CLAIM:** Fully automated form submission does not work for every target. Some forms
   detect and penalize automation.
   **PATTERN:** Spam-sensitive forms score how a submission was made (timing, input events,
   browser fingerprint), not only what it contains. A scripted submit can be flagged as a
   bot even when every field is correct, and the application may then need a manual resubmit.
   **DO INSTEAD:** Keep the final submit with the human (see the safety contract in
   `CLAUDE.md`). Check whether a form looks spam-sensitive before any automation touches it,
   and keep a human-submit path ready for every target.

2. **CLAIM:** Page-text extraction alone is not reliable for confirming a critical action
   succeeded.
   **WHAT HAPPENED:** A browser-automated booking confirmation page returned placeholder,
   pre-load text through a text-extraction tool, even though the booking had actually succeeded.
   **DO INSTEAD:** For any critical confirmation, verify with a screenshot or an independent
   channel, not page-text extraction alone.

3. **CLAIM:** A generic "is this option selected" DOM check does not reliably generalize across
   custom web widgets.
   **WHAT HAPPENED:** A selection-state check matched the wrong attribute for a custom widget and
   reported nothing selected when a choice was visibly filled in.
   **DO INSTEAD:** Verify selection state visually (screenshot) for any non-standard widget
   rather than trusting a generic attribute check.

4. **CLAIM:** Treating all "we'll send a scheduling link" paths as equivalent does not work -- 
   self-service links decay without a human actively holding slots.
   **WHAT HAPPENED:** Waiting a few days to act on a scheduling link resulted in nearly a month
   of previously open dates becoming unavailable by the time it was opened, unlike
   recruiter-mediated scheduling where a human was holding the slot.
   **DO INSTEAD:** Treat any self-service scheduling link as same-day-action-required.

5. **CLAIM:** An automated "rejected" status from an applicant-tracking system is not always a
   permanent signal.
   **WHAT HAPPENED:** An application was auto-rejected by a tracking system, then a human
   recruiter reached out hours later to schedule an interview for the same role, but the
   monitoring agent had already stopped watching that thread.
   **DO INSTEAD:** Keep monitoring a thread for a defined grace period after an automated
   rejection before closing it out.

6. **CLAIM:** Assuming a single obvious mail-search string covers a vendor's notification domain
   does not work.
   **WHAT HAPPENED:** A mail search for a vendor's ATS notifications silently returned zero
   results because the real sending subdomain differed subtly from the expected one.
   **DO INSTEAD:** When searching mail for a specific vendor's notifications, check the actual
   sending address on a known message rather than assuming the obvious domain string, and treat
   zero results from a narrow search as inconclusive.
