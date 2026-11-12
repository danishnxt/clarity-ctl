"""H2: a credit note keeps the credited invoice's entity after the tenant moves, and counts on its own."""
import json
from datetime import date

from h2_helpers import (credit, credit_number, make_data_dir, require_credit_numbers_with_entity, write_invoice)
from meterbill.invoices import InvoiceStatus


def test_credit_note_after_the_tenant_moved_keeps_the_invoices_entity(tmp_path):
    require_credit_numbers_with_entity(tmp_path)
    data = make_data_dir(tmp_path, {"AA": "MBUS"})              # AA has moved to MBUS since the invoice was issued
    old_invoice = write_invoice(tmp_path, "old", "MBDE")
    new_invoice = write_invoice(tmp_path, "new", "MBUS", seq=1)
    assert credit_number(data, old_invoice) == "CN-MBDE-AA-2026-00001"
    assert credit_number(data, old_invoice) == "CN-MBDE-AA-2026-00002"      # still MBDE's counter
    assert credit_number(data, new_invoice) == "CN-MBUS-AA-2026-00001"      # MBUS counts separately


def test_sequence_is_per_entity_tenant_and_year(tmp_path):
    require_credit_numbers_with_entity(tmp_path)
    data = make_data_dir(tmp_path)
    aa, bb = write_invoice(tmp_path, "aa", "MBDE", "AA"), write_invoice(tmp_path, "bb", "MBDE", "BB")
    assert credit_number(data, aa, "2026-12-31") == "CN-MBDE-AA-2026-00001"
    assert credit_number(data, bb, "2026-12-31") == "CN-MBDE-BB-2026-00001"
    assert credit_number(data, aa, "2027-01-02") == "CN-MBDE-AA-2027-00001"
    assert credit_number(data, aa, "2026-12-31") == "CN-MBDE-AA-2026-00002"


def test_credit_note_sequence_is_separate_from_the_invoice_sequence(tmp_path):
    require_credit_numbers_with_entity(tmp_path)
    data = make_data_dir(tmp_path)
    (data / "sequences.json").write_text(json.dumps({"MBDE": {"AA": {"2026": 5}}}))     # five invoices issued
    before = (data / "sequences.json").read_text()
    assert credit_number(data, write_invoice(tmp_path, "inv", "MBDE", seq=5)) == "CN-MBDE-AA-2026-00001"
    assert (data / "sequences.json").read_text() == before


def test_a_refused_credit_note_leaves_no_gap(tmp_path):
    require_credit_numbers_with_entity(tmp_path)
    data = make_data_dir(tmp_path)
    draft = write_invoice(tmp_path, "draft", "MBDE", status=InvoiceStatus.DRAFT)
    code, _, _ = credit(data, draft)
    assert code != 0
    assert credit_number(data, write_invoice(tmp_path, "inv", "MBDE")) == "CN-MBDE-AA-2026-00001"


def test_existing_credit_note_documents_keep_their_numbers(tmp_path):
    require_credit_numbers_with_entity(tmp_path)
    data = make_data_dir(tmp_path)
    docs = data / "documents"
    docs.mkdir()
    legacy = docs / "legacy.json"
    legacy.write_text(json.dumps({
        "type": "credit_note", "number": "CN-AA-2026-00003", "invoice_number": "INV-AA-2026-00002", "tenant_id": "AA",
        "tenant_name": "Tenant AA", "currency": "EUR", "reason": "old", "issue_date": "2026-09-20",
        "lines": [{"invoice_line": 1, "meter": "m", "country": "DE", "quantity": "-1", "amount": -1000,
                   "tax_rate": "0", "tax_amount": 0}], "subtotal": -1000, "tax_total": 0, "total": -1000}))
    before = legacy.read_text()
    credit_number(data, write_invoice(tmp_path, "inv", "MBDE"))
    assert legacy.read_text() == before
    from meterbill.exports import load_documents
    assert "CN-AA-2026-00003" in {d.number for d in load_documents(docs)}
