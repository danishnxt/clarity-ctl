"""Leases: who is working an epoch.

A lease is one file per epoch (`EPOCHS/NNN_.../.lease`), claimed with O_EXCL so two
processes racing for the same epoch cannot both create it.

It is a warning, not a lock. Clarity has no way to stop a second agent editing the
worktree — git and the filesystem take writes from anyone — so it does not pretend
to. A lease says "someone is on this, here is who and since when", refuses a second
claim, and offers `--steal`. The repo belongs to whoever is running clarity; if they
decide to take it, that is their call to make, not ours to prevent.

Deliberately absent: expiry and process checks. Both were attempts to guess whether
the holder was still alive, and both guessed wrong — a pid recorded by a one-shot CLI
is dead the moment the command exits, which quietly made every lease takeable. Now
nothing expires on its own. A stale lease waits for a person, the way terraform's
state lock waits for `force-unlock`.

Machine-local state — gitignored, never part of the worklog.
"""

from __future__ import annotations

import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .store import ClarityError

LEASE = ".lease"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def whoami(name: str | None = None) -> dict:
    """Identity of this holder. `name` (claim --as) wins, then CLARITY_AGENT, so an
    agent can name itself per command or once per shell.

    A self-declared string, like a kubernetes lease's holderIdentity — never a pid.
    """
    return {
        "owner": name or os.environ.get("CLARITY_AGENT") or os.environ.get("USER") or "unknown",
        "host": socket.gethostname(),
    }


def path_for(folder: Path) -> Path:
    return folder / LEASE


def read(folder: Path) -> dict | None:
    path = path_for(folder)
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def held_by_us(lease: dict, name: str | None = None) -> bool:
    me = whoami(name)
    return lease.get("owner") == me["owner"] and lease.get("host") == me["host"]


def age(lease: dict) -> str | None:
    """How long ago it was claimed, for the human deciding whether to steal it."""
    try:
        since = _now() - datetime.fromisoformat(lease["at"])
    except (KeyError, TypeError, ValueError):
        return None
    minutes = int(since.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    return f"{hours}h ago" if hours < 24 else f"{hours // 24}d ago"


def describe(lease: dict) -> str:
    who = f"{lease.get('owner', '?')}@{lease.get('host', '?')}"
    when = age(lease)
    return f"{who}, claimed {when}" if when else who


def claim(folder: Path, steal: bool = False, label: str | None = None,
          name: str | None = None) -> dict:
    """Take the lease. Refuses if anyone else holds it, unless stealing."""
    folder.mkdir(parents=True, exist_ok=True)
    lease = {**whoami(name), "at": _stamp(_now())}
    if label:
        lease["label"] = label

    path = path_for(folder)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        current = read(folder)
        if current and not held_by_us(current, name) and not steal:
            raise ClarityError(
                f"epoch is leased by {describe(current)}\n"
                "  check whether that agent is still working before you take it\n"
                "  then: clarity-ctl claim <id> --steal",
                code=4,
            )
        if current and steal and not held_by_us(current, name):
            lease["stolen_from"] = describe(current)
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o644)

    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        yaml.safe_dump(lease, fh, sort_keys=False)
    return lease


def release(folder: Path, force: bool = False, name: str | None = None) -> bool:
    current = read(folder)
    if current is None:
        return False
    if not force and not held_by_us(current, name):
        raise ClarityError(f"lease belongs to {describe(current)} — use --force", code=4)
    path_for(folder).unlink(missing_ok=True)
    return True
