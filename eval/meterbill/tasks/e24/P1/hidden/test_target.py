"""P1 target: unmatched payments are allocated to open invoices and the invoices reflect it."""
from datetime import date

from p1_helpers import add_invoice, add_payment, allocate, make_data_dir, show

D1, D2 = date(2026, 10, 10), date(2026, 10, 20)


def test_payment_exactly_covering_an_invoice_is_allocated_to_it(tmp_path):
    data = make_data_dir(tmp_path)
    number = add_invoice(data, 1, 10000, D1)
    add_payment(data, 10000)
    moves = allocate(data)
    assert [(m[1], m[2], m[3]) for m in moves] == [(number, 100, "EUR")]
    assert show(data, number) == ("0.00 EUR", True)
    assert allocate(data) == []                      # the payment is not allocated twice


def test_partial_payment_leaves_the_rest_open(tmp_path):
    data = make_data_dir(tmp_path)
    number = add_invoice(data, 1, 10000, D1)
    add_payment(data, 4000)
    assert [(m[1], m[2]) for m in allocate(data)] == [(number, 40)]
    assert show(data, number) == ("60.00 EUR", False)


def test_payment_spread_over_two_invoices_prints_one_line_per_target(tmp_path):
    data = make_data_dir(tmp_path)
    first = add_invoice(data, 1, 10000, D1)
    second = add_invoice(data, 2, 10000, D2)
    add_payment(data, 15000)
    moves = allocate(data)
    assert len(moves) == 2 and len({m[0] for m in moves}) == 1
    assert sorted((m[1], m[2]) for m in moves) == sorted([(first, 100), (second, 50)]) or \
        sorted((m[1], m[2]) for m in moves) == sorted([(first, 50), (second, 100)])
    assert {m[1] for m in moves} == {first, second}
    assert {m[3] for m in moves} == {"EUR"}


def test_already_matched_payments_are_left_alone(tmp_path):
    data = make_data_dir(tmp_path)
    number = add_invoice(data, 1, 10000, D1)
    add_payment(data, 10000, reference=number)
    assert allocate(data) == []
    assert show(data, number) == ("0.00 EUR", True)
