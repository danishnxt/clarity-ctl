"""Helpers for the X1 hidden tests: a throwaway data dir with event month files, reject files, invoices and credit notes."""
import contextlib
import io
import json
import os
import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from meterbill.cli import main
from meterbill.credits import CreditNote, CreditNoteLine, credit_note_to_json
from meterbill.invoices import Invoice, InvoiceLine, InvoiceStatus, invoice_to_json
from meterbill.money import Money
from meterbill.period import Period

TODAY = date(2026, 8, 15)


def make_data_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "plans.json").write_text(json.dumps({"plans": [{"id": "p", "name": "P", "currency": "EUR", "components": [
        {"meter": "m", "model": "per_unit", "unit_price": "1"}]}]}))
    (data / "tenants.json").write_text(json.dumps({"tenants": [
        {"id": "AA", "name": "Tenant A", "plan_id": "p", "country": "DE"},
        {"id": "BB", "name": "Tenant B", "plan_id": "p", "country": "DE"}]}))
    (data / "entities.json").write_text(json.dumps({"entities": [
        {"id": "MBDE", "country": "DE", "currency": "EUR"}, {"id": "MBUS", "country": "US", "currency": "USD"}]}))
    (data / "tax_rates.json").write_text("{}")
    (data / "tax_overrides.json").write_text("{}")
    (data / "invoices").mkdir()
    return data


def _stamp(path, day):
    moment = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc).timestamp()
    os.utime(path, (moment, moment))


def add_month_file(data, tenant, month, finalized=True):
    """events/<tenant>/<month>.jsonl with its .idem index; a finalized invoice for that period unless told not to."""
    year, mon = map(int, month.split("-"))
    folder = Path(data) / "events" / tenant
    folder.mkdir(parents=True, exist_ok=True)
    event = {"tenant_id": tenant, "meter": "m", "quantity": "1", "timestamp": f"{month}-10T10:00:00+00:00",
             "event_id": f"e-{month}", "idempotency_key": f"k-{month}", "properties": {}}
    (folder / f"{month}.jsonl").write_text(json.dumps(event) + "\n")
    (folder / f"{month}.idem").write_text(json.dumps(f"k-{month}") + "\n")
    end = date(year, mon, calendar.monthrange(year, mon)[1])
    _stamp(folder / f"{month}.jsonl", end)
    return add_invoice(data, tenant, month) if finalized else None


def add_invoice(data, tenant, month):
    year, mon = map(int, month.split("-"))
    number = f"INV-MBDE-{tenant}-{year}-{mon:05d}"
    line = InvoiceLine("m", Decimal(1), Decimal(1), Money(1000, "EUR"), "DE", Decimal(0), Money(0, "EUR"))
    invoice = Invoice(tenant, tenant, Period.parse(month), "EUR", (line,), date(year, mon, 28), number=number,
                      status=InvoiceStatus.FINALIZED, due_date=date(year, mon, 28), entity="MBDE")
    folder = Path(data) / "invoices" / tenant
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{number}.json").write_text(invoice_to_json(invoice))
    return number


def add_credit_note(data, invoice_number, tenant, issued, seq):
    line = CreditNoteLine(1, "m", "DE", Decimal(-1), Money(-1000, "EUR"), Decimal(0), Money(0, "EUR"))
    note = CreditNote(f"CN-{tenant}-{issued.year}-{seq:05d}", invoice_number, tenant, tenant, "EUR", "goodwill", issued, (line,))
    folder = Path(data) / "documents"
    folder.mkdir(exist_ok=True)
    (folder / f"{note.number}.json").write_text(credit_note_to_json(note))


def add_reject_file(data, day):
    folder = Path(data) / "rejects"
    folder.mkdir(exist_ok=True)
    path = folder / f"{day.isoformat()}.jsonl"
    path.write_text(json.dumps({"row": {}, "file": "f.jsonl", "line": 1, "reason": "bad"}) + "\n")
    _stamp(path, day)


def purge(data, *flags, today=TODAY):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["purge", "--date", today.isoformat(), "--data-dir", str(data), *flags])
    assert code == 0, err.getvalue()
    return [line.strip() for line in out.getvalue().splitlines() if line.strip()]


def exists(data, rel):
    return (Path(data) / rel).exists()


def printed_as(data, lines):
    """The printed paths relative to the data dir (printed absolute, relative to it, or relative to the cwd)."""
    base = Path(data).resolve()
    rels = []
    for line in lines:
        path = Path(line)
        for candidate in (path, base / path, Path.cwd() / path):
            try:
                rels.append(candidate.resolve().relative_to(base).as_posix())
                break
            except ValueError:
                continue
        else:
            raise AssertionError(f"printed path is not inside the data dir: {line!r}")
    return rels


def require_purge(tmp_path):
    """Skip (not fail) while `purge` does not exist: the target tests cover that."""
    probe = make_data_dir(tmp_path / "probe") if (tmp_path / "probe").mkdir() is None else None
    try:
        purge(probe)
    except SystemExit:
        pytest.skip("no purge command yet")
