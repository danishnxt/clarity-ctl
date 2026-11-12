"""H1 target: credit notes appear in the ledger export as postings that reverse their invoice's postings."""
from decimal import Decimal

from h1_helpers import issue_credit_note, issue_invoice, make_world, postings, split, total


def revenue_row(p):
    return p["account"] != "1200" and not p["account"].startswith("2200-")


def test_full_credit_note_postings_balance_and_mirror_the_invoice(tmp_path):
    data, events, docs = make_world(tmp_path)
    issue_invoice(data, events, docs)
    issue_credit_note(data, docs)
    invoice, credit = split(postings(tmp_path, data, docs))
    assert invoice and credit
    for rows in (invoice, credit):
        assert total(rows, "debit") == total(rows, "credit") > 0
    assert len(credit) == len(invoice)
    # receivable: debited by the invoice, credited by the credit note, same gross
    assert total(invoice, "debit", lambda p: p["account"] == "1200") == total(credit, "credit", lambda p: p["account"] == "1200")
    # revenue and tax: credited by the invoice, debited by the credit note, same amounts
    assert total(invoice, "credit", revenue_row) == total(credit, "debit", revenue_row) == Decimal("4.51")
    assert total(invoice, "credit", lambda p: p["account"] == "2200-DE") == total(credit, "debit", lambda p: p["account"] == "2200-DE")
    assert {p["currency"] for p in credit} == {"EUR"}


def test_partial_credit_note_posts_only_its_line(tmp_path):
    data, events, docs = make_world(tmp_path)
    issue_invoice(data, events, docs)
    issue_credit_note(data, docs, "--line", "2")
    _, credit = split(postings(tmp_path, data, docs))
    assert credit
    assert total(credit, "debit") == total(credit, "credit")
    assert total(credit, "debit", revenue_row) == Decimal("3.50")
