"""Helpers for the T2 hidden tests: a throwaway data dir and the quote command run in process."""
import contextlib
import io
import json
import re
from decimal import Decimal

from meterbill.cli import main

TIERS = [{"up_to": 100, "unit_price": "0.10"}, {"up_to": 1000, "unit_price": "0.08"}, {"up_to": None, "unit_price": "0.05"}]
HINT = re.compile(r"next tier:\s*(?:\+(\d+(?:\.\d+)?)\s+units?\s+at\s+(\d+(?:\.\d+)?)|(top tier))")


def make_data_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    plans = [
        {"id": "tiered-plan", "name": "Tiered Plan", "currency": "USD",
         "components": [{"meter": "t_calls", "model": "tiered", "tiers": TIERS}]},
        {"id": "volume-plan", "name": "Volume Plan", "currency": "USD",
         "components": [{"meter": "v_gb", "model": "volume", "tiers": TIERS}]},
        {"id": "mixed-plan", "name": "Mixed Plan", "currency": "USD",
         "components": [{"meter": "fee", "model": "flat", "fee": "10.00"},
                        {"meter": "t_calls", "model": "tiered", "tiers": TIERS},
                        {"meter": "plain", "model": "per_unit", "unit_price": "0.5"},
                        {"meter": "v_gb", "model": "volume", "tiers": TIERS}]},
    ]
    (data / "plans.json").write_text(json.dumps({"plans": plans}))
    (data / "tenants.json").write_text(json.dumps({"tenants": []}))
    (data / "tax_rates.json").write_text("{}")
    (data / "tax_overrides.json").write_text("{}")
    return data


def run_quote(data, *args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["quote", "--data-dir", str(data), *args])
    assert code == 0, err.getvalue()
    return out.getvalue()


def hints(text):
    """(units, price) per hint line in order of appearance, or the string 'top' for a top-tier hint."""
    found = []
    for line in text.splitlines():
        m = HINT.search(line)
        if m:
            found.append("top" if m.group(3) else (Decimal(m.group(1)), Decimal(m.group(2))))
    return found
