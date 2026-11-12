<!-- CLARITY:START -->
## clarity

This project's state lives in clarity. Query it — don't crawl the tree, and
don't write its files by hand.

- Where things stand is at the end of this block, current as of the last clarity
  write; you don't need `status` or `--help` to get going. `show <id>` has every note,
  `show closed` every closed item. A fact not in the block: `search <words>` finds the item (often the note too),
  then `show <id>`.
- Start work: `clarity-ctl start "<name, a few words>" --repo <repo|all|none>
  --brief "<goal and limits>"`, or an idea's id in place of the name. One call: it
  branches the repos you name, makes the worktree, claims the epoch for you and prints
  where to work.
- Commands on an item take its id, always.
- Note the moment a decision changes — a reversal, an approach you rejected, a result
  that surprised you: `clarity-ctl note <id> "..."`. Not at the end: the notes are what
  the next session has instead of this conversation.
- A decision that outlives the epoch — a rule, a constraint, something we won't build
  and why: a note starting `DECISION:`. Every one is listed below for later sessions.
- The whole task done and merged: `clarity-ctl close <id> "<outcome>"`, which
  also releases it. The outcome says what changed and why — for a bug, what was wrong.
  Rejected: `close <id> --drop "<why>"`. An idea already built or unwanted closes
  the same way, unstarted. An epoch left open reads as unfinished.
- Part of it left for later, even with the rest merged: don't close it. Keep it active
  and write a note starting `HANDOFF:` — what's done, what's left, what to do first.
  Not an idea: an idea reads as optional, a handoff as next.
- Later, not now: `clarity-ctl idea "<a few words, like a title>"`, then the why and
  the evidence in a note on it: the name is what lists show, the note is the detail.
- Never hand-edit `worklog.yaml` or the generated block in `EPOCH.md`.
- `--json` is for scripts. Exit codes: 0 ok · 1 error · 2 validation · 3 not a clarity
  project · 4 refused.
- Splitting work across agents, taking over another agent's epoch, repos: `clarity-ctl
  --help`. If `.clarity/adopt.md` exists, adoption is unfinished: read it first.

### Where things stand

Generated from the worklog on every clarity write, so it is current. `clarity-ctl status` adds leases and branch warnings; `clarity-ctl show <id>` has every note.

**Objective:** Usage-billing library: metered events to invoices

**Active**
- none

**Up next:** #2 Persist finalized invoices atomically with sequence · #3 Tax calculation per tenant country · #4 Windows support for sequence lock (fcntl)

**Standing decisions**, newest first
- Zero third-party dependencies (stdlib only; deployment boxes have no internet). (#1)
- No float anywhere in money math. Money is integer minor units + ISO code; floats raise TypeError. Multiplication rounds half-up; from_major rejects excess precision unless a rounding mode is given. (#1)
- Invoice numbers INV-<TENANT>-<YYYY>-<5 digits> are gapless per tenant per year (auditor checks). build_invoice returns a draft with no number and never touches data/sequences.json; only finalize_invoice advances it (file lock, atomic write… (#1)
- Tiered pricing is graduated with inclusive upper bounds: unit 1000 bills at tier 1's price, unit 1001 at tier 2's (matches contract wording 'the first 1,000 units at...'; sales was burned by a quote read the other way). Do not change to ex… (#5)

**Closed**, newest first — `clarity-ctl show <id>` for the outcome and notes
#5 ✓ Tiered (graduated) pricing model · #1 ✓ meterbill library and CLI: events to invoices
<!-- CLARITY:END -->
