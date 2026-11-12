"""T3: duplicates and missing keys are handled by the ingest rules, not by the envelope format."""
import pytest

from t3_helpers import event, ingest, reject_reasons, stored_events, write_envelope


def _needs_envelopes(tmp_path):
    """Skip (not fail) while envelopes are not supported at all: the target tests cover that."""
    drop, data = tmp_path / "probe", tmp_path / "probe-data"
    write_envelope(drop, "probe", "probe", [event("ZEN", 99)])
    try:
        if ingest(drop, data) != {"ZEN": (1, 0, 0)}:
            pytest.skip("envelopes not supported yet")
    except AssertionError:
        pytest.skip("envelopes not supported yet")


def test_resent_envelope_with_new_batch_and_event_ids_adds_nothing(tmp_path):
    _needs_envelopes(tmp_path)
    drop, data = tmp_path / "drop", tmp_path / "data"
    first = [event("ZEN", n) for n in (1, 2, 3)]
    write_envelope(drop, "first", "batch-A", first)
    assert ingest(drop, data) == {"ZEN": (3, 0, 0)}
    # the same events sent again: fresh batch id and fresh event ids, same idempotency keys
    again = [{**e, "event_id": e["event_id"] + "-retry"} for e in first]
    write_envelope(drop, "second", "batch-B", again)
    assert ingest(drop, data) == {"ZEN": (0, 3, 0)}
    assert len(stored_events(data, "ZEN")) == 3


def test_event_without_idempotency_key_is_rejected_and_the_rest_accepted(tmp_path):
    _needs_envelopes(tmp_path)
    drop, data = tmp_path / "drop", tmp_path / "data"
    write_envelope(drop, "b1", "batch-1", [event("ZEN", 1), event("ZEN", 2, key=None), event("ZEN", 3)])
    assert ingest(drop, data) == {"ZEN": (2, 0, 1)}
    assert sorted(e["event_id"] for e in stored_events(data, "ZEN")) == ["ev-ZEN-1", "ev-ZEN-3"]
    assert reject_reasons(data) == ["missing idempotency_key"]


def test_duplicate_inside_one_envelope_is_counted_once(tmp_path):
    _needs_envelopes(tmp_path)
    drop, data = tmp_path / "drop", tmp_path / "data"
    twin = {**event("ZEN", 1), "event_id": "ev-ZEN-1-twin"}
    write_envelope(drop, "b1", "batch-1", [event("ZEN", 1), twin])
    assert ingest(drop, data) == {"ZEN": (1, 1, 0)}
