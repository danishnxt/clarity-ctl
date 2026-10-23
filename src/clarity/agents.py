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
block below is a constant instead, so there is nothing to regenerate and nothing
to go stale. The objective is not in it: `clarity-ctl status` prints that, live.

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

_BODY = """- If `.clarity/adopt.md` exists, adoption is unfinished: read it first and do
  what it says. It ends by telling you to delete it.
- `clarity-ctl status` — objective, what's active, what's next.
  `clarity-ctl --help` — every command.
- `clarity-ctl show active --json`, `clarity-ctl show <id> --json` — for you. Every read
  takes `--json` and answers `{ok, command, data, warnings, version}`.
- Exit codes: 0 ok · 1 error · 2 validation · 3 not a clarity project · 4 refused.
- Never hand-edit `worklog.yaml` or the generated block in `EPOCH.md` — both are
  rewritten from the commands. Below the marker in `EPOCH.md` is yours.
- Name ideas and epochs like a title, a few words: `clarity-ctl idea add "status
  crash on missing repo"`. The why, the evidence and the context go in a note
  right after — the first note is the detail. Folder and branch names come from
  the name.
- Start work with `clarity-ctl epoch start <id> --repo <repo|all|none> --brief "<goal and
  limits>"`; it takes an idea straight to active, and the brief is what whoever picks the
  epoch up reads first. Name the repos you will change; a project that lists repos asks.
  Then work in that epoch's folder: `clarity-ctl path <id>`.
- Every command that acts on an epoch takes its id, always: `clarity-ctl note 7
  "..."`. Clarity never infers which epoch you mean and will refuse without one.
- Claim before you work: `clarity-ctl claim <id> --as <your name>`; release with the same
  name when done: `clarity-ctl release <id> --as <your name>`.
- Running a swarm: start each agent's part with `clarity-ctl epoch start <id> --parent
  <swarm epoch id>`, the swarm epoch active. It cannot close while any member still runs.
- Stopping before the work is done: write a note starting `HANDOFF:` — what is finished,
  what is stuck, what the next agent should do first. `show <id>` reads the latest one.
- Write a note the moment a decision changes — a reversal, an approach you
  rejected, a result that surprised you: `clarity-ctl note <id> "..."`. Not when
  work completes; in a long session it never does, and the record is what the
  next session has instead of this conversation."""

# Written into a file inside the project. It sits next to the worklog, so it can
# say so plainly — hedging here would only teach an agent to doubt the repo it is
# already standing in.
LOCAL_BLOCK = f"""{START}
## clarity

This project's state lives in clarity. Query it — don't crawl the tree, and
don't write its files by hand.

{_BODY}
{END}"""

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

def block_for(path: Path | None = None) -> str:
    """What a given file gets. CLAUDE.md imports AGENTS.md instead of copying it."""
    if path is not None and path.name == "CLAUDE.md":
        return SHIM_BLOCK
    return LOCAL_BLOCK


def upsert(path: Path) -> str:
    """Put the block in `path`, preserving everything outside the markers.

    Returns created · updated · unchanged · skipped, so a caller can report
    honestly and a re-run of install is quiet rather than claiming work it did not do.
    """
    body = block_for(path)
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


def install(paths: list[Path], remove_instead: bool = False) -> list[tuple[Path, str]]:
    """Write (or strip) the block across `paths`, reporting what each one did."""
    if remove_instead:
        return [(path, remove(path)) for path in paths]
    return [(path, upsert(path)) for path in paths]


def refresh(paths: list[Path]) -> list[Path]:
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
        if start != -1 and end > start and upsert(path) == "updated":
            out.append(path)
    return out
