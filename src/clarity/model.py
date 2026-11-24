"""Data model. Plain dataclasses, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

STATUSES = ["idea", "active", "done", "dropped"]
TYPES = ["feature", "fix", "improvement", "experiment", "chore"]

OPEN = {"idea", "active"}
# There was a `blocked` too, for an epoch waiting on something. Nothing used it,
# and a note says the same without a status of its own.
IN_FLIGHT = {"active"}
FUTURE = {"idea"}
# Every closed state. There is no third: `dropped` is what `close --drop` sets. It was
# stored as `abandoned` while printing as DROPPED — two words for one state, until
# worklog version 2. An `archived` status existed for a while with nothing to reach
# it, which made the vocabulary bigger than the behaviour.
CLOSED = {"done", "dropped"}

# A folder on disk is required once an epoch starts, and not before or after in any
# way that matters: an idea has none, and an idea closed straight to done or dropped
# (`close` on an idea) never gets one. So a closed item may or may not have a
# folder, and nothing may assume it does. There used to be a `planned` status for a
# folder without a branch; `start --repo none` is that now, and an idea that was
# planned reads as an idea that keeps its folder.
NEEDS_FOLDER = {"active"}

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
    # The decisions this note is about, as stored ("D7"). Set only by `note --on`; never
    # read out of the text. The link never changes: what a retired decision resolves to
    # is looked up when the note is shown.
    decision: list[str] | None = None
    # Set only on a handoff: "live" until the next write on the item, then "taken", with
    # `taken_at` the moment of that write. Reading never changes it. See Item.take_handoff.
    handoff: str | None = None
    taken_at: str | None = None

    def to_dict(self) -> dict:
        out: dict = {"at": self.at, "text": self.text}
        if self.decision:
            out["decision"] = list(self.decision)
        if self.handoff:
            out["handoff"] = self.handoff
        if self.taken_at:
            out["taken_at"] = self.taken_at
        return out


# What a handoff used to be: a note starting with this. A handoff is a flag on a note now
# (`note --handoff`); the prefix survives only to refuse it and to migrate old notes.
HANDOFF = "HANDOFF:"
HANDOFF_LIVE = "live"
HANDOFF_TAKEN = "taken"


def handoff_prefix(text: str) -> bool:
    """Whether `text` starts the way a handoff note used to: HANDOFF:, any case."""
    return text.strip().upper().startswith(HANDOFF)
# What a decision used to be: a note starting with this. Decisions are records of their
# own now (see Decision); the prefix survives only to refuse it and to migrate old notes.
DECISION = "DECISION:"


def decision_prefix(text: str) -> bool:
    """Whether `text` starts the way a decision note used to: DECISION:, any case."""
    return text.strip().upper().startswith(DECISION)


def parse_decision_id(value) -> str | None:
    """A decision id as given — D7 or d7 — in its one stored form, "D7", or None."""
    text = str(value).strip()
    if len(text) > 1 and text[0] in "Dd" and text[1:].isdigit() and int(text[1:]) > 0:
        return f"D{int(text[1:])}"
    return None


def decision_key(decision_id: str) -> int:
    """The number of a stored decision id, to sort D9 before D10."""
    return int(decision_id[1:])


@dataclass
class Decision:
    """A rule, a constraint, something we won't build and why — a record of its own,
    not a note, so that a later one can retire it. Lives in worklog.yaml beside the
    items, never inside one: an archived epoch is read-only and a decision made in it
    can still be replaced.

    `replaces` names the decisions this one retired when it was recorded; `replaced_by`
    is the single decision that retired this one. Both directions are stored so either
    can be walked, and a decision has one successor, so the chains never loop.
    `retired` is {at, why} once it no longer stands, with or without a successor.
    """

    id: str  # "D7"
    epoch: int | str  # the item it was made in — provenance only
    text: str
    at: str
    replaces: list[str] = field(default_factory=list)
    replaced_by: str | None = None
    retired: dict | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Decision":
        epoch = parse_id(raw.get("epoch"))
        return cls(id=str(raw.get("id")), epoch=raw.get("epoch") if epoch is None else epoch,
                   text=str(raw.get("text") or ""), at=str(raw.get("at") or ""),
                   replaces=list(raw.get("replaces") or []),
                   replaced_by=raw.get("replaced_by"), retired=raw.get("retired") or None)

    def to_dict(self) -> dict:
        return {"id": self.id, "epoch": self.epoch, "text": self.text, "at": self.at,
                "replaces": list(self.replaces), "replaced_by": self.replaced_by,
                "retired": self.retired}

    @property
    def standing(self) -> bool:
        return self.retired is None


def decision_end(decisions: dict[str, Decision], decision_id: str) -> str:
    """Where `decision_id` stands now: itself if it stands, else its successor, and
    that one's successor — the last decision of the chain. A retired decision with no
    successor is its own end."""
    seen = {decision_id}
    current = decision_id
    while True:
        nxt = decisions[current].replaced_by if current in decisions else None
        if not nxt or nxt in seen or nxt not in decisions:
            return current
        seen.add(nxt)
        current = nxt


def decision_tag(decisions: dict[str, Decision], decision_id: str) -> str:
    """How a note's link to a decision reads: `D7` while it stands, `D7 → D12` once
    replaced, with `retired` after whichever one the chain ends on if that is closed
    without a replacement."""
    end = decision_end(decisions, decision_id)
    stands = end in decisions and decisions[end].standing
    mark = "" if stands else " retired"
    return f"{decision_id}{mark}" if end == decision_id else f"{decision_id} → {end}{mark}"


def parse_id(value) -> int | str | None:
    """An id as given — 7, or "7.1" for a subepoch — in its one stored form, or None.

    A top-level id is an int. A subepoch's is "<parent>.<n>", counted per parent, so
    it reads as part of its parent and uses up none of the top-level numbers. YAML
    reads an unquoted 7.1 as a float; str() brings that back too.
    """
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    head, dot, tail = text.partition(".")
    if dot and head.isdigit() and tail.isdigit() and int(tail) > 0:
        return f"{int(head)}.{int(tail)}"
    return None


def id_key(item_id: int | str) -> tuple[int, int]:
    """Sorts 7 before 7.1 before 7.2 before 8 — never 7.10 before 7.2."""
    head, _, tail = str(item_id).partition(".")
    return int(head), int(tail or 0)


# Folder and branch names come from the item's name. Short enough to read in a
# listing; an item named like a title fits whole.
SLUG_MAX = 30


@dataclass
class Item:
    """One unit of work: idea, feature, fix, experiment."""

    id: int | str  # 7, or "7.1" for a subepoch — see parse_id
    name: str
    type: str = "feature"
    status: str = "idea"
    description: str | None = None
    # What the work is for and what limits apply, written once at start. Read first by
    # whoever picks the epoch up, including a replacement agent after a kill.
    brief: str | None = None
    outcome: str | None = None
    folder: str | None = None
    branch: str | None = None
    # The repos this epoch branched, relative to the root — copied from the project's
    # list at first start, so close and refresh act on what was actually branched
    # even if that list changes later. None means the root repo, as before.
    repos: list[str] | None = None
    # The epoch this one was spawned under, as a subepoch of it: the head of its id.
    # None for a top-level epoch. One level only: a subepoch cannot have its own.
    parent: int | None = None
    # The branch each repo's epoch branch catches up with, keyed like `repos` ("."
    # for the root). Taken from the repo's checkout when the epoch first branches
    # it, so switching that checkout later for unrelated work changes nothing.
    bases: dict[str, str] | None = None
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
        "id name type status description brief outcome folder branch repos parent bases "
        "evidence notes created started ended closed_seq"
    ).split()

    @classmethod
    def from_dict(cls, raw: dict) -> "Item":
        known = {k: raw.get(k) for k in cls.KNOWN if k in raw}
        notes = [Note(**n) for n in (known.pop("notes", None) or [])]
        extra = {k: v for k, v in raw.items() if k not in cls.KNOWN}
        if parse_id(known.get("id")) is not None:
            known["id"] = parse_id(known["id"])
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
            out["notes"] = [n.to_dict() for n in self.notes]
        out.update(self.extra)
        return out

    @property
    def never_started(self) -> bool:
        """Closed (or still an idea) without work ever beginning: `close` on an
        idea. No start date and no branch, so no repo work was done. render.item_text
        reads the same two fields off the item's dict."""
        return self.started is None and self.branch is None

    @property
    def live_handoff(self) -> Note | None:
        """The note holding this item's handoff while it is still live — written and not
        yet taken up. At most one: writing a new handoff takes the one before."""
        for note in reversed(self.notes):
            if note.handoff == HANDOFF_LIVE:
                return note
        return None

    @property
    def handoff(self) -> str | None:
        """The live handoff's text: what is finished, what is stuck, what the next
        session should do first. None once the next session has taken it up."""
        note = self.live_handoff
        return note.text if note else None

    def take_handoff(self, at: str) -> None:
        """Mark the live handoff taken up as of `at`. Called by every write on the item
        that is the next session's work — a note, a decision, a close — never by a read."""
        note = self.live_handoff
        if note:
            note.handoff, note.taken_at = HANDOFF_TAKEN, at

    @property
    def slug(self) -> str:
        keep = [c.lower() if c.isalnum() else "-" for c in self.name]
        slug = "".join(keep)
        while "--" in slug:
            slug = slug.replace("--", "-")
        slug = slug.strip("-")
        if len(slug) > SLUG_MAX:
            # at a word boundary: a word cut in half reads as a typo in every path
            cut = slug[:SLUG_MAX + 1]
            slug = cut[:cut.rindex("-")] if "-" in cut else slug[:SLUG_MAX]
        return slug or f"item-{self.id}"

    @property
    def code(self) -> str:
        """The id as folder and branch names carry it: 007, or 007.1 for a subepoch."""
        head, _ = id_key(self.id)
        return f"{head:03d}" if isinstance(self.id, int) else f"{head:03d}.{id_key(self.id)[1]}"

    @property
    def folder_name(self) -> str:
        return f"{self.code}_{today()}__{self.slug}"


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
