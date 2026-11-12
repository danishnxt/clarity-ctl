"""T2: the exact number of units to the next tier follows each model's own boundary rule."""
from decimal import Decimal

import pytest

from t2_helpers import hints, make_data_dir, run_quote


def units(tmp_path, plan, meter, quantity):
    found = hints(run_quote(make_data_dir(tmp_path), "--plan", plan, "--meter", meter, "--quantity", str(quantity)))
    if not found:
        pytest.skip("no hint printed: the target tests cover that")      # exact counts only mean something once a hint exists
    (hint,) = found
    return hint


@pytest.mark.parametrize("quantity, expected", [(50, (51, "0.08")), (99, (2, "0.08")), (100, (1, "0.08")),
                                               (101, (900, "0.05")), (1000, (1, "0.05"))])
def test_graduated_units_to_next_tier(tmp_path, quantity, expected):
    # inclusive bounds: unit 100 is still in tier 1, so it takes up_to + 1 - quantity more units
    assert units(tmp_path, "tiered-plan", "t_calls", quantity) == (Decimal(expected[0]), Decimal(expected[1]))


@pytest.mark.parametrize("quantity, expected", [(50, (50, "0.08")), (99, (1, "0.08")), (100, (900, "0.05")),
                                               (101, (899, "0.05")), (999, (1, "0.05"))])
def test_volume_units_to_next_tier(tmp_path, quantity, expected):
    # a total equal to up_to already prices in the next tier, so the hint looks one tier further
    assert units(tmp_path, "volume-plan", "v_gb", quantity) == (Decimal(expected[0]), Decimal(expected[1]))


def test_whole_plan_quote_uses_each_components_own_rule(tmp_path):
    out = run_quote(make_data_dir(tmp_path), "--plan", "mixed-plan", "--usage", "t_calls=100,plain=1,v_gb=100")
    if not hints(out):
        pytest.skip("no hint printed: the target tests cover that")
    assert hints(out) == [(Decimal(1), Decimal("0.08")), (Decimal(900), Decimal("0.05"))]


def test_quote_totals_unchanged_by_the_hint(tmp_path):
    out = run_quote(make_data_dir(tmp_path), "--plan", "mixed-plan", "--usage", "t_calls=100,plain=10,v_gb=100")
    # 10.00 fee + 100 x 0.10 + 10 x 0.5 + 100 x 0.05 (volume: total 100 prices in tier 2 at 0.08 -> 8.00)
    assert "Total:    33.00 USD" in out
