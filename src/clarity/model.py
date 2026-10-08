"""Data model. Plain dataclasses, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

STATUSES = ["idea", "planned", "active", "blocked", "done", "dropped"]
TYPES = ["feature", "fix", "improvement", "experiment", "chore"]

OPEN = {"idea", "planned", "active", "blocked"}
IN_FLIGHT = {"active", "blocked"}
FUTURE = {"idea", "planned"}
# Every closed state. There is no third: `dropped` is what `close --drop` sets. It was
# stored as `abandoned` while printing as DROPPED — two words for one state, until
# worklog version 2. An `archived` status existed for a while with nothing to reach
# it, which made the vocabulary bigger than the behaviour.
CLOSED = {"done", "dropped"}

# A folder on disk is required from `planned` onwards.
NEEDS_FOLDER = {"planned", "active", "blocked", "done", "dropped"}

def today() -> str:
    return date.today().isoformat()


def now() -> str:
    """Timestamp for a note. Dates are enough for created/started/ended — those are
    milestones — but a note's whole job is to say how current the record is, and
    "today" cannot tell a session that started an hour ago from one that ran all day.
    Seconds are dropped: this is read by a human, not diffed.
    """
    return datetime.now().replace(second=0, microsecond=0).isoformat(" ")

@dataclass
class Note:
    """`at` is an ISO datetime for notes written since timestamps landed, and a bare
    date for older ones. Both parse; readers must cope with either."""

    at: str
    text: str


@dataclass
class Item:
    """One unit of work: idea, feature, fix, experiment."""

    id: int
    name: str
    type: str = "feature"
    status: str = "idea"
    description: str | None = None
    outcome: str | None = None
    folder: str | None = None
    branch: str | None = None
    # The repos this epoch branched, relative to the root — copied from the project's
    # list at first start, so close and refresh act on what was actually branched
    # even if that list changes later. None means the root repo, as before.
    repos: list[str] | None = None
    # The branch each repo's epoch branch catches up with, keyed like `repos` ("."
    # for the root). Taken from the repo's checkout when the epoch first branches
    # it, so switching that checkout later for unrelated work changes nothing.
    bases: dict[str, str] | None = None
    blocked_reason: str | None = None
    evidence: str | None = None  # where adopt found it
    notes: list[Note] = field(default_factory=list)
    created: str = field(default_factory=today)
    started: str | None = None
    ended: str | None = None
    # The order things were finished in, which `ended` cannot hold: it is a date, so
    # two items closed on the same day are indistinguishable. Allocated on close, and
    # again on re-close after a reopen, so it always reflects the latest finish.
    closed_seq: int | None = None
    extra: dict = field(default_factory=dict)  # preserves hand-added keys

    KNOWN = (
        "id name type status description outcome folder branch repos bases blocked_reason "
        "evidence notes created started ended closed_seq"
    ).split()

    @classmethod
    def from_dict(cls, raw: dict) -> "Item":
        known = {k: raw.get(k) for k in cls.KNOWN if k in raw}
        notes = [Note(**n) for n in (known.pop("notes", None) or [])]
        extra = {k: v for k, v in raw.items() if k not in cls.KNOWN}
        item = cls(**known, notes=notes, extra=extra)
        return item

    def to_dict(self) -> dict:
        out: dict = {}
        for key in self.KNOWN:
            if key == "notes":
                continue
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.notes:
            out["notes"] = [{"at": n.at, "text": n.text} for n in self.notes]
        out.update(self.extra)
        return out

    @property
    def slug(self) -> str:
        keep = [c.lower() if c.isalnum() else "-" for c in self.name]
        slug = "".join(keep)
        while "--" in slug:
            slug = slug.replace("--", "-")
        return slug.strip("-")[:40] or f"item-{self.id}"

    @property
    def folder_name(self) -> str:
        return f"{self.id:03d}_{today()}__{self.slug}"


@dataclass
class Objectives:
    """What the project is for — one line, and the only objective there is.

    There used to be a second, `current`: what's being worked on now. It was a
    hand-kept copy of what "Active" already shows, and with several epochs in
    flight at once no single line could be true. An old worklog's `current` is
    read and dropped on the next write.
    """

    overall: str | None = None

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Objectives":
        raw = raw or {}
        return cls(overall=raw.get("overall"))

    def to_dict(self) -> dict:
        return {"overall": self.overall}


DEFAULT_CONFIG = {
    "version": 1,
    "project": {"name": None},
    "style": {
        "length": "concise",  # concise | balanced | verbose
        "format": "bullets",  # bullets | paragraphs | mixed
        "custom": "",
    },
    "behavior": {
        "read_on_demand": True,
        "ask_before": ["push", "delete", "install"],
        "commit_style": "conventional",
    },
    "hooks": {"enforce": "warn"},  # block | warn | off
    "summarizer": "none",
}
