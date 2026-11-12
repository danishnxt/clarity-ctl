# meterbill

Usage-billing library (Python 3.12, stdlib only). Code: workspace/meterbill.

## Keeping this file current
This file is the project's memory between sessions. At the end of every session, update it:
- Overview and architecture: what each module does, kept short.
- Decisions: rules we follow, each with its reason. Say when a decision replaced an older one.
- Rejected approaches: what was tried and removed, and why, so nobody tries it again.
- In progress: anything left half done, what is left and what to do first.
- Next: work the user has said is coming.
Keep it under 200 lines; prune what no longer matters, but never drop a decision or a
rejected approach that still applies.

## Overview and architecture
Package `meterbill/` (code under workspace/meterbill), tests in `tests/` (one file per module, plus CLI and shared conftest), seed data in `data/`.
- `money.py`: `Money` = integer minor units + ISO code; `CURRENCY_EXPONENT` (USD/EUR/GBP 2, JPY 0, KWD 3). add/sub/multiply by int or Decimal; `from_major`, `to_major`.
- `period.py`: `YYYY-MM` `Period`, UTC bounds, start inclusive / end exclusive; `first_day`, `end_day`, `days`; `contains(ts, tz=None)` checks the local calendar date.
- `events/`: `UsageEvent`, JSONL reader (`read_events` list, `stream_events` lazy generator), validation (errors carry line number), `dedupe_events` (list; built on lazy `iter_unique_events`).
- `plans/`: `Plan`, `PlanComponent`, `PricingModel` (flat, per_unit, tiered, volume), `Tier`, `Tenant`, `load_catalog` (plans.json + tenants.json + optional subscriptions.json, validated; `CatalogError`). `Tenant.tz` (IANA, default UTC, `zone` property) and `Tenant.subscriptions`. `segments.py` `segments_for` splits a local month into whole-day plan segments.
- `rating/`: `rate_events` streams events one at a time (filters tenant+period, lazy dedupe), keeps running Decimal totals per (meter, country), one line per plan component per country (tiered: one line per tier touched, label like `api_calls (1-1000)` stored in `RatedLine.meter`). Volume: one line per component per country, label `storage_gb (volume tier 2)`, summed like per_unit (`_rate_volume`). `RatedLine.country`; takes `default_country`.
- `tax/`: `store.py` (`read_rates`, `read_overrides`: the ONLY file access, optional `data_dir`; NOT cached: every call reads the file from disk), `resolver.py` (`TaxResolver.rate_for(tenant_id, country, on_date)`: tenant override first, else rate with latest `valid_from` <= date; missing rate raises `TaxError`). Data: `data/tax_rates.json`, `data/tax_overrides.json`.
- `invoices/`: `Invoice` (`subtotal`, `tax_total`, `total` = subtotal + tax), `InvoiceLine` (`country`, `tax_rate`, `tax_amount`), `build_invoice` (draft with `draft_id` `DRAFT-<8 hex>`, no number; computes per-line tax), `finalize_invoice(payment_terms_days, finalize_date)` (assigns number, sets `due_date`), `void_invoice` (finalized only, reason required), `Invoice.status` draft/finalized/void plus `due_date`, `void_reason`, `SequenceStore`. `invoices/store.py` `InvoiceStore`: `<root>/<TENANT>/<number-or-draft-id>.json`, root `<data-dir>/invoices`; finalize writes numbered file then deletes draft file; void rewrites in place; per-tenant lock; refs validated against path traversal. `Tenant.payment_terms_days` (default 14, non-negative int).
- `invoices/serialization.py`: `invoice_to_dict/from_dict/to_json/from_json`; Decimals as strings, money as minor units; load rejects malformed docs and totals not matching lines.
- `credits/`: `CreditNote`, `CreditNoteLine` (negative amounts), `issue_credit_note(invoice, lines=None, *, reason, store, issue_date=None)`; `lines` are 1-based positions on the invoice. Numbers `CN-<TENANTID>-<YYYY>-<5 digit seq>` from own sequence file `credit_sequences.json`. `SequenceStore` takes a `prefix` (default `INV`).
- `cli.py` / `__main__.py`: `invoice --tenant --period --events` plus `--data-dir` (also supplies tax files), `--finalize`, `--issue-date`, `--json` (emit invoice JSON, needed to make the file `credit` reads); `credit --invoice F [--line N ...] --reason ... [--data-dir] [--issue-date]` (no `--line` = whole invoice; `--json` emits credit note JSON to save for export); `export --period YYYY-MM --out F [--documents-dir, default data/documents]` writes the ERP CSV; `invoices create [--events --issue-date] | finalize <id> [--date] | void <number> --reason | list --tenant [--state] | show <id|number> [--json]` (lifecycle, uses InvoiceStore); errors to stderr, exit 1.
- `credits/serialization.py`: credit note JSON round-trip (Decimals as strings, minor units, totals checked on load). `CreditNoteLine.quantity` = negated original line quantity (needed by the CSV).
- `exports/csv_export.py`: `load_documents(dir)` reads `*.json` invoices/credit notes; writes one row per line: number, tenant, date, meter, quantity, net, tax rate, tax, gross. Drafts skipped; sorted by issue date then number.
- `pricing.py`: `price_quantity(component, quantity, currency=None)` -> list of `PricedPart(label, quantity, unit_price, amount)`; the ONLY pricing math (flat, per_unit, tiered inclusive, volume strictly-greater, half-up). `currency` needed except for flat (fee carries its own). Negative/non-finite quantity raises ValueError; zero quantity gives no parts for non-flat. `rating.engine._rate_plan` builds lines from it (flat parts prorated there).
- `quote.py`: `quote_meter`, `quote_plan`, `format_quote` (aligned plain text). CLI `quote --plan P (--meter M --quantity N | --usage a=1,b=2) [--country C] [--date D] [--data-dir]`; errors to stderr, exit 1. `tests/test_quote.py` checks quote == invoice for every seeded plan.
- `attribution.py`: `attribute(component, events, default_country=None)` walks events in `chronological_key` order (timestamp, then `event_id`; defined in `events/models.py`) through the tiers, one row per (event, tier), straddling events split in two; restarts per country; `tier_totals(rows, currency)` sums per (country, tier) with half-up like invoice tier lines. `pricing.tier_span` makes tier labels. CLI `attribution --tenant --period --meter --events [--data-dir]` prints rows plus per-tier totals (no per-row amounts: invoices round per tier total); exit 1 if meter not tiered on tenant's plan. Seed has no growth tenant, so CLI test adds one.
- `fx/`: `FxConverter(convert, rate, apply)`, `FxError`, `MAX_RATE_AGE_DAYS = 7`; `store.py` reads `data/fx_rates.json` (EUR base, ECB style, weekdays only, strictly validated). `Tenant.billing_currency` optional (None = plan currency). `InvoiceLine` has `fx_rate`, `original_amount` (both or neither); serialization writes them plus `original_currency`, old docs still load. CLI `fx convert AMOUNT FROM TO [--date]`, `fx rates [--date]`; `invoice` prints original/rate/converted for converted lines.
- Subscriptions (`data/subscriptions.json`, `{"subscriptions": {tenant: [{plan_id, from}]}}`, currently EMPTY): `rating.engine.rate_segments` rates events in one pass by local date of each event; `prorate` is exact integer math, HALF_EVEN; prorated flat line = quantity 1, unit price = prorated amount. `build_invoice` uses segments + tenant tz; each line converted to invoice currency separately. `EventStore.read_period(tz=)` also reads neighbouring UTC month files.
- `ingest/`: `store.py` (`EventStore` appends to `data/events/<tenant>/<YYYY-MM>.jsonl`, UTC month of timestamp, with `<YYYY-MM>.idem` index beside it (one JSON-encoded idempotency key per line; rebuilt from stored events if missing; `migrate_legacy_index()` converts old event_id `.seen` files and deletes them; `new_events()` = dry-run twin of `add_all()`); `read_period`; `RejectLog` appends row/file/line/reason to `data/rejects/<YYYY-MM-DD>.jsonl`). `importer.py` `ingest_drop` reads `.jsonl` and `.csv` (header row; five event columns required (idempotency_key optional in the header), optional JSON `properties` column, extra columns ignored) directly in the drop dir, reuses `parse_event`, dedupes on (tenant_id, idempotency_key) per tenant per month, rejects rows with absent/blank/non-string idempotency_key (reason `missing idempotency_key`), counts accepted/duplicate/rejected per tenant, moves files to `processed/` (numeric suffix on name clash). CLI `ingest --drop DIR | --check DIR [--data-dir]` (exactly one, else exit 2; `--check` is a dry run: same table plus a "Dry run" line, writes/logs/moves nothing; `ingest_drop(dry_run=)`; real runs migrate the index first); `invoice` reads the store when `--events` is omitted. `data/events/` and `data/rejects/` are gitignored.
- `exports/ledger.py`: double-entry postings for finalized invoices in a period (CLI `ledger --period YYYY-MM --out F [--documents-dir] [--data-dir]`, JSONL). Per invoice: debit 1200 gross; per line credit revenue account (meter -> account from `data/accounts.json` `{"meters":{...},"default":"4000"}`) with net; per line credit `2200-<country>` with tax. Fields: document_number, date (issue date), account, debit, credit, currency; amounts decimal strings with currency exponent, unused side "0.00". Drafts and credit notes skipped. Tests check each document balances (incl. JPY, KWD).
- Seed: 5 plans (starter USD, usage-eur, enterprise-jpy, growth USD tiered, volume USD: fee 99.00 + storage_gb tiers 1000/10000/null at 0.10/0.08/0.05; growth and volume have no tenant), 5 tenants (NWD Northwind DE per-unit EUR, ACM, GLB, TKY, ZEN). Tax seed: DE 0.19, FR 0.20, GB 0.20, US 0, JP 0.10; override ACM exempt in DE. TKY has `billing_currency` USD (plan JPY). Seed tz: NWD Europe/Berlin, ACM America/New_York, others UTC. 428 tests pass.
- `payments/`: `models.py` (`Payment`, `InvoiceBalance`: matched payments, credit-note total, paid total, open amount, `paid` when open <= 0), `store.py` (`PaymentStore` appends to `data/payments.jsonl` under a lock; rejects non-positive amounts, empty references, invalid or unknown tenant ids; matching computed on read, nothing written to invoices). CLI `payments record --tenant --amount --currency --date [--reference]`, `payments list --tenant [--unmatched]`; `invoices show` prints payments, credit notes, paid, open amount for finalized invoices (`--json` unchanged).

