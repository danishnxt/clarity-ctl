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

**Objective:** Usage-billing library (Python 3.12, stdlib only): metered events to invoices. Code: workspace/meterbill

**Active**
- none

**Up next:** #4 Windows support for sequence lock (fcntl) · #8 Per-build_invoice tax lookup cache · #10 Prevent double credit of same invoice or line · #16 Export FX fields (original amount, rate) in CSV and credit notes · #17 Load real treasury-approved FX rates into data/fx_rates.json · #20 Repair/rebuild the ingest .seen index from event files · #21 Lock ingest runs so concurrent ingests cannot interleave · #22 Ingest: handle invalid UTF-8 mid-file without partial accept · #23 Ingest: crash between event write and seen-index write can double-store on rerun · #25 Confirm ZEN tenant plan and country in data/tenants.json · #26 Investigate why ZEN was double-billed despite invoice-time key dedupe · #27 Ingest dedupe across UTC months for retried events · 19 more: `clarity-ctl show next`

**Standing decisions**, newest first
- Outbox (meterbill/outbox/; data/outbox/<timestamp>-<8hex>.json, one JSON file per message, atomic write, gitignored) only QUEUES mail via Outbox.queue_mail(to, cc, subject, body, kind, ref); nothing in meterbill ever sends — these boxes ha… (#54)
- Billing entities (data/entities.json: MBDE DE/EUR, MBUS US/USD; Tenant.entity default MBDE). Invoice number = INV-<ENTITY>-<TENANT>-<YYYY>-<seq>, gapless per entity+tenant+year; sequences.json layout {ENTITY:{TENANT:{YEAR:n}}}. Invoice.ent… (#57)
- Not built yet, by user's request. A credit note takes the entity of the invoice it credits, even if the tenant has since moved entity. Numbers CN-<ENTITY>-<TENANT>-<YYYY>-<seq>, own gapless sequence per entity+tenant+year, SEPARATE from th… (#58)
- Not built yet, by user's request; extends #45 (oldest due_date first, ties lower invoice number). A payment in a different currency from the invoice is converted at the PAYMENT date's FX rate (FxConverter). If the amount left open after al… (#59)
- Wallet leftover rule (from user, with wallets #49): when an unmatched payment is bigger than everything open, the leftover is credited to the tenant's wallet in the PAYMENT's currency (WalletStore topup); we never refund automatically. DEC… (#45)
- Statements (meterbill/statements.py; CLI 'statements --tenant T --from D --to D [--csv FILE] [--data-dir]') are one statement per currency over an inclusive date range, balance starts at zero on --from (no opening balance carried in). Incl… (#48)
- Wallets (meterbill/wallets/store.py WalletStore; data/wallets.json = balance per tenant+currency, data/wallet_transactions.jsonl = append-only log, both written under a file lock; CLI 'wallet topup --tenant --amount --currency [--date]', '… (#49)
- Privacy scrub (meterbill/ingest/scrub.py). Event properties lose keys email, ip, phone, user_agent and any key starting 'pii_' at ingest (before store) and via 'events scrub --tenant T --period P' on stored month files (atomic rewrite like… (#52)
- Retention plan changed by the privacy review, SUPERSEDES #47's note: files in data/rejects are kept 30 days (not 90) because they hold raw rows we never accepted. Raw events stay 25 months after the END of their billing period. HARD RULE f… (#52)
- Invoice lifecycle draft -> finalized -> void. Drafts get id DRAFT-<8 hex> and no number; finalize assigns the next gapless number, freezes the invoice and sets due_date = finalize date + tenant payment_terms_days (tenants.json, default 14,… (#40)
- Payments (meterbill/payments/, data/payments.jsonl, one JSON payment per line, appended under a lock; CLI 'payments record --tenant --amount --currency --date [--reference]' and 'payments list --tenant [--unmatched]'). A payment matches an… (#44)
- Allocation rule agreed with finance: allocate to the invoice with the oldest due_date first; ties broken by the lower invoice number. Not built yet (#44 only matches by explicit reference). Context: unmatched payments are those with no ref… (#45)
- Retention policy (NOT built; purge is future work): raw events are kept 25 months after the END of their billing period; files in data/rejects are kept 90 days. Any purge must follow these. (#47)
- Ledger (meterbill/exports/ledger.py, 'python -m meterbill ledger --period YYYY-MM --out f.jsonl [--documents-dir] [--data-dir]') posts per invoice: one debit 1200 for gross; per line a revenue credit (account from data/accounts.json meters… (#37)
- Ingest dedupes on (tenant_id, idempotency_key), NOT event_id. This REVERSES #19's event_id dedupe. Why: the client SDK generates a fresh event_id on every retry but keeps idempotency_key stable, so retries got past event_id dedupe and ZEN… (#24)
- Mid-month plan changes. data/subscriptions.json = {"subscriptions": {tenant: [{plan_id, from: YYYY-MM-DD}]}}; 'from' is the FIRST local day on the new plan (date-only, so no local day is ever on two plans; duplicate dates rejected at load)… (#28)
- Volume pricing prices ALL units at the single tier the period total falls in, with EXCLUSIVE upper bounds: first tier whose up_to is strictly greater than the total (1000 -> tier 2; contracts say '1,000 or more units: 0.08'). This delibera… (#32)
- All price math (flat, per_unit, tiered, volume) lives in meterbill/pricing.py price_quantity(component, quantity, currency=None); rating and quote both call it so a quote and an invoice cannot disagree. Do not re-implement pricing elsewher… (#34)
- 'meterbill quote' output is plain aligned text only, no JSON/CSV mode, because sales pastes it into emails. Quotes use the standard tax rate (no tenant, so no tenant override), are in plan currency with no FX, and whole-plan quotes show fl… (#34)
- Tiered rating stays list-based permanently; we will not stream it. Why: support must answer 'which of my events were billed at which tier price' on a challenged tiered charge, which needs events walked through the tiers in (timestamp, even… (#14)
- 13 older: `clarity-ctl search DECISION`

**Closed**, newest first — `clarity-ctl show <id>` for the outcome and notes
#57 ✓ Billing entities and entity invoice numbers · #54 ✓ Outbox mail queue and finalize --notify · #52 ✓ PII scrub at ingest and events scrub · #49 ✓ Wallets: prepaid balance per tenant and currency · #48 ✓ Customer statements CLI and CSV · #47 ✓ Event store compaction and stats CLI · #46 ✗ Event store compaction and stats CLI · #44 ✓ Payments recording and matching · #40 ✓ Invoice lifecycle: draft/finalized/void store · #2 ✓ Persist finalized invoices atomically with sequen… · 18 older: `clarity-ctl show closed`
<!-- CLARITY:END -->
