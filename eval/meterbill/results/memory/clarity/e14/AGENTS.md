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

**Up next:** #2 Persist finalized invoices atomically with sequence · #4 Windows support for sequence lock (fcntl) · #8 Per-build_invoice tax lookup cache · #10 Prevent double credit of same invoice or line · #16 Export FX fields (original amount, rate) in CSV and credit notes · #17 Load real treasury-approved FX rates into data/fx_rates.json · #20 Repair/rebuild the ingest .seen index from event files · #21 Lock ingest runs so concurrent ingests cannot interleave · #22 Ingest: handle invalid UTF-8 mid-file without partial accept · #23 Ingest: crash between event write and seen-index write can double-store on rerun · #25 Confirm ZEN tenant plan and country in data/tenants.json · #26 Investigate why ZEN was double-billed despite invoice-time key dedupe · 5 more: `clarity-ctl show next`

**Standing decisions**, newest first
- Ingest dedupes on (tenant_id, idempotency_key), NOT event_id. This REVERSES #19's event_id dedupe. Why: the client SDK generates a fresh event_id on every retry but keeps idempotency_key stable, so retries got past event_id dedupe and ZEN… (#24)
- Mid-month plan changes. data/subscriptions.json = {"subscriptions": {tenant: [{plan_id, from: YYYY-MM-DD}]}}; 'from' is the FIRST local day on the new plan (date-only, so no local day is ever on two plans; duplicate dates rejected at load)… (#28)
- Volume pricing prices ALL units at the single tier the period total falls in, with EXCLUSIVE upper bounds: first tier whose up_to is strictly greater than the total (1000 -> tier 2; contracts say '1,000 or more units: 0.08'). This delibera… (#32)
- Tiered rating stays list-based permanently; we will not stream it. Why: support must answer 'which of my events were billed at which tier price' on a challenged tiered charge, which needs events walked through the tiers in (timestamp, even… (#14)
- FX rates (data/fx_rates.json, EUR base, ECB-style) are never guessed. FxConverter uses the most recent rate on or before the date, per currency; cross rates go through EUR; a rate more than 7 days old (MAX_RATE_AGE_DAYS) raises FxError, wi… (#15)
- build_invoice converts each rated line (not the invoice total) into the tenant's billing_currency at the issue date, rounding HALF_EVEN, BEFORE tax; tax is then computed on the converted line amount. Each InvoiceLine stores fx_rate and ori… (#15)
- Event store layout is data/events/<tenant>/<YYYY-MM>.jsonl (UTC month of event timestamp) with a <YYYY-MM>.seen index (one event_id per line) beside it; rejects go to data/rejects/<YYYY-MM-DD>.jsonl (row, file, line, reason). Ingest dedupe… (#19)
- No tax data (tax_rates.json, tax_overrides.json) is cached across invoice runs, ever; every lookup reads the files from disk. This REVERSES #6's lru_cache decision. Why: the billing worker is long-running and ops hand-edit tax_overrides.js… (#7)
- Credit note lines never look up tax. They copy tax_rate from the original InvoiceLine and negate amount and tax_amount, so a refund after a rate change (e.g. FR last January) reverses exactly what was charged and the VAT return balances. C… (#9)
- CSV export (meterbill/exports/csv_export.py, 'python -m meterbill export --period YYYY-MM --out f.csv [--documents-dir data/documents]') uses ';' delimiter (German Excel) and amounts as major-unit decimal strings with exactly the currency'… (#12)
- Zero third-party dependencies (stdlib only; deployment boxes have no internet). (#1)
- No float anywhere in money math. Money is integer minor units + ISO code; floats raise TypeError. Multiplication rounds half-up; from_major rejects excess precision unless a rounding mode is given. (#1)
- Invoice numbers INV-<TENANT>-<YYYY>-<5 digits> are gapless per tenant per year (auditor checks). build_invoice returns a draft with no number and never touches data/sequences.json; only finalize_invoice advances it (file lock, atomic write… (#1)
- Tax is computed per invoice line: line amount * rate, rounded to the currency minor unit with ROUND_HALF_EVEN; invoice tax_total is the sum of the rounded line taxes. Never compute tax on the subtotal and round once: finance reconciles eac… (#3)
- Tax follows where usage happened: event properties['country'], falling back to the tenant's country. Rating splits lines by (meter, country); each line's rate comes from TaxResolver.rate_for(tenant, country, date) (tenant override first, e… (#3)
- Tiered pricing is graduated with inclusive upper bounds: unit 1000 bills at tier 1's price, unit 1001 at tier 2's (matches contract wording 'the first 1,000 units at...'; sales was burned by a quote read the other way). Do not change to ex… (#5)
- tax_rates.json and tax_overrides.json are read once per data_dir per process (functools.lru_cache on store.read_rates/read_overrides). Edits to them need a process restart, or store.read_rates.cache_clear() and store.read_overrides.cache_c… (#6)

**Closed**, newest first — `clarity-ctl show <id>` for the outcome and notes
#32 ✓ Volume pricing model · #28 ✓ Mid-month plan changes: subscriptions.json, prora… · #24 ✓ Ingest dedupe on (tenant_id, idempotency_key) · #19 ✓ File-drop event ingest into per-tenant monthly ev… · #18 ✓ Tiered event attribution · #14 ✗ Stream tiered rating (still collects quantities) · #15 ✓ Per-tenant billing currency with FX conversion · #13 ✓ Stream rating: running totals for flat and per_un… · #12 ✓ CSV export of invoices and credit notes for finan… · #11 ✓ Credit note JSON serialization and file output · 6 older: `clarity-ctl show closed`
<!-- CLARITY:END -->