## Decisions
- Stdlib only, no third-party deps: deployment boxes have no internet.
- No float in money math; floats raise TypeError. Money multiply rounds half-up; `from_major` rejects excess precision unless a rounding mode is given.
- Invoice numbers `INV-<TENANTID>-<YYYY>-<5 digit seq>`, gapless per tenant per year (auditor checks). Sequence lives in data/sequences.json and advances ONLY in `finalize_invoice` (file lock, atomic write); `build_invoice` never touches it. Corrupt file or seq > 99999 raises without changing anything.
- Invoice year comes from the issue date, not billing period (my choice, unconfirmed: ask user if auditor wants period year).
- Unit prices are decimal strings in major units and may exceed currency precision (e.g. 0.0015 EUR); only the line amount is rounded.
- Flat components always yield a line; per-unit with zero usage yield none.
- Event for a meter the plan doesn't price raises an error (not silently dropped); out-of-period events are ignored first.
- Timestamps need a UTC offset and are stored as UTC; quantities non-negative, JSON numbers parsed as Decimal.
- Dedupe by (tenant, idempotency key).
- Tiered pricing is graduated with INCLUSIVE upper bounds: unit 1000 bills at the first tier's price, unit 1001 at the second. Reason: every contract words it "the first 1,000 units at..." and sales got burned by a quote read the other way. Tests cover every boundary (0, 1, 1000, 1001, 10000, 10001, 20000).
- Tier validation: non-empty, `up_to` positive whole numbers ascending, only the last tier has `up_to: null` and it must, prices non-negative. Whole-number bounds keep labels meaningful; fractional usage still works (1000.5 puts 0.5 in tier 2).
- Each tier line's amount is rounded half-up on its own (not summed then rounded).
- Tax is computed PER LINE: amount * rate rounded to minor unit with ROUND_HALF_EVEN; invoice tax total = sum of rounded line taxes. Never tax the subtotal and round once. Reason: finance reconciles each line against the ledger; invoice-level rounding was a cent off at Q3 close (Priya).
- Tax follows where usage happened: event `properties["country"]`, falling back to tenant country. Rating splits lines by (meter, country); each line's rate comes from `rate_for` for that line's country.
- `Invoice.total` now INCLUDES tax (was line sum; that is now `subtotal`).
- Tax rate date = invoice issue date (my choice, unconfirmed; period end would be a one-line change in builder.py). Same open question as the invoice-number year.
- Tiered pricing restarts per (meter, country) (my choice, unconfirmed): multi-country usage loses some volume discount vs tiering combined quantity. Ask user.
- Flat fees are taxed in the tenant's country.

