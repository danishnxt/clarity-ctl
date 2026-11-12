"""Helpers for the T3 hidden tests: drop directories with envelope files, the ingest command, store readers."""
import contextlib
import io
import json
from pathlib import Path

from meterbill.cli import main


def event(tenant, n, key="auto", ts="2026-10-05T10:00:00+00:00"):
    record = {"tenant_id": tenant, "meter": "api_calls", "quantity": "5", "timestamp": ts, "event_id": f"ev-{tenant}-{n}"}
    if key == "auto":
        record["idempotency_key"] = f"key-{tenant}-{n}"
    elif key is not None:
        record["idempotency_key"] = key
    return record


def write_envelope(drop: Path, name, batch_id, events, device="dev-1"):
    drop.mkdir(exist_ok=True)
    path = drop / f"{name}.envelope.json"
    path.write_text(json.dumps({"batch_id": batch_id, "sent_at": "2026-10-06T08:00:00+00:00",
                                "device_id": device, "events": events}))
    return path


def ingest(drop, data, *flags):
    """Run `ingest` and return {tenant: (accepted, duplicate, rejected)} parsed from its table."""
    out, err = io.StringIO(), io.StringIO()
    argv = ["ingest", flags[0], str(drop), "--data-dir", str(data)] if flags else ["ingest", "--drop", str(drop), "--data-dir", str(data)]
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    assert code == 0, err.getvalue()
    counts = {}
    for line in out.getvalue().splitlines():
        parts = line.split()
        if len(parts) == 4 and all(p.isdigit() for p in parts[1:]):
            counts[parts[0]] = tuple(int(p) for p in parts[1:])
    return counts


def stored_events(data, tenant):
    files = sorted((Path(data) / "events" / tenant).glob("*.jsonl")) if (Path(data) / "events" / tenant).is_dir() else []
    return [json.loads(l) for f in files for l in f.read_text().splitlines() if l.strip()]


def reject_reasons(data):
    folder = Path(data) / "rejects"
    return [json.loads(l)["reason"] for f in sorted(folder.glob("*.jsonl")) for l in f.read_text().splitlines() if l.strip()] \
        if folder.is_dir() else []
