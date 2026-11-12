"""D1 target: the first reminder at due+7 and the final one at due+35 (copies finance), nothing on other days, --queue."""
from meterbill.outbox import Outbox

from d1_helpers import (FINANCE, DUE, add_invoice, add_payment, due_plus, dunning, make_data_dir)

N1 = "INV-MBDE-EU1-2026-00001"


def test_first_and_final_levels_with_contact_and_copies(tmp_path):
    data = make_data_dir(tmp_path)
    add_invoice(data, "EU1", 1, 10000)
    assert dunning(data, due_plus(7)) == [f"{N1}  L1  to=ap@eu1.example  cc=cfo@eu1.example"]
    assert dunning(data, due_plus(35)) == [f"{N1}  L3  to=ap@eu1.example  cc=cfo@eu1.example,{FINANCE}"]


def test_nothing_on_other_days(tmp_path):
    data = make_data_dir(tmp_path)
    add_invoice(data, "EU1", 1, 10000)
    for offset in (-3, 0, 1, 6, 8, 14, 29, 34, 36, 60):
        assert dunning(data, due_plus(offset)) == [], offset


def test_lines_are_sorted_by_invoice_number_and_cc_is_left_out_without_copies(tmp_path):
    data = make_data_dir(tmp_path)
    add_invoice(data, "EU2", 1, 10000)
    add_invoice(data, "EU1", 1, 10000)
    add_invoice(data, "EU1", 2, 20000)
    assert dunning(data, due_plus(7)) == [
        "INV-MBDE-EU1-2026-00001  L1  to=ap@eu1.example  cc=cfo@eu1.example",
        "INV-MBDE-EU1-2026-00002  L1  to=ap@eu1.example  cc=cfo@eu1.example",
        "INV-MBDE-EU2-2026-00001  L1  to=ap@eu2.example",
    ]
    assert dunning(data, due_plus(35))[-1] == f"INV-MBDE-EU2-2026-00001  L3  to=ap@eu2.example  cc={FINANCE}"


def test_paid_voided_and_draft_invoices_get_no_reminder(tmp_path):
    from meterbill.invoices import InvoiceStatus
    data = make_data_dir(tmp_path)
    paid = add_invoice(data, "EU1", 1, 10000)
    add_payment(data, "EU1", paid, 10000)
    add_invoice(data, "EU1", 2, 10000, status=InvoiceStatus.VOID)
    still_open = add_invoice(data, "EU1", 3, 10000)
    add_payment(data, "EU1", still_open, 4000)          # partly paid: still owed
    assert dunning(data, due_plus(7)) == [f"{still_open}  L1  to=ap@eu1.example  cc=cfo@eu1.example"]


def test_queue_writes_one_outbox_mail_per_reminder(tmp_path):
    data = make_data_dir(tmp_path)
    add_invoice(data, "EU1", 1, 10000)
    add_invoice(data, "EU2", 1, 10000)
    lines = dunning(data, due_plus(35), "--queue")
    assert len(lines) == 2
    mails = Outbox(data / "outbox").list()
    assert sorted((m.kind, m.ref, m.to, m.cc) for m in mails) == [
        ("reminder", "INV-MBDE-EU1-2026-00001", "ap@eu1.example", ("cfo@eu1.example", FINANCE)),
        ("reminder", "INV-MBDE-EU2-2026-00001", "ap@eu2.example", (FINANCE,)),
    ]
    assert dunning(data, due_plus(8), "--queue") == [] and len(Outbox(data / "outbox").list()) == 2
