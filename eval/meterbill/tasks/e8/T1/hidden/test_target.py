"""T1 target: a large invoice opens each tax file at most once per distinct country on it."""
from t1_helpers import build, count_tax_file_reads, event, make_data_dir, overrides_for

RATES = {c: [{"rate": r, "valid_from": "2024-01-01"}] for c, r in (("DE", "0.19"), ("FR", "0.20"), ("GB", "0.20"))}
METERS = [f"meter_{i:03d}" for i in range(170)]


def test_large_multi_country_invoice_reads_each_tax_file_per_country_at_most_once(tmp_path, monkeypatch):
    data = make_data_dir(tmp_path, METERS, RATES, overrides_for("GB", "0", "exempt"))
    events = [event(m, c) for m in METERS for c in ("DE", "FR", "GB")]
    with count_tax_file_reads(monkeypatch) as reads:
        invoice = build(data, events)
    # 170 meters x 3 countries = 510 lines; the 10 units of each cost 0.13 EUR
    assert len(invoice.lines) == 510
    countries = 3          # a per-(tenant, country) memo reads once per country; unchanged code reads once per line
    assert reads["tax_rates.json"] <= countries, dict(reads)
    assert reads["tax_overrides.json"] <= countries, dict(reads)
