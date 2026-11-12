"""C1 target: `python -m meterbill plans list`, run against a copy of the tree with its own plans.json."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest



def find_root():
    """The tree under test: the nearest parent holding both meterbill/__main__.py and data/."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "meterbill" / "__main__.py").exists() and (parent / "data").is_dir():
            return parent
    raise RuntimeError("tree root not found")


ROOT = find_root()


def run_plans_list(tmp_path, plans_doc=None):
    """Copy the package and data/ into tmp_path (optionally replacing plans.json), run the command there."""
    tree = tmp_path / "tree"
    tree.mkdir()
    shutil.copytree(ROOT / "meterbill", tree / "meterbill", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "data", tree / "data")
    if plans_doc is not None:
        (tree / "data" / "plans.json").write_text(json.dumps(plans_doc))
        (tree / "data" / "tenants.json").write_text(json.dumps({"tenants": []}))
    done = subprocess.run([sys.executable, "-m", "meterbill", "plans", "list"], cwd=tree,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return [line.rstrip() for line in done.stdout.splitlines()]


def table(rows):
    """Reference formatting: two spaces between columns, each left-aligned to its widest value."""
    widths = [max(len(r[i]) for r in rows) for i in range(4)]
    return ["  ".join(r[i].ljust(widths[i]) for i in range(4)).rstrip() for r in rows]


def test_seeded_plans(tmp_path):
    expected = table([
        ("ID", "NAME", "MODEL", "CURRENCY"),
        ("enterprise-jpy", "Enterprise (JPY)", "mixed", "JPY"),
        ("growth", "Growth (tiered)", "mixed", "USD"),
        ("starter", "Starter", "mixed", "USD"),
        ("usage-eur", "Usage (EUR)", "per_unit", "EUR"),
    ])
    assert run_plans_list(tmp_path) == expected


def flat(meter):
    return {"meter": meter, "model": "flat", "fee": "10.00"}


def per_unit(meter):
    return {"meter": meter, "model": "per_unit", "unit_price": "0.5"}


def tiered(meter):
    return {"meter": meter, "model": "tiered", "tiers": [{"up_to": 100, "unit_price": "1"}, {"up_to": None, "unit_price": "0.5"}]}


def test_fixture_with_mixed_plans_sorted_by_id(tmp_path):
    plans = {"plans": [
        {"id": "zeta-metered", "name": "Zeta Metered Plan", "currency": "EUR", "components": [per_unit("a"), per_unit("b")]},
        {"id": "alpha-tiers", "name": "Alpha Tiers", "currency": "GBP", "components": [tiered("a")]},
        {"id": "mid-flat-and-usage", "name": "Mid", "currency": "USD", "components": [flat("fee"), per_unit("a")]},
        {"id": "beta-mix-three", "name": "Beta Everything Plan", "currency": "JPY", "components": [flat("f"), per_unit("a"), tiered("b")]},
        {"id": "gamma-flat-fees", "name": "Gamma", "currency": "KWD", "components": [flat("f1"), flat("f2")]},
    ]}
    expected = table([
        ("ID", "NAME", "MODEL", "CURRENCY"),
        ("alpha-tiers", "Alpha Tiers", "tiered", "GBP"),
        ("beta-mix-three", "Beta Everything Plan", "mixed", "JPY"),
        ("gamma-flat-fees", "Gamma", "flat", "KWD"),
        ("mid-flat-and-usage", "Mid", "mixed", "USD"),
        ("zeta-metered", "Zeta Metered Plan", "per_unit", "EUR"),
    ])
    # every non-final column here has a value wider than its header, so the header's own width does not matter
    assert run_plans_list(tmp_path, plans) == expected
