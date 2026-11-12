"""H2 target: credit notes are numbered CN-<ENTITY>-<TENANT>-<YYYY>-<seq> with the entity of the credited invoice."""
from h2_helpers import credit_number, make_data_dir, write_invoice


def test_credit_note_number_has_the_invoices_entity(tmp_path):
    data = make_data_dir(tmp_path)
    assert credit_number(data, write_invoice(tmp_path, "inv", "MBDE")) == "CN-MBDE-AA-2026-00001"


def test_each_entity_numbers_its_own_credit_notes(tmp_path):
    data = make_data_dir(tmp_path, {"AA": "MBDE", "BB": "MBUS"})      # AA is invoiced by MBDE, BB by MBUS
    de = write_invoice(tmp_path, "de", "MBDE", "AA")
    us = write_invoice(tmp_path, "us", "MBUS", "BB")
    assert [credit_number(data, de), credit_number(data, us), credit_number(data, de), credit_number(data, us)] == [
        "CN-MBDE-AA-2026-00001", "CN-MBUS-BB-2026-00001", "CN-MBDE-AA-2026-00002", "CN-MBUS-BB-2026-00002"]
