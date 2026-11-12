"""Helpers for the H2 hidden tests: invoice files of given entities and the credit command run in process."""
import contextlib
import io
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from meterbill.cli import main
from meterbill.invoices import Invoice, InvoiceLine, InvoiceStatus, invoice_to_json
from meterbill.money import Money
from meterbill.period import Period


def make_data_dir(tmp_path, tenant_entities=None):
    """Tenants AA and BB; ``tenant_entities`` maps a tenant to the entity it belongs to now."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    entities = tenant_entities or {}
    tenants = []
    for tid in ("AA", "BB"):
        record = {"id": tid, "name": f"Tenant {tid}", "plan_id": "p", "country": "DE"}
        if tid in entities:
            record["entity"] = entities[tid]
        tenants.append(record)
    (data / "plans.json").write_text(json.dumps({"plans": [{"id": "p", "name": "P", "currency": "EUR", "components": [
        {"meter": "m", "model": "per_unit", "unit_price": "1"}]}]}))
    (data / "tenants.json").write_text(json.dumps({"tenants": tenants}))
    (data / "entities.json").write_text(json.dumps({"entities": [
        {"id": "MBDE", "country": "DE", "currency": "EUR"}, {"id": "MBUS", "country": "US", "currency": "USD"}]}))
    (data / "tax_rates.json").write_text("{}")
    (data / "tax_overrides.json").write_text("{}")
    return data


def write_invoice(tmp_path, name, entity, tenant="AA", seq=1, status=InvoiceStatus.FINALIZED):
    """A finalized invoice file issued by ``entity`` with the number that entity gave it."""
    currency = "USD" if entity == "MBUS" else "EUR"
    number = f"INV-{entity}-{tenant}-2026-{seq:05d}" if status is InvoiceStatus.FINALIZED else None
    line = InvoiceLine("m", Decimal(1), Decimal(1), Money(10000, currency), "DE", Decimal(0), Money(0, currency))
    invoice = Invoice(tenant, tenant, Period.parse("2026-08"), currency, (line,), date(2026, 9, 1), number=number,
                      status=status, draft_id=None if number else "DRAFT-0123abcd",
                      due_date=date(2026, 9, 15) if number else None, entity=entity)
    path = Path(tmp_path) / f"{name}.json"
    path.write_text(invoice_to_json(invoice))
    return path


def credit(data, invoice_file, issued="2026-10-05", *extra):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["credit", "--invoice", str(invoice_file), "--reason", "goodwill", "--data-dir", str(data),
                     "--issue-date", issued, "--json", *extra])
    return code, out.getvalue(), err.getvalue()


def credit_number(data, invoice_file, issued="2026-10-05"):
    code, out, err = credit(data, invoice_file, issued)
    assert code == 0, err
    return json.loads(out)["number"]


def require_credit_numbers_with_entity(tmp_path):
    """Skip (not fail) while credit notes carry no entity at all: the target tests cover that."""
    data = make_data_dir(tmp_path / "probe") if (tmp_path / "probe").mkdir() is None else None
    if "MBDE" not in credit_number(data, write_invoice(tmp_path / "probe", "inv", "MBDE")):
        pytest.skip("credit note numbers have no entity yet")
