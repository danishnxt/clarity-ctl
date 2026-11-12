"""D1: the second reminder is at due+28, and small balances and recently credited invoices are left alone."""
from datetime import timedelta

from d1_helpers import DUE, add_credit_note, add_invoice, add_payment, due_plus, dunning, make_data_dir, require_dunning

N1 = "INV-MBDE-EU1-2026-00001"


def test_second_reminder_is_at_due_plus_28_and_not_at_21(tmp_path):
    require_dunning(tmp_path)
    data = make_data_dir(tmp_path)
    add_invoice(data, "EU1", 1, 10000)
    assert dunning(data, due_plus(21)) == []
    assert dunning(data, due_plus(28)) == [f"{N1}  L2  to=ap@eu1.example  cc=cfo@eu1.example"]


def test_open_amount_below_five_euro_gets_no_reminder(tmp_path):
    require_dunning(tmp_path)
    data = make_data_dir(tmp_path)
    add_invoice(data, "EU1", 1, 499)       # 4.99 EUR
    add_invoice(data, "EU1", 2, 500)       # 5.00 EUR
    paid_down = add_invoice(data, "EU1", 3, 10000)
    add_payment(data, "EU1", paid_down, 9600)     # 4.00 EUR left
    assert dunning(data, due_plus(7)) == ["INV-MBDE-EU1-2026-00002  L1  to=ap@eu1.example  cc=cfo@eu1.example"]


def test_foreign_currency_open_amount_is_compared_in_euro(tmp_path):
    require_dunning(tmp_path)
    data = make_data_dir(tmp_path)
    add_invoice(data, "JP1", 1, 300, "JPY")        # about 1.88 EUR at 160 JPY per EUR
    add_invoice(data, "JP1", 2, 5000, "JPY")       # about 31.25 EUR
    assert dunning(data, due_plus(7)) == ["INV-MBDE-JP1-2026-00002  L1  to=ap@jp1.example"]


def test_recent_credit_note_stops_the_reminder_and_an_old_one_does_not(tmp_path):
    require_dunning(tmp_path)
    data = make_data_dir(tmp_path)
    on = due_plus(28)
    recent = add_invoice(data, "EU1", 1, 10000)
    add_credit_note(data, recent, "EU1", 100, on - timedelta(days=10), seq=1)
    old = add_invoice(data, "EU2", 1, 10000)
    add_credit_note(data, old, "EU2", 100, on - timedelta(days=40), seq=2)
    assert dunning(data, on) == ["INV-MBDE-EU2-2026-00001  L2  to=ap@eu2.example"]
