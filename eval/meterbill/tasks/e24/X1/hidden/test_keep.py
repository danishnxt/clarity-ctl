"""X1: event files go 25 months after their period, rejects after 30 days, and some periods are never deleted."""
from datetime import date

from x1_helpers import (add_credit_note, add_invoice, add_month_file, add_reject_file, exists, make_data_dir,
                        printed_as, purge, require_purge)


def test_event_month_files_are_kept_for_25_months_after_the_period_ends(tmp_path):
    require_purge(tmp_path)
    data = make_data_dir(tmp_path)
    add_month_file(data, "AA", "2024-06")           # period ended 2024-06-30: 25.5 months before 2026-08-15
    add_month_file(data, "AA", "2024-07")           # period ended 2024-07-31: 24.5 months before
    purge(data)
    assert not exists(data, "events/AA/2024-06.jsonl")
    assert exists(data, "events/AA/2024-07.jsonl") and exists(data, "events/AA/2024-07.idem")


def test_reject_files_are_kept_for_30_days(tmp_path):
    require_purge(tmp_path)
    data = make_data_dir(tmp_path)
    add_reject_file(data, date(2026, 7, 15))        # 31 days old
    add_reject_file(data, date(2026, 7, 17))        # 29 days old
    assert printed_as(data, purge(data)) == ["rejects/2026-07-15.jsonl"]
    assert exists(data, "rejects/2026-07-17.jsonl")


def test_a_period_without_a_finalized_invoice_is_kept(tmp_path):
    require_purge(tmp_path)
    data = make_data_dir(tmp_path)
    add_month_file(data, "AA", "2023-01", finalized=False)
    add_month_file(data, "AA", "2023-04")
    assert printed_as(data, purge(data)) == ["events/AA/2023-04.jsonl"]
    assert exists(data, "events/AA/2023-01.jsonl") and exists(data, "events/AA/2023-01.idem")


def test_a_period_with_a_recent_credit_note_is_kept_and_an_old_one_does_not_protect(tmp_path):
    require_purge(tmp_path)
    data = make_data_dir(tmp_path)
    recent = add_month_file(data, "AA", "2023-02")
    add_credit_note(data, recent, "AA", date(2025, 9, 15), seq=1)       # 11 months before 2026-08-15
    stale = add_month_file(data, "AA", "2023-03")
    add_credit_note(data, stale, "AA", date(2025, 7, 15), seq=2)        # 13 months before
    assert printed_as(data, purge(data)) == ["events/AA/2023-03.jsonl"]
    assert exists(data, "events/AA/2023-02.jsonl")


def test_invoices_and_credit_notes_are_never_deleted(tmp_path):
    require_purge(tmp_path)
    data = make_data_dir(tmp_path)
    number = add_month_file(data, "AA", "2023-01")
    add_credit_note(data, number, "AA", date(2023, 3, 1), seq=1)
    purge(data)
    assert exists(data, f"invoices/AA/{number}.json") and exists(data, "documents/CN-AA-2023-00001.json")
