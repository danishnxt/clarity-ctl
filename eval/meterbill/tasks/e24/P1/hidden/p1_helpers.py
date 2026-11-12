"""Helpers for the P1 hidden tests: a throwaway data dir with stored invoices and unmatched payments."""
import contextlib
import io
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from meterbill.cli import main
from meterbill.invoices import Invoice, InvoiceLine, InvoiceStatus, invoice_to_json
from meterbill.money import Money
from meterbill.period import Period

LINE = re.compile(r"^(\S+) -> (\S+) (\d+(?:\.\d+)?) ([A-Z]{3})$")


def make_data_dir(tmp_path, tenant="AA"):
    data = tmp_path / "data"
    data.mkdir()
    (data / "plans.json").write_text(json.dumps({"plans": [{"id": "p", "name": "P", "currency": "EUR", "components": [
        {"meter": "m", "model": "per_unit", "unit_price": "1"}]}]}))
    (data / "tenants.json").write_text(json.dumps({"tenants": [
        {"id": tenant, "name": "Tenant", "plan_id": "p", "country": "DE"}]}))
    (data / "entities.json").write_text(json.dumps({"entities": [
        {"id": "MBDE", "country": "DE", "currency": "EUR"}, {"id": "MBUS", "country": "US", "currency": "USD"}]}))
    (data / "fx_rates.json").write_text(json.dumps({"2026-10-01": {"USD": "1.25"}, "2026-10-02": {"USD": "1.25"}}))
    (data / "tax_rates.json").write_text("{}")
    (data / "tax_overrides.json").write_text("{}")
    (data / "invoices").mkdir()
    return data


def add_invoice(data, seq, minor, due, tenant="AA", currency="EUR", status=InvoiceStatus.FINALIZED):
    number = f"INV-MBDE-{tenant}-2026-{seq:05d}"
    line = InvoiceLine("m", Decimal(1), Decimal(1), Money(minor, currency), "DE", Decimal(0), Money(0, currency))
    invoice = Invoice(tenant, tenant, Period.parse("2026-08"), currency, (line,), date(2026, 9, 1), number=number,
                      status=status, due_date=due, entity="MBDE")
    folder = Path(data) / "invoices" / tenant
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{number}.json").write_text(invoice_to_json(invoice))
    return number


def add_payment(data, minor, currency="EUR", on=date(2026, 10, 1), tenant="AA", reference=None):
    with open(Path(data) / "payments.jsonl", "a") as handle:
        handle.write(json.dumps({"tenant_id": tenant, "amount": minor, "currency": currency,
                                 "date": on.isoformat(), "reference": reference}) + "\n")


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    assert code == 0, (argv, err.getvalue())
    return out.getvalue()


def allocate(data, tenant="AA"):
    """The movement lines printed by `payments allocate`: (payment id, target, amount, currency)."""
    text = run("payments", "allocate", "--tenant", tenant, "--data-dir", str(data))
    moves = []
    for line in text.splitlines():
        if line.strip():
            m = LINE.match(line.strip())
            assert m, f"not a movement line: {line!r}"
            moves.append((m.group(1), m.group(2), Decimal(m.group(3)), m.group(4)))
    return moves


def show(data, number):
    """(open amount, settled) of a finalized invoice from `invoices show`."""
    text = run("invoices", "show", number, "--data-dir", str(data))
    open_line = next(l for l in text.splitlines() if l.startswith("Open:"))
    settled = next(l for l in text.splitlines() if l.startswith("Settled:")).split(":")[1].strip() == "yes"
    return open_line.split(":")[1].strip(), settled


def wallet(data, currency, tenant="AA"):
    return run("wallet", "balance", "--tenant", tenant, "--currency", currency, "--data-dir", str(data)).strip()


def require_allocate(tmp_path):
    """Skip (not fail) while `payments allocate` does not exist: the target tests cover that."""
    probe = make_data_dir(tmp_path / "probe") if (tmp_path / "probe").mkdir() is None else None
    try:
        allocate(probe)
    except SystemExit:
        pytest.skip("no payments allocate command yet")
