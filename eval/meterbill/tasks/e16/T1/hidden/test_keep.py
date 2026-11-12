"""T1 behaviour that must survive any speed-up."""
import json
from datetime import date
from decimal import Decimal

import pytest

from t1_helpers import build, event, make_data_dir, overrides_for, rewrite_same_timestamp, write_json
from meterbill.credits import issue_credit_note
from meterbill.invoices import SequenceStore, finalize_invoice
from meterbill.tax import TaxResolver

RATES_3 = {c: [{"rate": r, "valid_from": "2024-01-01"}] for c, r in (("DE", "0.19"), ("FR", "0.20"), ("GB", "0.20"))}
METERS_170 = [f"meter_{i:03d}" for i in range(170)]
RATES_DE = {"DE": [{"rate": "0.19", "valid_from": "2024-01-01"}]}


@pytest.mark.parametrize("reuse_resolver", [False, True], ids=["new_resolver_each_time", "same_resolver_object"])
def test_override_edited_between_invoices_is_used(tmp_path, reuse_resolver):
    from meterbill.invoices import build_invoice
    from meterbill.plans import load_catalog
    from t1_helpers import ISSUE, PERIOD, tenant

    data = make_data_dir(tmp_path, ["m"], RATES_DE, overrides_for("DE", "0.05"))
    resolver = TaxResolver(data)
    first = build_invoice(tenant(), PERIOD, [event("m", "DE")], load_catalog(data), ISSUE, resolver)
    # same byte length, same modification time: only the content differs
    rewrite_same_timestamp(data / "tax_overrides.json", overrides_for("DE", "0.07"))
    second = build_invoice(tenant(), PERIOD, [event("m", "DE")], load_catalog(data), ISSUE,
                           resolver if reuse_resolver else TaxResolver(data))
    assert first.lines[0].tax_rate == Decimal("0.05")
    assert second.lines[0].tax_rate == Decimal("0.07")


def test_rates_edited_between_invoices_is_used(tmp_path):
    data = make_data_dir(tmp_path, ["m"], RATES_DE, {})
    first = build(data, [event("m", "DE")])
    rewrite_same_timestamp(data / "tax_rates.json", {"DE": [{"rate": "0.17", "valid_from": "2024-01-01"}]})
    second = build(data, [event("m", "DE")])
    assert (first.lines[0].tax_rate, second.lines[0].tax_rate) == (Decimal("0.19"), Decimal("0.17"))


def test_each_line_tax_is_rounded_on_its_own_and_summed(tmp_path):
    # three lines of 0.50 EUR at 19%: 9.5 minor units each, half-even -> 10 each, total 30
    # (taxing the 1.50 EUR subtotal once would give 28.5 -> 28)
    data = make_data_dir(tmp_path, ["a", "b", "c"], RATES_DE, {}, unit_price="0.05")
    invoice = build(data, [event(m, "DE") for m in "abc"])
    assert [l.amount.minor for l in invoice.lines] == [50, 50, 50]
    assert [l.tax_amount.minor for l in invoice.lines] == [10, 10, 10]
    assert invoice.tax_total.minor == 30


def test_line_tax_rounds_half_even(tmp_path):
    # 1.50 EUR at 19% is 28.5 minor units: half-even gives 28 (half-up would give 29)
    data = make_data_dir(tmp_path, ["a"], RATES_DE, {}, unit_price="0.15")
    invoice = build(data, [event("a", "DE")])
    assert invoice.lines[0].amount.minor == 150
    assert invoice.lines[0].tax_amount.minor == 28


def test_credit_note_after_rate_change_reverses_original_tax(tmp_path):
    data = make_data_dir(tmp_path, ["a", "b"], RATES_DE, {})
    invoice = build(data, [event("a", "DE"), event("b", "DE")])
    invoice = finalize_invoice(invoice, SequenceStore(data / "sequences.json"))
    original = [(l.tax_rate, l.tax_amount) for l in invoice.lines]
    write_json(data / "tax_rates.json", {"DE": [{"rate": "0.19", "valid_from": "2024-01-01"},
                                                 {"rate": "0.25", "valid_from": "2026-01-01"}]})
    note = issue_credit_note(invoice, reason="goodwill", store=SequenceStore(data / "credit_sequences.json", "CN"),
                             issue_date=date(2026, 11, 15))
    assert [(l.tax_rate, -l.tax_amount) for l in note.lines] == original
    assert note.tax_total == -invoice.tax_total


def test_large_multi_country_invoice_taxes_every_line(tmp_path):
    # 170 meters x 3 countries = 510 lines of 0.13 EUR: 19% -> 0.02, 20% -> 0.03, exempt GB -> 0
    data = make_data_dir(tmp_path, METERS_170, RATES_3, overrides_for("GB", "0", "exempt"))
    invoice = build(data, [event(m, c) for m in METERS_170 for c in ("DE", "FR", "GB")])
    expected = {"DE": (Decimal("0.19"), 2), "FR": (Decimal("0.20"), 3), "GB": (Decimal("0"), 0)}
    assert len(invoice.lines) == 510
    for line in invoice.lines:
        assert (line.tax_rate, line.tax_amount.minor) == expected[line.country]
    assert invoice.tax_total.minor == 170 * (2 + 3 + 0)
