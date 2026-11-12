"""Helpers for the D1 hidden tests: a throwaway data dir with stored invoices, payments, credit notes and contacts."""
import contextlib
import io
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from meterbill.cli import main
from meterbill.credits import CreditNote, CreditNoteLine, credit_note_to_json
from meterbill.invoices import Invoice, InvoiceLine, InvoiceStatus, invoice_to_json
from meterbill.money import Money
from meterbill.period import Period

ISSUE = date(2026, 9, 1)          # also the finalize date in every fixture
DUE = ISSUE + timedelta(days=14)  # payment terms 14 days
FINANCE = "finance@meterbill.example"


def due_plus(days):
    return DUE + timedelta(days=days)


def make_data_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "plans.json").write_text(json.dumps({"plans": [{"id": "p", "name": "P", "currency": "EUR", "components": [
        {"meter": "m", "model": "per_unit", "unit_price": "1"}]}]}))
    (data / "tenants.json").write_text(json.dumps({"tenants": [
        {"id": "EU1", "name": "Euro One", "plan_id": "p", "country": "DE"},
        {"id": "EU2", "name": "Euro Two", "plan_id": "p", "country": "FR"},
        {"id": "JP1", "name": "Japan One", "plan_id": "p", "country": "JP", "billing_currency": "JPY"}]}))
    (data / "entities.json").write_text(json.dumps({"entities": [
        {"id": "MBDE", "country": "DE", "currency": "EUR"}, {"id": "MBUS", "country": "US", "currency": "USD"}]}))
    (data / "contacts.json").write_text(json.dumps({
        "EU1": {"billing_contact": "ap@eu1.example", "cc": ["cfo@eu1.example"]},
        "EU2": {"billing_contact": "ap@eu2.example"},
        "JP1": {"billing_contact": "ap@jp1.example"}}))
    (data / "fx_rates.json").write_text(json.dumps({"2026-09-01": {"JPY": "160.00", "USD": "1.25"}}))
    (data / "tax_rates.json").write_text("{}")
    (data / "tax_overrides.json").write_text("{}")
    (data / "invoices").mkdir()
    return data


def add_invoice(data, tenant, seq, minor, currency="EUR", status=InvoiceStatus.FINALIZED):
    """A stored invoice of ``minor`` minor units (no tax), issued and finalized on ISSUE."""
    number = f"INV-MBDE-{tenant}-2026-{seq:05d}"
    line = InvoiceLine("m", Decimal(1), Decimal(1), Money(minor, currency), "DE", Decimal(0), Money(0, currency))
    invoice = Invoice(tenant, tenant, Period.parse("2026-08"), currency, (line,), ISSUE, number=number,
                      status=status, due_date=DUE, entity="MBDE")
    folder = Path(data) / "invoices" / tenant
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{number}.json").write_text(invoice_to_json(invoice))
    return number


def add_payment(data, tenant, number, minor, currency="EUR"):
    with open(Path(data) / "payments.jsonl", "a") as handle:
        handle.write(json.dumps({"tenant_id": tenant, "amount": minor, "currency": currency,
                                 "date": "2026-09-10", "reference": number}) + "\n")


def add_credit_note(data, invoice_number, tenant, minor, issued, seq=1, currency="EUR"):
    line = CreditNoteLine(1, "m", "DE", Decimal(-1), Money(-minor, currency), Decimal(0), Money(0, currency))
    note = CreditNote(f"CN-{tenant}-2026-{seq:05d}", invoice_number, tenant, tenant, currency, "goodwill", issued, (line,))
    folder = Path(data) / "documents"
    folder.mkdir(exist_ok=True)
    (folder / f"{note.number}.json").write_text(credit_note_to_json(note))


def dunning(data, on, *flags):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["dunning", "--date", on.isoformat(), "--data-dir", str(data), *flags])
    assert code == 0, err.getvalue()
    return [line for line in out.getvalue().splitlines() if line.strip()]


def require_dunning(tmp_path):
    """Skip (not fail) when `dunning` does not exist at all: the target tests cover that."""
    probe = make_data_dir(tmp_path / "probe") if (tmp_path / "probe").mkdir() is None else None
    try:
        dunning(probe, date(2026, 1, 1))
    except SystemExit:
        pytest.skip("no dunning command yet")
