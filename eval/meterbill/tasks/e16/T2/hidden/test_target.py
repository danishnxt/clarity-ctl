"""T2 target: quotes carry a next-tier hint for tiered and volume components."""
from decimal import Decimal

from t2_helpers import hints, make_data_dir, run_quote


def test_tiered_quote_has_hint_with_next_tier_price(tmp_path):
    (hint,) = hints(run_quote(make_data_dir(tmp_path), "--plan", "tiered-plan", "--meter", "t_calls", "--quantity", "50"))
    assert hint != "top" and hint[0] > 0 and hint[1] == Decimal("0.08")


def test_volume_quote_has_hint_with_next_tier_price(tmp_path):
    (hint,) = hints(run_quote(make_data_dir(tmp_path), "--plan", "volume-plan", "--meter", "v_gb", "--quantity", "50"))
    assert hint != "top" and hint[0] > 0 and hint[1] == Decimal("0.08")


def test_second_tier_points_at_third_tier_price(tmp_path):
    data = make_data_dir(tmp_path)
    for plan, meter in (("tiered-plan", "t_calls"), ("volume-plan", "v_gb")):
        (hint,) = hints(run_quote(data, "--plan", plan, "--meter", meter, "--quantity", "500"))
        assert hint != "top" and hint[1] == Decimal("0.05"), plan


def test_top_tier_says_so(tmp_path):
    data = make_data_dir(tmp_path)
    for plan, meter in (("tiered-plan", "t_calls"), ("volume-plan", "v_gb")):
        assert hints(run_quote(data, "--plan", plan, "--meter", meter, "--quantity", "5000")) == ["top"], plan
        assert "next tier: top tier" in run_quote(data, "--plan", plan, "--meter", meter, "--quantity", "5000")


def test_whole_plan_quote_has_one_hint_per_tiered_or_volume_component(tmp_path):
    out = run_quote(make_data_dir(tmp_path), "--plan", "mixed-plan", "--usage", "t_calls=50,plain=7,v_gb=5000")
    # components in plan order: the tiered one first (next tier 0.08), the volume one last (top tier)
    found = hints(out)
    assert len(found) == 2 and found[0] != "top" and found[0][1] == Decimal("0.08") and found[1] == "top"
    assert out.count("next tier:") == 2          # none for the flat and per_unit components
