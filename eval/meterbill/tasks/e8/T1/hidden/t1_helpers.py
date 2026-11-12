"""Shared helpers for the T1 hidden tests: a throwaway data dir and event/invoice builders."""
import builtins
import io
import json
import os
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal

from meterbill.events import UsageEvent
from meterbill.period import Period
from meterbill.plans import load_catalog

_state = {"tenant": "T1"}


def tenant():
    """The tenant id of the running test; a different one per test, so no state shared through
    a module-level structure in the code under test can couple two tests."""
    return _state["tenant"]


def set_tenant(value):
    _state["tenant"] = value


TAX_FILES = ("tax_rates.json", "tax_overrides.json")
PERIOD = Period.parse("2026-10")
ISSUE = date(2026, 10, 31)


def overrides_for(country, rate, reason="r"):
    return {tenant(): {country: {"rate": rate, "reason": reason}}}


def write_json(path, doc):
    path.write_text(json.dumps(doc), encoding="utf-8")


def make_data_dir(tmp_path, meters, rates, overrides, country="DE", unit_price="0.013"):
    """plans/tenants/tax files for one tenant the test's tenant on a per-unit EUR plan with the given meters."""
    data = tmp_path / "data"
    data.mkdir()
    write_json(data / "plans.json", {"plans": [{
        "id": "p", "name": "P", "currency": "EUR",
        "components": [{"meter": m, "model": "per_unit", "unit_price": unit_price} for m in meters],
    }]})
    write_json(data / "tenants.json", {"tenants": [{"id": tenant(), "name": "T One", "plan_id": "p", "country": country}]})
    write_json(data / "tax_rates.json", rates)
    write_json(data / "tax_overrides.json", overrides)
    return data


def event(meter, country, qty="10", n=0):
    return UsageEvent(
        tenant_id=tenant(), meter=meter, quantity=Decimal(qty),
        timestamp=datetime(2026, 10, 5, 12, tzinfo=UTC),
        event_id=f"{meter}-{country}-{n}", idempotency_key=f"{meter}-{country}-{n}",
        properties={"country": country} if country else {},
    )


def build(data, events):
    from meterbill.invoices import build_invoice
    from meterbill.tax import TaxResolver

    return build_invoice(tenant(), PERIOD, events, load_catalog(data), ISSUE, TaxResolver(data))


def rewrite_same_timestamp(path, doc):
    """Replace the file's content and give it back its old modification time."""
    before = path.stat()
    write_json(path, doc)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = path.stat()
    assert after.st_mtime_ns == before.st_mtime_ns


@contextmanager
def count_tax_file_reads(monkeypatch):
    """Counts how many times each tax JSON file is opened, however the code opens it."""
    counts = Counter()
    real_open = io.open

    def counting_open(file, *args, **kwargs):
        if isinstance(file, (str, os.PathLike)) and os.path.basename(os.fspath(file)) in TAX_FILES:
            counts[os.path.basename(os.fspath(file))] += 1
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)
    monkeypatch.setattr(io, "open", counting_open)
    yield counts
