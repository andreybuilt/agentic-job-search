# ATS gotchas

Vendor-specific traps, learned the hard way, that apply whether or not you automate anything.
These are facts about the vendors' forms, not about any particular employer or applicant.

## General, across every vendor

- **A generic "is this selected" DOM check does not generalize.** Custom dropdown/combobox
  widgets often don't expose selection state through the attribute a generic check expects.
  Verify visually (a screenshot) for any non-standard control rather than trusting a plain
  attribute read.
- **A keyboard listbox is not a type-ahead filter.** A date/time picker that ignores typed text
  and barely responds to the scroll wheel is usually a keyboard listbox: click to open (this
  highlights the current value), then arrow keys, then Enter. Typing into it is a prefix-jump
  that can silently commit the wrong value with no error.
- **React-style fields need a native value-setter, not a plain `.value =` assignment**, followed
  by a dispatched `input` and `change` event, or the framework's own state never notices the
  field changed and silently reverts it.
  JS native-setter pattern:
  ```js
  const proto = window.HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
  setter.call(inputEl, "the value");
  inputEl.dispatchEvent(new Event("input", { bubbles: true }));
  inputEl.dispatchEvent(new Event("change", { bubbles: true }));
  ```
- **A résumé parser will mangle your name or phone number often enough that you should always
  read back every auto-parsed field before submit.** Never trust the parse; verify it populated
  what you think it populated.
- **Page-text extraction is not proof a critical action succeeded.** A booking/confirmation page
  can return stale, pre-load placeholder text to a text-extraction tool even after the real
  action succeeded. Screenshot or use an independent channel (confirmation email) for anything
  that matters.
- **A field-type incompatibility in a cursor-positioning or autofill routine can silently kill
  the rest of the form.** Wrap every per-field action in its own error handler so one bad field
  logs a warning instead of aborting the whole run with nothing filled past that point.

## Greenhouse

- Public job-board JSON API exists per company (`boards-api.greenhouse.io`) -- good for sourcing
  and liveness checks without touching the apply form itself.
  this stack's "0 results" baseline differs from other vendors; confirm whether a zero count
  means "no open roles" or "this tenant isn't on the platform" before trusting it (Lesson 3.3).
- Application forms are frequently embedded in an iframe on the employer's own careers page;
  confirm you are filling the iframe's form, not the parent page.

## Ashby

- Also exposes a public job-board API per company, structurally similar to Greenhouse's.
- Ashby-hosted self-schedule interview booking pages are the other common surface
  (`tools/build/book_link.py` targets this and Calendly-style pages). Expect a
  CAPTCHA on first load from some tenants; stop and hand off, never attempt to solve it.

## Workday

- The heaviest, slowest, most custom-widget-dense of the major ATS platforms. Expect multi-page
  wizards, "Add Another" repeating sections (education, work history) that can silently reset if
  you navigate backward, and session timeouts mid-form on long applications.
- Workday's own search/filter widgets are a common source of the "keyboard listbox" trap above.
- No simple public job-search API comparable to Greenhouse/Ashby/Lever exists across all Workday
  tenants; expect to read the rendered page, not query an API.

## iCIMS

- Older, more varied templates per employer -- less consistency between two companies' iCIMS
  instances than between two Greenhouse instances. Treat each employer's iCIMS form as its own
  thing rather than assuming a pattern transfers.
- Frequently gates the actual application behind an account-creation step; budget for a
  sign-in/account-creation wall as a human-only step, not something to automate past.

## Lever

- Public job-postings API per company, lighter-weight than Greenhouse's. Straightforward for
  sourcing and liveness checks.
- Application forms are usually a single page; the main trap is custom resume-upload/parse
  widgets that silently truncate or mis-split a name across first/last fields -- read back the
  parsed name before submit.

## A 404 is not a closure, for any vendor

If a vendor-hosted board page, apply page, or board root returns "not found," that is evidence
the employer isn't using that vendor for this role -- not evidence the role is closed. Check the
employer's own careers domain before writing off a target (Lesson 3.1). The same applies to an
API returning an error code for every tenant you query, including ones that cannot exist: that
error code discriminates nothing and should not be read as "closed" (Lesson 3.3).
