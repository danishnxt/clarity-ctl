"""P1: allocation order, voided invoices, wallet leftover and cross-currency write-off."""
from datetime import date
from decimal import Decimal

from p1_helpers import add_invoice, add_payment, allocate, make_data_dir, require_allocate, show, wallet
from meterbill.invoices import InvoiceStatus

D1, D2 = date(2026, 10, 10), date(2026, 10, 20)


def test_oldest_due_date_is_paid_first(tmp_path):
    require_allocate(tmp_path)
    data = make_data_dir(tmp_path)
    newer_due_lower_number = add_invoice(data, 1, 10000, D2)
    older_due = add_invoice(data, 2, 10000, D1)
    add_payment(data, 10000)
    assert [m[1] for m in allocate(data)] == [older_due]
    assert show(data, older_due)[1] is True and show(data, newer_due_lower_number)[1] is False


def test_equal_due_dates_pay_the_lower_invoice_number_first(tmp_path):
    require_allocate(tmp_path)
    data = make_data_dir(tmp_path)
    higher = add_invoice(data, 7, 10000, D1)
    lower = add_invoice(data, 3, 10000, D1)
    add_payment(data, 10000)
    assert [m[1] for m in allocate(data)] == [lower]
    assert show(data, higher)[1] is False


def test_payments_are_processed_in_date_order(tmp_path):
    require_allocate(tmp_path)
    data = make_data_dir(tmp_path)
    first = add_invoice(data, 1, 10000, D1)
    second = add_invoice(data, 2, 10000, D2)
    add_payment(data, 6000, on=date(2026, 10, 2))      # recorded first, dated later
    add_payment(data, 10000, on=date(2026, 10, 1))
    assert [(m[1], m[2]) for m in allocate(data)] == [(first, 100), (second, 60)]


def test_a_voided_invoice_is_never_allocated(tmp_path):
    require_allocate(tmp_path)
    data = make_data_dir(tmp_path)
    voided = add_invoice(data, 1, 10000, D1, status=InvoiceStatus.VOID)
    live = add_invoice(data, 2, 10000, D2)
    add_payment(data, 10000)
    moves = allocate(data)
    assert [m[1] for m in moves] == [live] and voided not in {m[1] for m in moves}


def test_leftover_goes_to_the_wallet_in_the_payments_currency(tmp_path):
    require_allocate(tmp_path)
    data = make_data_dir(tmp_path)
    first = add_invoice(data, 1, 10000, D1)
    second = add_invoice(data, 2, 10000, D2)
    add_payment(data, 25000)
    moves = allocate(data)
    assert [(m[1], m[2], m[3]) for m in moves] == [(first, 100, "EUR"), (second, 100, "EUR"), ("wallet", 50, "EUR")]
    assert wallet(data, "EUR") == "50.00 EUR"


def test_foreign_currency_leftover_goes_to_the_wallet_in_that_currency(tmp_path):
    require_allocate(tmp_path)
    data = make_data_dir(tmp_path)
    number = add_invoice(data, 1, 10000, D1)
    add_payment(data, 20000, currency="USD")          # 200.00 USD; at 1.25 USD per EUR the invoice takes 125.00 USD
    moves = allocate(data)
    assert [(m[1], m[2], m[3]) for m in moves] == [(number, 100, "EUR"), ("wallet", 75, "USD")]
    assert wallet(data, "USD") == "75.00 USD" and show(data, number)[1] is True


def test_converted_payment_leaving_under_half_a_unit_is_written_off(tmp_path):
    require_allocate(tmp_path)
    data = make_data_dir(tmp_path)
    number = add_invoice(data, 1, 10000, D1)
    add_payment(data, 12450, currency="USD")          # 124.50 USD = 99.60 EUR, 0.40 EUR short
    moves = allocate(data)
    assert [(m[1], m[2], m[3]) for m in moves] == [(number, Decimal("99.60"), "EUR"), ("6900", Decimal("0.40"), "EUR")]
    assert show(data, number) == ("0.00 EUR", True)


def test_converted_payment_leaving_half_a_unit_or_more_stays_open(tmp_path):
    require_allocate(tmp_path)
    data = make_data_dir(tmp_path)
    number = add_invoice(data, 1, 10000, D1)
    add_payment(data, 12400, currency="USD")          # 124.00 USD = 99.20 EUR, 0.80 EUR short
    assert [(m[1], m[2]) for m in allocate(data)] == [(number, Decimal("99.20"))]
    assert show(data, number) == ("0.80 EUR", False)

