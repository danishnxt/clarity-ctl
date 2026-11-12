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
- `period.py`: `YYYY-MM` `Period`, UTC bounds, start inclusive / end exclusive.
- `events/`: `UsageEvent`, JSONL reader, validation (errors carry line number), `dedupe_events`.
- `plans/`: `Plan`, `PlanComponent`, `PricingModel` (flat, per_unit, tiered), `Tier`, `Tenant`, `load_catalog` (plans.json + tenants.json, validated).
- `rating/`: `rate_events` filters tenant+period, dedupes, totals usage per (meter, country), one line per plan component per country (tiered: one line per tier touched, label like `api_calls (1-1000)` stored in `RatedLine.meter`). `RatedLine.country`; takes `default_country`.
- `tax/`: `store.py` (`read_rates`, `read_overrides`: the ONLY file access, optional `data_dir`; both `@lru_cache(maxsize=None)`: each file read once per data_dir per process), `resolver.py` (`TaxResolver.rate_for(tenant_id, country, on_date)`: tenant override first, else rate with latest `valid_from` <= date; missing rate raises `TaxError`). Data: `data/tax_rates.json`, `data/tax_overrides.json`.
- `invoices/`: `Invoice` (`subtotal`, `tax_total`, `total` = subtotal + tax), `InvoiceLine` (`country`, `tax_rate`, `tax_amount`), `build_invoice` (draft, no number; computes per-line tax), `finalize_invoice` (assigns number), `SequenceStore`.
- `cli.py` / `__main__.py`: `invoice --tenant --period --events` plus `--data-dir` (also supplies tax files), `--finalize`, `--issue-date`; errors to stderr, exit 1.
- Seed: 4 plans (starter USD, usage-eur, enterprise-jpy, growth USD tiered; growth has no tenant), 4 tenants (NWD Northwind DE per-unit EUR, ACM, GLB, TKY). Tax seed: DE 0.19, FR 0.20, GB 0.20, US 0, JP 0.10; override ACM exempt in DE. 161 tests pass.

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

- Tax file reads are cached per process with `lru_cache` on `read_rates`/`read_overrides`. Reason: Northwind's run took ~40s, ~70% in `rate_for` re-reading the JSON per line (user's profile; speed-up after the change not measured). Replaced the older "each call reads the file" behavior. Cached dicts are shared: never mutate them. Edits to tax JSON need a restart, or `store.read_rates.cache_clear()` and `store.read_overrides.cache_clear()`. Cache key is the `data_dir` argument as given, so str vs Path is cached separately (harmless). Tests that change tax files must clear the caches.

## Rejected approaches
- None yet.

## In progress
- Finalize does not persist the invoice, only prints it. If the process dies after the number is consumed there is a gap. Fix: persist invoice and sequence together (first thing to do for a real audit trail).

- CLI table for tiered lines (label in Meter column, tier price in Unit price column) has no dedicated test.

## Known limits
- Sequence lock uses `fcntl`: macOS/Linux only, not Windows.

## Next
- Nothing stated by the user yet beyond the open items above. Awaiting answers on tax date, per-country tiering.
