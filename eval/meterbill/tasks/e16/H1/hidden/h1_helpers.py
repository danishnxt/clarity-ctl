"""Helpers for the H1 hidden tests: a throwaway data dir and the invoice / credit / ledger commands run in process."""
import contextlib
import io
import json
from decimal import Decimal

from meterbill.cli import main

RATES = {"DE": [{"rate": "0.19", "valid_from": "2024-01-01"}]}
MAPPING_1 = {"meters": {"m1": "4010", "m2": "4020"}, "default": "4000"}
MAPPING_2 = {"meters": {"m1": "5010", "m2": "5020"}, "default": "5000"}


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    assert code == 0, (argv, err.getvalue())
    return out.getvalue()


def make_world(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "plans.json").write_text(json.dumps({"plans": [{"id": "p", "name": "P", "currency": "EUR", "components": [
        {"meter": "m1", "model": "per_unit", "unit_price": "0.1013"},
        {"meter": "m2", "model": "per_unit", "unit_price": "0.5"}]}]}))
    (data / "tenants.json").write_text(json.dumps({"tenants": [
        {"id": "HT", "name": "H Tenant", "plan_id": "p", "country": "DE"}]}))
    (data / "tax_rates.json").write_text(json.dumps(RATES))
    (data / "tax_overrides.json").write_text("{}")
    (data / "accounts.json").write_text(json.dumps(MAPPING_1))
    events = tmp_path / "events.jsonl"
    events.write_text("\n".join(json.dumps(
        {"tenant_id": "HT", "meter": m, "quantity": q, "timestamp": "2026-10-05T10:00:00+00:00",
         "event_id": f"e-{m}", "idempotency_key": f"k-{m}"}) for m, q in (("m1", "10"), ("m2", "7"))) + "\n")
    docs = tmp_path / "documents"
    docs.mkdir()
    return data, events, docs


def issue_invoice(data, events, docs):
    text = run("invoice", "--tenant", "HT", "--period", "2026-10", "--events", str(events), "--data-dir", str(data),
               "--finalize", "--issue-date", "2026-10-31", "--json")
    (docs / "invoice.json").write_text(text)
    return docs / "invoice.json"


def issue_credit_note(data, docs, *extra):
    text = run("credit", "--invoice", str(docs / "invoice.json"), "--reason", "goodwill", "--data-dir", str(data),
               "--issue-date", "2026-12-05", "--json", *extra)
    (docs / "creditnote.json").write_text(text)


def postings(tmp_path, data, docs):
    """{document number: [posting dicts]} from the ledger of the invoice's period and of the credit note's month."""
    found = {}
    for period in ("2026-10", "2026-12"):
        out = tmp_path / f"postings-{period}.jsonl"
        run("ledger", "--period", period, "--out", str(out), "--documents-dir", str(docs), "--data-dir", str(data))
        by_doc = {}
        for line in out.read_text().splitlines():
            if line.strip():
                p = json.loads(line)
                by_doc.setdefault(p["document_number"], []).append(p)
        for number, rows in by_doc.items():
            found.setdefault(number, rows)
    return found


def split(found):
    invoice = [rows for n, rows in found.items() if n.startswith("INV")]
    credit = [rows for n, rows in found.items() if n.startswith("CN")]
    return (invoice[0] if invoice else []), (credit[0] if credit else [])


def total(rows, key, only=lambda p: True):
    return sum((Decimal(p[key]) for p in rows if only(p)), Decimal(0))
