"""C2 target: `python -m meterbill tenants list`, run against a copy of the tree with its own tenants.json."""
import json
import shutil
import subprocess
import sys
from pathlib import Path


def find_root():
    """The tree under test: the nearest parent holding both meterbill/__main__.py and data/."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "meterbill" / "__main__.py").exists() and (parent / "data").is_dir():
            return parent
    raise RuntimeError("tree root not found")


ROOT = find_root()


def run_tenants_list(tmp_path, tenants_doc=None):
    tree = tmp_path / "tree"
    tree.mkdir()
    shutil.copytree(ROOT / "meterbill", tree / "meterbill", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "data", tree / "data")
    if tenants_doc is not None:
        (tree / "data" / "tenants.json").write_text(json.dumps(tenants_doc))
    done = subprocess.run([sys.executable, "-m", "meterbill", "tenants", "list"], cwd=tree,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return [line.rstrip() for line in done.stdout.splitlines()]


def table(rows):
    """Reference formatting: two spaces between columns, each left-aligned to its widest value (header included)."""
    widths = [max(len(r[i]) for r in rows) for i in range(6)]
    return ["  ".join(r[i].ljust(widths[i]) for i in range(6)).rstrip() for r in rows]


HEADER = ("ID", "NAME", "COUNTRY", "PLAN", "CURRENCY", "TZ")


def test_seeded_tenants(tmp_path):
    expected = table([
        HEADER,
        ("ACM", "Acme Corp", "US", "starter", "USD", "America/New_York"),
        ("GLB", "Globex", "GB", "starter", "USD", "UTC"),
        ("NWD", "Northwind", "DE", "usage-eur", "EUR", "Europe/Berlin"),
        ("TKY", "Tokyo Freight", "JP", "enterprise-jpy", "USD", "UTC"),
        ("ZEN", "ZEN", "US", "starter", "USD", "UTC"),
    ])
    assert run_tenants_list(tmp_path) == expected


def test_fixture_defaults_and_sorting(tmp_path):
    tenants = {"tenants": [
        {"id": "zulu-tenant", "name": "Zulu Holdings International", "plan_id": "usage-eur", "country": "Germany",
         "billing_currency": "GBP", "tz": "Europe/London"},
        {"id": "alpha-tenant", "name": "Alpha Works", "plan_id": "enterprise-jpy", "country": "Japanese", "tz": "Asia/Tokyo"},
        {"id": "mike-tenant", "name": "Mike Manufacturing Company", "plan_id": "growth", "country": "Switzerland"},
        {"id": "bravo-tenant", "name": "Bravo Shipping Ltd", "plan_id": "volume", "country": "Australia", "billing_currency": "KWD"},
    ]}
    # every non-final column has a value wider than its header, so the header's own width does not matter
    expected = table([
        HEADER,
        ("alpha-tenant", "Alpha Works", "Japanese", "enterprise-jpy", "JPY", "Asia/Tokyo"),
        ("bravo-tenant", "Bravo Shipping Ltd", "Australia", "volume", "KWD", "UTC"),
        ("mike-tenant", "Mike Manufacturing Company", "Switzerland", "growth", "USD", "UTC"),
        ("zulu-tenant", "Zulu Holdings International", "Germany", "usage-eur", "GBP", "Europe/London"),
    ])
    assert run_tenants_list(tmp_path, tenants) == expected