- NO tax data cached across invoice runs, ever (user rule; replaced the earlier per-process `lru_cache` decision). Reason: the billing worker is long-running and ops hand-edit `tax_overrides.json`; ACM's revoked DE exemption was still applied at 0% for six hours because the cache never re-read it. `read_rates`/`read_overrides` read the files on every lookup. If speed is needed, cache only inside a single `build_invoice` call and discard it at the end (not built yet; do it when Northwind complains again; Northwind's run was ~40s, ~70% in `rate_for` re-reading JSON per line).
- Credit notes reverse the ORIGINAL line's stored `tax_rate`, `amount` and `tax_amount` (negated); NEVER call the tax resolver. Reason: FR's rate changed last January; a refund after a change must reverse exactly what was charged or the VAT return won't balance.
- Credit notes: only finalized invoices; reason required; the CN sequence number is taken only after all checks pass so a failed call leaves no gap. Own gapless sequence, separate from invoices.
- Credit note year comes from the issue date (same unconfirmed assumption as invoices).

- CSV export (finance ERP import): delimiter `;`; amounts are major-unit decimal strings with EXACTLY the currency exponent ("1500" JPY, "12.30" EUR, "1.250" KWD); the ERP rejects "1500.00" for JPY and fails the whole file. Credit note rows negative. Quantity/rate plain decimals, no exponent notation. UTF-8 without BOM. Date column = issue date; tenant column = tenant id (both my choice, unconfirmed).
- Export period filter (my choice, unconfirmed): invoices match on billing period; credit notes (no period) match on issue month. A single rule would mean storing period on credit notes. Ask user.
- Export reads saved JSON documents from a directory because nothing stores invoices/credit notes.

