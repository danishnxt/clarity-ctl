"""H1: invoice postings keep their shape, and credit note postings take accounts and tax from the invoice."""
from decimal import Decimal

import json

import pytest

from h1_helpers import MAPPING_2, issue_credit_note, issue_invoice, make_world, postings, split, total


def test_invoice_postings_are_unchanged(tmp_path):
    data, events, docs = make_world(tmp_path)
    issue_invoice(data, events, docs)
    invoice, _ = split(postings(tmp_path, data, docs))
    shape = sorted((p["account"], p["debit"], p["credit"]) for p in invoice)
    assert shape == sorted([("1200", "5.36", "0.00"), ("4010", "0.00", "1.01"), ("4020", "0.00", "3.50"),
                            ("2200-DE", "0.00", "0.19"), ("2200-DE", "0.00", "0.66")])


def test_credit_note_revenue_goes_to_the_accounts_the_invoice_posted_to(tmp_path):
    data, events, docs = make_world(tmp_path)
    issue_invoice(data, events, docs)
    (data / "accounts.json").write_text(json.dumps(MAPPING_2))          # the meters are remapped afterwards
    issue_credit_note(data, docs)
    _, credit = split(postings(tmp_path, data, docs))
    if not credit:
        pytest.skip("credit notes are not posted yet: the target tests cover that")
    revenue = sorted((p["account"], p["debit"]) for p in credit if p["account"] != "1200" and not p["account"].startswith("2200-"))
    assert revenue == [("4010", "1.01"), ("4020", "3.50")]


def test_credit_note_tax_postings_use_the_stored_tax_amounts(tmp_path):
    data, events, docs = make_world(tmp_path)
    issue_invoice(data, events, docs)
    (data / "tax_rates.json").write_text(json.dumps(
        {"DE": [{"rate": "0.19", "valid_from": "2024-01-01"}, {"rate": "0.25", "valid_from": "2026-06-01"}]}))
    issue_credit_note(data, docs)
    _, credit = split(postings(tmp_path, data, docs))
    if not credit:
        pytest.skip("credit notes are not posted yet: the target tests cover that")
    tax = sorted(p["debit"] for p in credit if p["account"] == "2200-DE")
    assert tax == ["0.19", "0.66"]
    assert total(credit, "debit") == total(credit, "credit") == Decimal("5.36")
