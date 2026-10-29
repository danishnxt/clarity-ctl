"""Telling other agents that this project uses clarity.

Every coding agent reads a markdown instructions file before it starts, and each
one reads a different file: Claude Code takes CLAUDE.md, Gemini takes GEMINI.md,
and most of the rest have settled on AGENTS.md. None of them are ours. A user's
CLAUDE.md is where they keep their own rules, and clarity has no business owning
that file.

So we write one marker-fenced block into it and leave every other byte alone:

    <!-- CLARITY:START -->
    ...
    <!-- CLARITY:END -->

Re-running finds the markers and swaps the body; nothing outside them is touched,
a byte-equal write reports `unchanged`, and `remove` takes the block back out.

There used to be a second file, .clarity/RULES.md, that this block pointed at.
It is gone. It was generated from config.yaml and the current objective, which
made it a cached copy of state that already lives in worklog.yaml — a second
place to keep in sync, and one that quietly fell behind its own generator. The
rules in the block are a constant instead. The block's state section, below, is
generated — but on every write, under the worklog lock, from nothing but the
worklog, so it has no way to fall behind (see "Why the state is in the block").

AGENTS.md carries the block. CLAUDE.md carries a one-line import of AGENTS.md
rather than a copy, so there is exactly one body of text to read or change. The
import is not optional — Claude Code does not read AGENTS.md on its own.

## Why the block is short, and why it stays short

It is loaded on every turn, by every agent, in every session — including
subagents, which inherit the instructions file but not whatever the main agent
chose to read. So it carries the rules that are expensive to get wrong and the
loop you actually run, and nothing else. Adding to it costs every turn of every
session.

That is why adopt gets one conditional line rather than its procedure. The
procedure is long and is read once; it lives in .clarity/adopt.md, which the
adopting agent deletes when it is done. After that the line costs a glance at a
path that isn't there.

## Why the state is in the block

It used to say "run `clarity-ctl status`" and stop there. Measured against a
CLAUDE.md the agent keeps by hand (bench/token-savings), that lost: the file is in
context before the first turn, while every clarity call is another turn, and every
turn re-reads the whole context. Clarity's record was as good — a CLAUDE.md written
from it scored best — it just cost more to get at.

So the block ends with `render.state_digest`: the objective, active epochs with
their handoffs, the queue, standing decisions and recent outcomes. It is bounded —
ten outcomes, twenty decisions, a line each — so it costs a large project no more
than a small one, and the rest stays a command away. It carries nothing that changes
without a command running (leases, git), which is what would make it go stale.

## Why the note rule names a moment, not a cadence

It used to say "as you go, not at the end". That describes a rhythm, and an
agent in a long session waits for a natural pause to obey it — which never
arrives, because the work keeps moving. The rule now names the trigger instead:
a decision changed. That is a thing an agent can notice happening, and it is
also exactly the content the next session cannot reconstruct from the code.

## Why there is no global install

There was one: the same block, written into ~/.claude/CLAUDE.md and the like, so
every project was covered. It went stale on every upgrade that renamed a
command, and nothing could refresh it — a write in one project has no business
editing files in the user's home. Where a project had both, the agent read two
blocks that disagreed. The project's own block is refreshed on every write, so
it is the only one.

## Why every write refreshes the block

An agent re-reads this file each session and remembers nothing else, so the
block is the whole of what it knows about clarity. After an upgrade it has to
say what the new binary does — `refresh` rewrites a block that differs and
leaves one that matches alone, so this costs a read on every write and a write
once per upgrade. It never adds a block: a file without one is the user's
choice, made with `install --remove` or by never installing.
"""

from __future__ import annotations

from pathlib import Path

from .store import write_atomic

START = "<!-- CLARITY:START -->"
END = "<!-- CLARITY:END -->"

_BODY = """- Where things stand is at the end of this block, current as of the last clarity
  write. Start from it; you don't need `status` or `--help` to get going.
  `clarity-ctl show <id>` has every note on an item.
- Start work: `clarity-ctl epoch start "<name, a few words>" --brief "<goal and limits>"
  --as <your name>`, or an idea's id in place of the name. One call: it branches, makes
  the worktree, claims the epoch for you and prints where to work.
- Commands that act on an epoch take its id, always: `clarity-ctl note 7 "..."`.
- Note the moment a decision changes — a reversal, an approach you rejected, a result
  that surprised you: `clarity-ctl note <id> "..."`. Not at the end: the notes are what
  the next session has instead of this conversation.
- A decision that outlives the epoch — a rule, a constraint, something we won't build
  and why: a note starting `DECISION:`. Every one is listed below for later sessions.
- The whole task done and merged: `clarity-ctl epoch close <id> "<outcome>"`, which
  also releases it. The outcome says what changed and why — for a bug, what was wrong.
  Rejected: `epoch close <id> --drop "<why>"`. An epoch left open reads as unfinished.
- Part of it left for later, even with the rest merged: don't close it. Keep it active
  and write a note starting `HANDOFF:` — what's done, what's left, what to do first.
  Not an idea: an idea reads as optional, a handoff as next.
- Later, not now: `clarity-ctl idea add "<name>"`.
- Never hand-edit `worklog.yaml` or the generated block in `EPOCH.md`.
- Every read takes `--json` and answers `{ok, command, data, warnings, version}`.
  Exit codes: 0 ok · 1 error · 2 validation · 3 not a clarity project · 4 refused.
- Splitting work across agents, taking over another agent's epoch, repos: `clarity-ctl
  --help`. If `.clarity/adopt.md` exists, adoption is unfinished: read it first."""