- Rating streams (user request, memory on big tenants): flat/per_unit keep only a running total per (meter, country). CLI `invoice` uses `stream_events`.
- Tiered rating stays list-based FOR GOOD (user decision; replaced the earlier "pending review" hold). Reason: support must answer "which events were billed at which tier price", which needs events walked through tiers in timestamp order; running totals can't. Tiered rating sorts events with `chronological_key`, the same as `attribute`, so invoices and attribution agree (test on 400 random events). Sorting changes no amounts (sums are order independent).

- FX (user rules): rate = most recent on or before the date, per currency (weekend uses Friday); cross rates via EUR; rate older than 7 days raises `FxError`, NEVER guess or fall back (treasury signs off every rate; failed run beats a guessed rate). Exactly 7 days is accepted.
- FX conversion in `build_invoice`: at the issue date, line by line (never the invoice total; same line-matching reason as tax), ROUND_HALF_EVEN, BEFORE tax; tax is computed on the converted amount. Rate fetched once per invoice.
- `FxConverter.rate()` rounds to 12 significant digits and convert/apply use exactly that rate, so the rate stored on a line reproduces its amount.
- A tenant billed in the plan's currency needs no fx file.

- Ingest dedupe key is (tenant_id, idempotency_key) (user decision; REPLACED event_id dedupe). Reason: the client SDK makes a new event_id on every retry (ZEN double-billed in October) but keeps idempotency_key stable. event_id is only an identifier. Events without idempotency_key are REJECTED ("missing idempotency_key"), not deduped on a hash of fields: user chose bouncing to the sender over guessing. A row with several problems reports only this reason.
- Ingest (my choices, unconfirmed): dedupe is per tenant per MONTH, so the same key in two months is stored twice (a retry landing in another UTC month is not caught at ingest; invoice builder still dedupes on idempotency key). Duplicates are counted but not written to rejects. Unsafe tenant ids (e.g. `../x`) are rejected; rows with no usable tenant count under `(unknown)`. A CSV missing required columns gives one reject at line 1 and stores nothing. Events are written BEFORE their ids enter the index: a crash between can store events twice on rerun, the reverse order would lose events (duplicates chosen over loss).

