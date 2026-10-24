"""Reading and writing the two YAML files. Atomic, quoted, order-preserving."""

from __future__ import annotations

import fcntl
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import yaml

from .model import DEFAULT_CONFIG, STATUSES, Item, Objectives, id_key, parse_id, today

WORKLOG = "worklog.yaml"
ARCHIVE = "ARCHIVE"
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
            # `blocked` was an active epoch with a reason; the reason becomes a note
            elif item.get("status") == "blocked":
                item["status"] = "active"
            reason = item.pop("blocked_reason", None)
            if reason:
                item.setdefault("notes", []).append(
                    {"at": item.get("started") or today(), "text": f"was blocked: {reason}"})
    raw["version"] = WORKLOG_VERSION
    return raw


def load_archive(root: Path) -> list[tuple[Item, str]]:
    """Every item `archive` moved out of worklog.yaml, with the file it sits in.

    Read-only: nothing here is saved back, and a write to an archived item is refused.
    """
    folder = root / ARCHIVE
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.yaml")):
        for raw in load_yaml(path).get("items") or []:
            found.append((Item.from_dict(raw), path.name))
    return found


class Worklog:
    """objectives + the repos the project changes + every item, idea through closed.

    `repos` is empty for a project that is itself one repo — epochs branch the root.
    A workspace holding several checkouts lists the ones its epochs branch instead.
    `state_repo` marks a root that is a repo only to hold clarity's own files — adopt
    makes one when the root was not a repo — so epochs never branch it.

    `archived` maps id to (item, archive file name) for closed items moved out of
    worklog.yaml. They are read for `show` and for id allocation, never saved here.

    `newer` is set when the file was written by a newer clarity-ctl than this one.
    It still reads — what it knows it shows — but never saves: a write would put
    this version's idea of the file over one it does not fully understand.
    """

    OWN = ("version", "objectives", "repos", "state_repo", "items")

    def __init__(self, path: Path, objectives: Objectives, items: list[Item], extra: dict,
                 repos: list[str] | None = None, state_repo: bool = False,
                 newer: int | None = None, archived: dict | None = None):
        self.path = path
        self.objectives = objectives
        self.repos = repos or []
        self.state_repo = state_repo
        self.items = items
        self.extra = extra
        self.newer = newer
        self.archived = archived or {}

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
        # A live copy wins: a crash between writing an archive file and saving the
        # worklog leaves the item in both, and the worklog is the one that is current.
        live = {i.id for i in items}
        archived = {i.id: (i, name) for i, name in load_archive(path.parent)
                    if i.id not in live}
        return cls(path, Objectives.from_dict(raw.get("objectives")), items, extra,
                   repos=list(raw.get("repos") or []),
                   state_repo=bool(raw.get("state_repo")), newer=newer, archived=archived)

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

    def by_id(self, item_id: int | str) -> Item:
        """A live item, for a write. An archived one is refused, not returned: changing
        a copy that is never saved would lose the change without a word."""
        item_id = _norm(item_id)
        for item in self.items:
            if item.id == item_id:
                return item
        if item_id in self.archived:
            _, name = self.archived[item_id]
            raise ClarityError(
                f"epoch {item_id} is archived in {ARCHIVE}/{name} — archived epochs are "
                f"read-only; `show {item_id}` still reads them", code=4)
        raise ClarityError(f"no item with id {item_id}", code=4)

    def lookup(self, item_id: int | str) -> tuple[Item, str | None]:
        """A live or archived item, for a read. The second value is the archive file
        it sits in, or None when it is live."""
        item_id = _norm(item_id)
        for item in self.items:
            if item.id == item_id:
                return item, None
        if item_id in self.archived:
            item, name = self.archived[item_id]
            return item, name
        raise ClarityError(f"no item with id {item_id}", code=4)

    def all_items(self) -> list[Item]:
        """Live and archived together: ids and closing order are allocated over both."""
        return [*self.items, *(item for item, _ in self.archived.values())]

    def next_id(self) -> int:
        """The next top-level id. Subepochs are numbered under their parent instead."""
        return max((i.id for i in self.all_items() if isinstance(i.id, int)), default=0) + 1

    def next_sub_id(self, parent_id: int) -> str:
        """The next subepoch id under `parent_id`: 7.1, then 7.2 — archived ones count,
        so a number is never handed out twice."""
        taken = [id_key(i.id)[1] for i in self.all_items()
                 if i.parent == parent_id and isinstance(i.id, str)]
        return f"{parent_id}.{max(taken, default=0) + 1}"

    def with_status(self, statuses) -> list[Item]:
        return [i for i in self.items if i.status in statuses]


def _norm(item_id):
    """7, "7", 7.1 or "7.1" as the id it names; anything else as given, to be not found."""
    parsed = parse_id(item_id)
    return item_id if parsed is None else parsed


def write_archive(root: Path, items: list[Item]) -> list[tuple[str, int]]:
    """Append closed items to ARCHIVE/<month>.yaml, one file per month they ended in.

    Returns (file name, items added) for each file written. An item already in its
    file is not added twice, so re-running after a crash is safe.
    """
    by_month: dict[str, list[Item]] = {}
    for item in items:
        by_month.setdefault((item.ended or item.created)[:7], []).append(item)
    written = []
    for month, batch in sorted(by_month.items()):
        path = root / ARCHIVE / f"{month}.yaml"
        kept = load_yaml(path).get("items") or []
        have = {d.get("id") for d in kept}
        fresh = [i for i in batch if i.id not in have]
        kept += [i.to_dict() for i in fresh]
        write_atomic(path, _dump({"version": WORKLOG_VERSION, "items": kept}))
        written.append((path.name, len(fresh)))
    return written


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
