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

## Why the wording is conditional

A global install writes this into ~/.claude/CLAUDE.md, which loads in every
project the user ever opens — nearly all of which have no worklog.yaml. An
unconditional "state lives in clarity" would send agents into failing commands
in projects that never adopted it. The block therefore states its own
precondition and tells the reader to ignore it when it does not hold.
"""

from __future__ import annotations

from pathlib import Path

from .store import write_atomic

START = "<!-- CLARITY:START -->"
END = "<!-- CLARITY:END -->"

_BODY = """- If `.clarity/adopt.md` exists, adoption is unfinished: read it first and do
  what it says. It ends by telling you to delete it.
- `clarity-ctl status` — objective, what's in flight, what's next.
  `clarity-ctl --help` — every command.
- `clarity-ctl show active --json`, `clarity-ctl show <id> --json` — for you. Every read
  takes `--json` and answers `{ok, command, data, warnings, version}`.
- Exit codes: 0 ok · 1 error · 2 validation · 3 not a clarity project · 4 refused.
- Never hand-edit `worklog.yaml` or the generated block in `EPOCH.md` — both are
  rewritten from the commands. Below the marker in `EPOCH.md` is yours.
- Start work with `clarity-ctl epoch start <id>`; it takes an idea straight to active.
  Then work in that epoch's folder: `clarity-ctl path <id>`.
- Every command that acts on an epoch takes its id, always: `clarity-ctl note 7
  "..."`. Clarity never infers which epoch you mean and will refuse without one.
- Claim before you work: `clarity-ctl claim <id>`, `clarity-ctl release <id>` when done.
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

# Written into the user's own files, which load in every project they open —
# nearly all of which have no worklog.yaml. Hence the precondition: without it,
# this block would send agents into failing commands everywhere else.
GLOBAL_BLOCK = f"""{START}
## clarity

In a project with a `worklog.yaml` at its root, state lives in clarity. Query it
— don't crawl the tree, and don't write its files by hand.

{_BODY}

No `worklog.yaml` at the root means the project does not use clarity — ignore
this section entirely there.
{END}"""

# CLAUDE.md gets this instead of a copy. One body of text, imported rather than
# duplicated — two copies would be two things to keep in step, which is the whole
# problem this epoch removed.
SHIM_BLOCK = f"""{START}
## clarity

This project's agent instructions live in AGENTS.md.

@AGENTS.md
{END}"""

BLOCK = LOCAL_BLOCK  # the common case, and what callers without a scope mean


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

# Global targets, relative to the user's home. Each is written only when its
# parent directory already exists — that a user has ~/.codex is the signal that
# they run Codex, and it is the only detection worth doing here.
GLOBAL_TARGETS: list[str] = [
    ".claude/CLAUDE.md",
    ".codex/AGENTS.md",
    ".gemini/GEMINI.md",
    ".qwen/QWEN.md",
    ".config/opencode/AGENTS.md",
    ".github/copilot-instructions.md",
]


def block_for(scope: str = "local", path: Path | None = None) -> str:
    """What a given file gets. Locally, CLAUDE.md imports AGENTS.md instead of copying it."""
    if scope == "global":
        return GLOBAL_BLOCK
    if path is not None and path.name == "CLAUDE.md":
        return SHIM_BLOCK
    return LOCAL_BLOCK


def upsert(path: Path, scope: str = "local") -> str:
    """Put the block in `path`, preserving everything outside the markers.

    Returns created · updated · unchanged · skipped, so a caller can report
    honestly and a re-run of install is quiet rather than claiming work it did not do.
    """
    body = block_for(scope, path)
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


def global_paths(home: Path | None = None) -> list[Path]:
    """Which files a machine-scoped install touches, for agents this user runs."""
    home = home or Path.home()
    return [home / name for name in GLOBAL_TARGETS if (home / name).parent.is_dir()]


def install(paths: list[Path], remove_instead: bool = False,
            scope: str = "local") -> list[tuple[Path, str]]:
    """Write (or strip) the block across `paths`, reporting what each one did."""
    if remove_instead:
        return [(path, remove(path)) for path in paths]
    return [(path, upsert(path, scope)) for path in paths]