- Subscriptions (user rules): flat fee prorated fee*days_on_plan/days_in_period, HALF_EVEN per line, one line per segment labelled with dates; usage rated on the plan in force at the event's timestamp; days counted in the tenant's local tz; a plan change never takes effect mid-day (a Tokyo customer was charged for two plans on one day; promised impossible). Tenants without an entry stay on `plan_id`.
- Billing month and period filter are the tenant's LOCAL month, not UTC (event 2026-09-30 23:00Z is October in Berlin).
- `"from"` = first local day on the new plan (my interpretation, unconfirmed; if it is the day the change was made, shift one day in `segments_for`). Duplicate `from` dates rejected at load.
- Single-segment month keeps plain labels and full fee; `(start to end)` suffix only with several segments (flat and usage). Before the first entry the tenant's `plan_id` applies. Tiers restart per segment (my choice, unconfirmed). Mixed-currency plans: invoice currency = `billing_currency`, else the last plan's in the month (my choice).
- Volume pricing (user rule): ALL units priced at the one tier the total falls in, the first tier whose `up_to` is strictly GREATER than the total, so exactly 1000 is tier 2 (volume contracts say "1,000 or more units: 0.08"). Opposite of graduated tiered, which stays inclusive; deliberate, legal won't reword the contracts. Same tier JSON and validation as tiered. Tests put both models side by side at every boundary (graduated 1000 = 100.00, volume 80.00).
- Volume (my choices, unconfirmed): total is per (meter, country), like tiered restart; per segment on plan changes, same as tiers.

- Quotes and invoices share `price_quantity` (user request) so they cannot disagree; do not add pricing math elsewhere. Quote output is plain aligned text only, NO JSON (sales pastes it into emails).
- Quote (my choices, unconfirmed): whole-plan quote shows every flat fee in full (no proration); meter missing from `--usage` quoted at zero; tax only when `--country` given, per line half-even, STANDARD rate (no tenant, so no override); tax date `--date` default today.

- Ledger (user rules): one posting per line, NEVER netted across lines; postings per document must balance (tested). Accounts: AR 1200, tax payable `2200-<country>`, revenue from `data/accounts.json`.
- Ledger (my choices, unconfirmed): zero-tax line gets no tax posting; non-zero tax with no country is an error (no tax account); posting date = invoice issue date; `accounts.json` account numbers 4010/4020/4030 (default 4000) are MADE UP, accounting must replace them.

- Invoice lifecycle (user rules): draft -> finalized -> void. A voided number is never reused or freed. due_date = finalize date + tenant `payment_terms_days`. Void and credit notes: void invoices are excluded from CSV export and ledger (both take finalized only) and credit notes refuse them. Number year still from issue date.
- Lifecycle (my choices, unconfirmed): `invoices finalize --date` sets finalize date; no reversing ledger entry for voided invoices (not built); draft save never overwrites.

- Payments (user rules): a payment with a reference matches only a FINALIZED invoice of the SAME tenant whose number equals the reference; otherwise it stays unmatched. Open amount = gross - matched payments - credit notes; paid when open reaches zero; partial payments allowed.
- Payments (my choices, unconfirmed): payment must also match the invoice currency, else unmatched; overpayment gives negative open amount and counts as paid; credit notes are read from `<data-dir>/documents/*.json` (only place they exist; missing dir = none); matching derived on every read, not stored on the invoice.

