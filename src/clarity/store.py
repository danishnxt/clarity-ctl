"""Reading and writing the two YAML files. Atomic, quoted, order-preserving."""

from __future__ import annotations

import fcntl
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import yaml

from .model import DEFAULT_CONFIG, STATUSES, Item, Objectives

WORKLOG = "worklog.yaml"
CONFIG_DIR = ".clarity"
CONFIG = "config.yaml"


class ClarityError(Exception):
    """Refused or invalid — carries the exit code the CLI should use.

    For a new error, pick by what the caller should do next:
      2  the input is wrong — a bad id, type, view or missing text. Fix the command.
      4  the input is fine but the project's state says no — already closed, lease
         held, newer worklog. Look at `status` before retrying.
      3  not a clarity project. 1 only for what fits neither.
    Older errors still use 4 for some input mistakes; they are left as they are.
    """

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def _dump(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def write_atomic(path: Path, text: str) -> None:
    """Write via temp file + rename, so an interrupted write can't truncate state."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_if_changed(path: Path, text: str) -> bool:
    """write_atomic, but only when the bytes would differ. True if it wrote.

    Rendering costs ~1us and the atomic write ~130us, so comparing first is most of
    the saving. It also stops a no-op rewrite from bumping mtime, which is what keeps
    `git status` quiet and makes watching mtimes viable.
    """
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == text:
                return False
        except (OSError, UnicodeDecodeError):
            pass  # unreadable — rewrite it
    write_atomic(path, text)
    return True


@contextmanager
def file_lock(path: Path, timeout: float = 10.0):
    """Exclusive lock held across a read-modify-write, so two writers can't lose an update.

    Advisory (flock), which is enough: every writer is a clarity process and takes it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    started = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() - started > timeout:
                    raise ClarityError(
                        "another clarity process is writing (lock timed out)", code=4
                    )
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ClarityError(f"{path.name}: expected a mapping at the top level", code=2)
    return data


# The shape of worklog.yaml this code reads and writes. Bump it when an older
# clarity-ctl would misread the file — a renamed field or status, not an added
# field, which older code already carries through untouched in `extra`.
WORKLOG_VERSION = 2


def _migrate(raw: dict) -> dict:
    """An older worklog, brought up to WORKLOG_VERSION in memory. Saved on the next write.

    One step per version, in order, so a worklog several versions behind takes
    every step it missed. No version at all is version 1: it was always written.
    """
    version = raw.get("version") or 1
    if version < 2:
        for item in raw.get("items") or []:
            # `abandoned` printed as DROPPED everywhere; the stored word now matches
            if item.get("status") == "abandoned":
                item["status"] = "dropped"
            # `planned` was a folder without a branch. Its folder stays; starting
            # the idea picks it back up.
            elif item.get("status") == "planned":
                item["status"] = "idea"
    raw["version"] = WORKLOG_VERSION
    return raw


class Worklog:
    """objectives + the repos the project changes + every item, idea through closed.

    `repos` is empty for a project that is itself one repo — epochs branch the root.
    A workspace holding several checkouts lists the ones its epochs branch instead.
    `state_repo` marks a root that is a repo only to hold clarity's own files — adopt
    makes one when the root was not a repo — so epochs never branch it.

    `newer` is set when the file was written by a newer clarity-ctl than this one.
    It still reads — what it knows it shows — but never saves: a write would put
    this version's idea of the file over one it does not fully understand.
    """

    OWN = ("version", "objectives", "repos", "state_repo", "items")

    def __init__(self, path: Path, objectives: Objectives, items: list[Item], extra: dict,
                 repos: list[str] | None = None, state_repo: bool = False,
                 newer: int | None = None):
        self.path = path
        self.objectives = objectives
        self.repos = repos or []
        self.state_repo = state_repo
        self.items = items
        self.extra = extra
        self.newer = newer

    @classmethod
    def load(cls, path: Path) -> "Worklog":
        raw = load_yaml(path)
        version = raw.get("version") or 1
        if not isinstance(version, int):
            raise ClarityError(f"{path.name}: version {version!r} is not a number", code=2)
        newer = version if version > WORKLOG_VERSION else None
        if not newer:
            raw = _migrate(raw)
        items = [Item.from_dict(d) for d in (raw.get("items") or [])]
        if not newer:
            # A status this code does not know would match no view and the item
            # would vanish from every listing — say so instead.
            for item in items:
                if item.status not in STATUSES:
                    raise ClarityError(
                        f"{path.name}: item {item.id} has status {item.status!r}; "
                        f"known: {', '.join(STATUSES)}", code=2)
        extra = {k: v for k, v in raw.items() if k not in cls.OWN}
        return cls(path, Objectives.from_dict(raw.get("objectives")), items, extra,
                   repos=list(raw.get("repos") or []),
                   state_repo=bool(raw.get("state_repo")), newer=newer)

    @classmethod
    def empty(cls, path: Path) -> "Worklog":
        return cls(path, Objectives(), [], {})

    def newer_warning(self) -> str | None:
        if not self.newer:
            return None
        return (f"{self.path.name} is version {self.newer}, from a newer clarity-ctl than "
                f"this one (reads up to {WORKLOG_VERSION}) — showing what it can, "
                f"refusing writes; upgrade clarity-ctl")

    def save(self) -> None:
        if self.newer:
            raise ClarityError(self.newer_warning(), code=4)
        data = {"version": WORKLOG_VERSION, "objectives": self.objectives.to_dict()}
        if self.repos:
            # absent rather than `repos: []`, so a single-repo worklog reads as it did
            data["repos"] = list(self.repos)
        if self.state_repo:
            data["state_repo"] = True
        data["items"] = [i.to_dict() for i in self.items]
        data.update(self.extra)
        write_atomic(self.path, _dump(data))

    def by_id(self, item_id: int) -> Item:
        for item in self.items:
            if item.id == item_id:
                return item
        raise ClarityError(f"no item with id {item_id}", code=4)

    def next_id(self) -> int:
        return max((i.id for i in self.items), default=0) + 1

    def with_status(self, statuses) -> list[Item]:
        return [i for i in self.items if i.status in statuses]


def load_config(root: Path) -> dict:
    """Project config, with defaults filled in for anything absent."""
    raw = load_yaml(root / CONFIG_DIR / CONFIG)
    config = {**DEFAULT_CONFIG}
    for key, value in raw.items():
        if isinstance(value, dict) and isinstance(config.get(key), dict):
            config[key] = {**config[key], **value}
        else:
            config[key] = value
    return config


def save_config(root: Path, config: dict) -> None:
    write_atomic(root / CONFIG_DIR / CONFIG, _dump(config))