# Written into a file inside the project. It sits next to the worklog, so it can
# say so plainly — hedging here would only teach an agent to doubt the repo it is
# already standing in.
LOCAL_BLOCK = f"""{START}
## clarity

This project's state lives in clarity. Query it — don't crawl the tree, and
don't write its files by hand.

{_BODY}
{END}"""


def local_block(state: str | None = None) -> str:
    """LOCAL_BLOCK with the project's state digest at the end, inside the markers."""
    if not state:
        return LOCAL_BLOCK
    return LOCAL_BLOCK[:-len(END)] + f"\n{state}\n{END}"

# CLAUDE.md gets this instead of a copy. One body of text, imported rather than
# duplicated — two copies would be two things to keep in step, which is the whole
# problem this epoch removed.
SHIM_BLOCK = f"""{START}
## clarity

This project's agent instructions live in AGENTS.md.

@AGENTS.md
{END}"""

BLOCK = LOCAL_BLOCK  # what AGENTS.md and every file but CLAUDE.md gets


# Local targets, relative to the project root. `always` files are created if
# missing; the rest are only joined if the user already keeps one, so clarity
# never litters a repo with instructions files for agents nobody here runs.
LOCAL_TARGETS: list[tuple[str, bool]] = [
    ("AGENTS.md", True),    # the cross-agent convention — Codex, Cursor, Copilot, Zed, Aider
    ("CLAUDE.md", True),    # Claude Code does not read AGENTS.md by default
    ("GEMINI.md", False),
    ("QWEN.md", False),
    ("WARP.md", False),
    (".windsurfrules", False),
    (".github/copilot-instructions.md", False),
]

def block_for(path: Path | None = None, state: str | None = None) -> str:
    """What a given file gets. CLAUDE.md imports AGENTS.md instead of copying it."""
    if path is not None and path.name == "CLAUDE.md":
        return SHIM_BLOCK
    return local_block(state)


def upsert(path: Path, state: str | None = None) -> str:
    """Put the block in `path`, preserving everything outside the markers.

    Returns created · updated · unchanged · skipped, so a caller can report
    honestly and a re-run of install is quiet rather than claiming work it did not do.
    """
    body = block_for(path, state)
    if path.is_symlink():
        # Someone pointed this file somewhere deliberately. Writing would replace
        # their link with our file, so we don't — there is nothing here we own.
        return "skipped"

    if not path.exists():
        write_atomic(path, body + "\n")
        return "created"

    text = path.read_text(encoding="utf-8")
    start, end = text.find(START), text.find(END)

    if start != -1 and end > start:
        if text[start:end + len(END)] == body:
            return "unchanged"
        write_atomic(path, text[:start] + body + text[end + len(END):])
        return "updated"

    theirs = text.rstrip()
    joined = (theirs + "\n\n" if theirs else "") + body + "\n"
    write_atomic(path, joined)
    return "updated"


def remove(path: Path) -> str:
    """Take the block back out. Deletes the file if we were all that was in it."""
    if path.is_symlink() or not path.exists():
        return "absent"

    text = path.read_text(encoding="utf-8")
    start, end = text.find(START), text.find(END)
    if start == -1 or end <= start:
        return "absent"

    before = text[:start].rstrip()
    after = text[end + len(END):].lstrip()
    joined = before + ("\n\n" if before and after else "") + after

    if not joined.strip():
        path.unlink()
        return "removed"
    write_atomic(path, joined.rstrip() + "\n")
    return "removed"


def local_paths(root: Path) -> list[Path]:
    """Which files a repo-scoped install touches here, in report order."""
    return [root / name for name, always in LOCAL_TARGETS
            if always or (root / name).exists()]


def install(paths: list[Path], remove_instead: bool = False,
            state: str | None = None) -> list[tuple[Path, str]]:
    """Write (or strip) the block across `paths`, reporting what each one did."""
    if remove_instead:
        return [(path, remove(path)) for path in paths]
    return [(path, upsert(path, state)) for path in paths]


def refresh(paths: list[Path], state: str | None = None) -> list[Path]:
    """Bring existing blocks up to this version's text. Returns the files it rewrote.

    Only a file that already has a block is touched — this keeps a block current,
    it never adds one — and upsert leaves an identical block alone.
    """
    out = []
    for path in paths:
        if path.is_symlink() or not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        start, end = text.find(START), text.find(END)
        if start != -1 and end > start and upsert(path, state) == "updated":
            out.append(path)
    return out