## Rejected approaches
- Deduping key-less events on a hash of their fields: rejected by user; reject at ingest instead.
- Event_id as dedupe key: replaced, retries get new ids.
- Streaming/running totals for tiered rating: rejected by user, attribution needs ordered events (see Decisions).
- File-mtime checks to invalidate a tax cache (suggested idea, user ruled it out): config files are rsynced with times preserved, so an edited file can arrive with an old mtime.
- Process-lifetime `lru_cache` on tax file reads: removed, served stale exemptions (see Decisions).

## In progress
- TKY has no `tz` (still UTC) though it is the tenant behind the same-day double charge; user named only NWD and ACM. Ask; likely `"tz": "Asia/Tokyo"` in data/tenants.json.
- `attribution` CLI is not segment-aware: refuses a period where the tenant changes plan; uses the local month otherwise.
- `data/subscriptions.json` is empty (no real data); subscriptions untested on real events beyond tests.
- `invoices` CLI/InvoiceStore now persists invoices, but a crash after the sequence advances and before the numbered file is written leaves a number gap (no recovery step). Old `invoice --finalize` still only prints, does not store.

- CLI table for tiered lines (label in Meter column, tier price in Unit price column) has no dedicated test.

- Credit notes can be issued twice for the same invoice/line (double refund): credit notes are not stored, only the sequence counter advances. Fix: ledger of credited lines, checked in `issue_credit_note`. Offered to user, not yet approved.
- Credit notes now have JSON (`credit --json`), but nothing saves invoice/credit JSON into `data/documents` automatically; someone must save the output by hand. Fix with the persistence work above.
- Open for export: German Excel may misread `.` decimals and want a BOM for non-ASCII (current columns are ASCII); ERP unaffected.
- No CLI test for `--json` on `invoice`.

- Streaming rating: dedupe still holds a set of (tenant, idempotency key) for the period (grows with event count, far smaller than events). No dedicated test for `stream_events` or a malformed line midway; malformed-line errors now surface during rating, not at load (CLI catches both).

- `data/fx_rates.json` is GENERATED placeholder data (seeded random walk around the 2026-10-01 anchor), 2026-09-01..2026-11-30. Needs treasury sign-off/replacement with real rates before any real run. TKY invoices with issue date after ~2026-12-07 fail until more rates are loaded (7-day rule working as intended).
- CSV export and credit notes carry no FX fields (they work in billing currency; original amount/rate not exported). Ask user if finance wants them.

- ZEN tenant is a GUESS (plan `starter`, country `US`, name `ZEN`); user gave none. Ask and fix in data/tenants.json (drives invoices and tax).
- Retried ZEN events already stored under different event_ids remain in the month files (migration only collapses the index). `iter_unique_events` should already drop repeats at invoicing, so why ZEN was double-billed is NOT investigated; look at that first.
- Ingest: no locking, so concurrent ingest runs can interleave; a file with invalid UTF-8 midway keeps rows read before the bad bytes, logs one reject, and is still moved to `processed/`.
- `attribution` CLI and `attribute` accept only graduated tiered meters; a volume meter gives "is not a tiered meter". Volume has one line, nothing to attribute by tier; add support only if support asks.

- Quotes are in plan currency, no FX. No tenant tax override in quotes: offered a `--tenant` option, not approved.

- Ledger credit notes NOT built (user: later). Requirement: a credit note must post to the revenue accounts the ORIGINAL invoice posted to, not today's mapping (accounting remaps meters at year end). User's plan: store the revenue account on each `InvoiceLine` when the invoice is built (serialization must carry it, old docs need a fallback decision). Current ledger uses the current mapping for invoices only; do not apply it to credit notes.

## Known limits
- Sequence lock uses `fcntl`: macOS/Linux only, not Windows.

## Next
- Automatic allocation of unmatched payments (user: later, DON'T build yet). Agreed rule with finance: oldest due date first, ties broken by the lower invoice number.
- Payment reminders (user: later, DON'T build yet): first 7 days after due date, second 21 days, final notice 35 days that also copies finance@meterbill.example. Builds on `due_date`.
- Ledger postings for credit notes (see In progress); user said they come next.
- Per-`build_invoice`-call tax cache (discarded at end of call) when Northwind's run speed becomes a complaint again.
- Nothing else stated by the user beyond the open items above. Awaiting answers on tax date, per-country tiering.
