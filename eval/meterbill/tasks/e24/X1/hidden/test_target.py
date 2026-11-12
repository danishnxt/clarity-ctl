"""X1 target: old event month files and old reject files are deleted; --dry-run deletes nothing."""
from x1_helpers import add_month_file, add_reject_file, exists, make_data_dir, printed_as, purge
from datetime import date


def setup(tmp_path):
    data = make_data_dir(tmp_path)
    add_month_file(data, "AA", "2023-01")           # 43 months after its period end: far past any keep time
    add_month_file(data, "AA", "2026-07")           # recent
    add_reject_file(data, date(2026, 1, 27))        # 200 days old
    add_reject_file(data, date(2026, 8, 10))        # 5 days old
    return data


def test_old_files_are_deleted_and_recent_ones_kept(tmp_path):
    data = setup(tmp_path)
    printed = purge(data)
    assert sorted(printed_as(data, printed)) == ["events/AA/2023-01.jsonl", "rejects/2026-01-27.jsonl"]
    assert not exists(data, "events/AA/2023-01.jsonl") and not exists(data, "rejects/2026-01-27.jsonl")
    assert exists(data, "events/AA/2026-07.jsonl") and exists(data, "rejects/2026-08-10.jsonl")


def test_printed_paths_are_sorted_and_name_data_files_only(tmp_path):
    data = setup(tmp_path)
    add_month_file(data, "AA", "2023-02")
    add_month_file(data, "BB", "2023-01")
    printed = purge(data)
    assert printed == sorted(printed)
    assert printed_as(data, printed) == ["events/AA/2023-01.jsonl", "events/AA/2023-02.jsonl",
                                         "events/BB/2023-01.jsonl", "rejects/2026-01-27.jsonl"]
    assert not any(line.endswith(".idem") for line in printed)


def test_dry_run_prints_the_same_and_deletes_nothing(tmp_path):
    data = setup(tmp_path)
    dry = purge(data, "--dry-run")
    assert sorted(printed_as(data, dry)) == ["events/AA/2023-01.jsonl", "rejects/2026-01-27.jsonl"]
    assert exists(data, "events/AA/2023-01.jsonl") and exists(data, "events/AA/2023-01.idem")
    assert exists(data, "rejects/2026-01-27.jsonl")
    assert purge(data) == dry                         # a real run then deletes what the dry run listed


def test_index_of_a_deleted_month_goes_with_it_and_other_indexes_stay(tmp_path):
    data = setup(tmp_path)
    purge(data)
    assert not exists(data, "events/AA/2023-01.idem")
    assert exists(data, "events/AA/2026-07.idem")
