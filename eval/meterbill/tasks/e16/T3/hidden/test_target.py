"""T3 target: batch envelope files are accepted by ingest and by ingest --check."""
from t3_helpers import event, ingest, stored_events, write_envelope


def test_envelope_is_ingested_into_the_store(tmp_path):
    drop, data = tmp_path / "drop", tmp_path / "data"
    write_envelope(drop, "b1", "batch-1", [event("ZEN", 1), event("ZEN", 2), event("ACM", 1)])
    counts = ingest(drop, data)
    assert counts == {"ZEN": (2, 0, 0), "ACM": (1, 0, 0)}
    assert sorted(e["event_id"] for e in stored_events(data, "ZEN")) == ["ev-ZEN-1", "ev-ZEN-2"]
    assert [e["event_id"] for e in stored_events(data, "ACM")] == ["ev-ACM-1"]


def test_envelope_next_to_a_jsonl_file(tmp_path):
    import json
    drop, data = tmp_path / "drop", tmp_path / "data"
    write_envelope(drop, "b1", "batch-1", [event("ZEN", 1), event("ZEN", 2)])
    (drop / "plain.jsonl").write_text(json.dumps(event("ZEN", 3)) + "\n")
    assert ingest(drop, data) == {"ZEN": (3, 0, 0)}
    assert len(stored_events(data, "ZEN")) == 3


def test_check_counts_an_envelope_and_writes_nothing(tmp_path):
    drop, data = tmp_path / "drop", tmp_path / "data"
    path = write_envelope(drop, "b1", "batch-1", [event("ZEN", 1), event("ZEN", 2)])
    assert ingest(drop, data, "--check") == {"ZEN": (2, 0, 0)}
    assert path.exists() and not (data / "events").exists()
