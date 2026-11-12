import itertools

import pytest

import t1_helpers

_counter = itertools.count(1)


@pytest.fixture(autouse=True)
def distinct_tenant_per_test():
    t1_helpers.set_tenant(f"TN{next(_counter):03d}")
