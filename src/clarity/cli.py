"""Argument parsing and output.

The CLI is the only thing that ships, so --help is the documentation: every command
and flag carries its own line. The machine-facing contract is the JSON envelope of the
three reads (status, show, search) and the exit codes below; human-readable text is
free to change.

Exit codes: 0 ok · 1 error · 2 validation failed · 3 not a clarity project · 4 refused.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import textwrap
from pathlib import Path

from . import render, search
from .model import CLOSED, TYPES, parse_id
from .project import Project
from .store import ARCHIVE, ClarityError

VERSION = "0.1.0"

# The top of `clarity-ctl --help`: the workflow first, as commands to copy. An agent
# reads this when the rules send it here or a command surprised it, so it says what
# the rules in AGENTS.md say, in the same words. Lines starting `$ ` must parse —
# tests/test_help.py runs every one through the parser.
HOW = """How work goes
  $ clarity-ctl start "<a few words>" --repo <repo|all|none> --brief "<goal and limits>"
      adds the idea, branches, makes the worktree, claims it and prints where to work
  $ clarity-ctl note <id> "..."
      when a decision changes: a reversal, an approach rejected, a result that surprised you
  $ clarity-ctl note <id> "DECISION: ..."
      a rule that outlives the epoch; AGENTS.md lists every one for later sessions
  $ clarity-ctl note <id> "HANDOFF: ..."
      stopping before it is done: what's done, what's left, what to do first
  $ clarity-ctl close <id> "<what changed and why>"
      only once all of it is merged; --drop "<why>" when it didn't work
  $ clarity-ctl idea "<a few words>"
      for later; the why and the evidence go in a note on it"""

READ = """Read (never writes) — at a terminal tables; piped, plain text, far smaller for lists
  clarity-ctl status        objective, active, next; --all adds closed
  clarity-ctl show <id>     one item: its folder, branch and every note
  clarity-ctl show <view>   active | next | closed | all | objective | repos
  clarity-ctl show closed   every closed item, by id and name
  clarity-ctl search <words>  items by keyword, in names, outcomes, briefs and notes"""

CONTRACT = """Contract
  Commands that act on an item take its id. clarity never guesses which you mean: not
  from the directory you are in, not from an env var, not from there being one active.
  --json is for scripts, on the reads only (status, show, search): {ok, command, data,
  warnings, version}; a failure has ok false, and error and code in place of data.
  Every other command prints text, and its errors go to stderr. Where stdout is not a
  terminal (an agent's shell), the three print plain text in the state block's style.
  Exit codes: 0 ok · 1 error · 2 validation failed · 3 not a clarity project · 4 refused
  Pass every argument. A missing one is asked for at a terminal and refused elsewhere,
  so an agent is never left waiting on a prompt."""

MORE = """More
  clarity-ctl <command> --help      one command: what it does, an example, its flags
  clarity-ctl help reference        every command's help on one page
  clarity-ctl --version · https://github.com/danishnxt/clarity-ctl"""

SHOW_NAMES = "active | next | closed | all | objective | repos | <id>"


def envelope(command: str, data, warnings=None) -> str:
    return json.dumps(
        {"ok": True, "command": command, "data": data, "warnings": warnings or [],
         "version": VERSION},
        indent=2,
    )


def error_envelope(command: str | None, message: str, code: int, warnings=None) -> str:
    """A failure, in the same shape as a success: every field a success has but
    `data`, plus `error` and `code`. Additive — nothing a reader relied on moved."""
    return json.dumps(
        {"ok": False, "command": command, "error": message, "code": code,
         "warnings": warnings or [], "version": VERSION},
        indent=2,
    )


def emit(args, command: str, data, human: str) -> None:
    warnings = getattr(args, "worklog_warnings", [])
    print(envelope(command, data, warnings) if getattr(args, "json", False) else human)


SECTIONS: list[tuple[str, list[tuple[str, str]]]] = []


def _section(title: str) -> list:
    """A divided group in `clarity-ctl --help`. argparse has no notion of these."""
    rows: list[tuple[str, str]] = []
    SECTIONS.append((title, rows))
    return rows


ACTIONS: dict[str, list[tuple[str, str]]] = {}


def _command_listing(width: int = 92) -> str:
    """Every command, by group: plain ones share lines, one with actions gets a line of
    its own (`repo add|remove`). Built from the parser, so a new command can't be
    missing from it."""
    out = ["All commands"]
    pad = max(len(title) for title, _ in SECTIONS)
    for title, rows in SECTIONS:
        plain = " · ".join(name for name, _ in rows if name not in ACTIONS)
        lines = (textwrap.wrap(plain, width - pad - 4, break_on_hyphens=False)
                 if plain else [])
        lines += [f"{name} {'|'.join(a for a, _ in ACTIONS[name])}"
                  for name, _ in rows if name in ACTIONS]
        out += [f"  {title if i == 0 else '':<{pad}}  {line}" for i, line in enumerate(lines)]
    return "\n".join(out)


class _Parser(argparse.ArgumentParser):
    """Top-level help, composed by hand: the workflow, the reads, every command, the
    contract. argparse would list commands as a tree of help lines and options last;
    an agent needs how the work goes first, and -h/--version are one line in More.
    """

    def format_help(self) -> str:
        return "\n\n".join([
            f"{self.prog}: {self.description}\nusage: {self.prog} <command> ...",
            HOW, READ, _command_listing(), CONTRACT, MORE,
        ]) + "\n"


def reference_text() -> str:
    """Every command's --help on one page, under a heading each, so an agent can read
    the whole tool in one call rather than one --help per command."""
    parser = build_parser()
    out = ["# clarity-ctl reference", "", parser.format_help().rstrip()]

    def walk(node, path):
        for action in node._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    out.extend(["", f"## clarity-ctl {' '.join(path + [name])}", "",
                                child.format_help().rstrip()])
                    walk(child, path + [name])

    walk(parser, [])
    return "\n".join(out) + "\n"


def _leaf(parent, name: str, help_: str, description: str | None = None,
          section: list | None = None, into: list | None = None):
    """A command, or an action under one (`repo add`)."""
    if into is not None:
        into.append((name, help_))
    kwargs = {}
    if section is None:
        kwargs["help"] = help_          # listed by argparse, for nested actions
    else:
        section.append((name, help_))   # listed by _command_listing, with dividers
    return parent.add_parser(
        name,
        description=description or help_,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        **kwargs,
    )


def _json_flag(node) -> None:
    """--json, only on the reads: status, show, search."""
    node.add_argument("--json", action="store_true",
                      help="print the machine-readable envelope, for scripts, instead of text")


# Words the commands used to take after `idea` and `objective`: alone, they are a stale
# command, not a name, and a worklog entry called "list" helps nobody.
RESERVED = ("show", "list", "add", "set")


def _name_text(command: str, text: str) -> str:
    if text.strip().lower() in RESERVED:
        raise ClarityError(f"{command} takes the text itself, and {text!r} alone is not "
                           f"one — see: clarity-ctl {command} --help", code=2)
    return text


def _id_arg(node, what: str = "the epoch"):
    node.add_argument("id", help=f"id of {what}")


def _repo_arg(parser) -> None:
    parser.add_argument(
        "--repo", action="append", metavar="<repo|all|none>", dest="repos",
        help="which listed repos to branch: one by path or folder name (repeat for more), "
             "all of them, or none. Required when the project lists repos")


def _repo_choice(project, item_id: int | str, repos: list[str] | None,
                 required: bool = True) -> tuple[list[str] | None, bool]:
    """--repo as (repos, none) for Project.start: `all` is every listed repo, `none`
    branches nothing. In a project that lists repos, leaving the choice out is refused —
    a default that branches everything is the mistake an agent makes without noticing,
    and the refusal names all three answers, so it doubles as the reminder. A closed
    epoch coming back takes the repos it had, so it asks for no choice."""
    if repos and len(repos) == 1 and repos[0] in ("all", "none"):
        return None, repos[0] == "none"
    if repos and {"all", "none"} & set(repos):
        raise ClarityError("--repo all and --repo none stand alone — not with other repos",
                           code=2)
    if required and not repos and project.worklog.repos:
        listed = ", ".join(project.worklog.repos)
        raise ClarityError(
            f"say which repos epoch {item_id} branches — one of:\n"
            f"  --repo <repo>   just these, repeat for more ({listed})\n"
            f"  --repo all      every listed repo\n"
            f"  --repo none     nothing yet; add one later with add-repo", code=2)
    return repos, False


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="clarity-ctl",
        description="project state for people and agents: what's active, what's next, "
                    "what was decided.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=VERSION)
    # parser_class: children must not inherit _Parser, or every -h reprints the
    # whole top-level listing
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>",
                                parser_class=argparse.ArgumentParser)
    SECTIONS.clear()
    look, work, capture, tidy, setup = (
        _section("read"), _section("on an id"), _section("capture"), _section("tidy"),
        _section("set up"),
    )

    # ---- reading ----
    p_status = _leaf(sub, "status", "print what's active and what's next",
                     "Prints only; it never writes. The view is composed on every run "
                     "from the worklog plus what is true on this machine right now — "
                     "who holds a lease (in --json), how far each branch trails its base, and whether "
                     "its work has landed there. None of "
                     "that is written down, so none of it can go stale.\n\n"
                     "--json lists each item with a note_count, not its notes: "
                     "`show <id> --json` has those. Where stdout is not a terminal it prints "
                     "plain text instead of tables, the state block's style: no boxes or "
                     "colour, closed work as one `#id ✓ name` line.", section=look)
    _json_flag(p_status)
    p_status.add_argument("--all", action="store_true",
                          help="include closed and dropped items")
    p_status.add_argument("--limit", type=int, default=15, metavar="N",
                          help="with --all, the N most recent closed and dropped (default "
                               "15; 0 for all). --json is never cut")
    p_status.add_argument("--order", choices=("newest", "oldest"), default="newest",
                          help="newest first (default), or oldest first — finished work "
                               "then reads as a story")
    p_status.add_argument("--children", action="store_true",
                          help="list subepochs as rows of their own, not only under "
                               "their parent epoch")

    p_show = _leaf(sub, "show", "print one view of the worklog, or one item",
                   f"Read-only. Views: {SHOW_NAMES}.\n\n"
                   "  active     epochs started and not closed\n"
                   "  next       ideas, not started\n"
                   "  closed     done and dropped\n"
                   "  all        everything\n"
                   "  objective  what the project is for\n"
                   "  repos      the repos epochs branch\n"
                   "  <id>       one item: status, folder, branch, repos, notes, plans; "
                   "lease in --json\n\n"
                   "What `status` prints, as data, is `clarity-ctl status --json`, which carries a "
                   "note count per item, not the notes: `show <id> --json` has them.\n\n"
                   "Where stdout is not a terminal it prints plain text: `show closed` is every "
                   "closed item as `#id ✓ name` (✗ dropped), newest first; `show <id>` "
                   "is the page with every note in full.",
                   section=look)
    p_show.add_argument("name", metavar="<view|id>", help=SHOW_NAMES)
    _json_flag(p_show)

    p_search = _leaf(sub, "search", "find items by keyword — the id of the one that holds a fact",
                     "Keyword search over every item, live and archived: its name, outcome, "
                     "brief and every note. Prints the best matches, each with the id and the "
                     "line that matched, so `show <id>` reads the right one. Read-only, and "
                     "nothing is indexed, so it is never stale.\n\n"
                     "Each distinct word of the query scores its best match in an item "
                     "(the same word 1, a stem like lease/leases 0.7, a typo 0.5), times how "
                     "rare the word is across the worklog; a word in the name counts 1.5x. "
                     "Ties go to the newer item.\n\n"
                     "example:\n  $ clarity-ctl search lease host", section=look)
    _json_flag(p_search)
    p_search.add_argument("words", nargs="+", metavar="<word>",
                          help="what to look for; a word starting with - goes after --")
    p_search.add_argument("--limit", type=int, default=5, metavar="N",
                          help="the N best matches (default 5; 0 for all)")

    p_help = _leaf(sub, "help", "this help, or every command's on one page",
                   "With no topic, the same as clarity-ctl --help. `help reference` prints "
                   "every command's help, one after another under a heading each: the "
                   "whole tool in one read. Works outside a project.\n\n"
                   "example:\n  $ clarity-ctl help reference", section=look)
    p_help.add_argument("topic", nargs="?", choices=["reference"],
                        help="reference: every command's help on one page")

    # ---- work on an id: ideas and epochs share ids ----
    p_start = _leaf(sub, "start", "begin work: an idea, or a new name, to active and claimed",
                    section=work, description=
                    "One call from nothing to working. Given a name, it adds the idea "
                    "first; given an id, it starts that idea. Either way the epoch gets a "
                    "folder, the branch epoch/NNN-slug (unless --branch names one) with a "
                    "worktree per repo, and a lease in your name, and start prints where "
                    "to work. A refused start adds nothing.\n\n"
                    "When the project lists repos, say which to branch: --repo <repo> "
                    "(repeat for more), --repo all, or --repo none. --repo none suits "
                    "planning or analysis with no code yet; add-repo brings a repo in "
                    "later. If the branch is already checked out somewhere, wt/ symlinks "
                    "to it instead of adding a worktree.\n\n"
                    "Given the id of a closed epoch, start picks it back up: active again, "
                    "its worktree recreated, the lease taken, and the old outcome kept as a "
                    "note. It comes back with the repos it had, so no --repo (add-repo "
                    "changes them); --branch replaces the recorded branch. Something closed "
                    "without ever being started is just started, like an idea.\n\n"
                    "Splitting the work across agents: spawn.\n\n"
                    "example:\n"
                    '  $ clarity-ctl start "memory-map the input" --repo parser '
                    '--brief "cut load time; leave the tokenizer alone"\n'
                    "  $ clarity-ctl start 12 --repo all")
    p_start.add_argument("id", help="id of the idea or closed epoch to start — or a name, a "
                                    "few words like a title, to add it as an idea and start "
                                    "it in one go")
    p_start.add_argument("--branch", help="use this branch instead of epoch/NNN-slug "
                                          "(or the recorded one, for a closed epoch)")
    p_start.add_argument("--brief", metavar="<text|file>",
                         help="what the work is for and what limits apply — the text, or a "
                              "file holding it; shown first to whoever picks the epoch up")
    _repo_arg(p_start)

    p_close = _leaf(sub, "close", "finish it, with its outcome in one line",
                    section=work, description=
                    "Takes an idea too: one already done elsewhere or not wanted is closed "
                    "without starting it, so no folder or branch is made.\n\n"
                    "Close only when the whole task is done and merged. The outcome says "
                    "what changed and why — for a bug, what was wrong. Part of it left for "
                    "later: don't close; keep it active and write a HANDOFF: note.\n\n"
                    "Keeps the branch and records its SHA, and releases the lease. Never "
                    "merges: merge first. --drop closes it as dropped, the outcome saying "
                    "why it didn't work. start <id> picks a closed epoch back up.\n\n"
                    "example:\n"
                    '  $ clarity-ctl close 7 "mmap halved load time; total unchanged, '
                    'the tokenizer is the bottleneck"\n'
                    '  $ clarity-ctl close 8 --drop "no gain: I/O is 5% of the run"')
    _id_arg(p_close)
    p_close.add_argument("outcome", nargs="?", metavar="<outcome>",
                         help="what changed and why, in one line (asked for only at a "
                              "terminal)")
    p_close.add_argument("--drop", action="store_true",
                         help="close as dropped rather than done")

    p_note = _leaf(sub, "note", "record a decision, a DECISION: rule or a HANDOFF:",
                   "For what the next session can't get from the code or git. Write one "
                   "the moment a decision changes — a reversal, an approach rejected and "
                   "why, a result that surprised you — not at the end: in a long session "
                   "the end never comes. Routine progress is not a note.\n\n"
                   "A note starting DECISION: is a rule that outlives the epoch; AGENTS.md "
                   "lists every one. A note starting HANDOFF: is for stopping before the "
                   "work is done: what's done, what's left, what to do first; show <id> "
                   "puts the latest up front.\n\n"
                   "example:\n"
                   '  $ clarity-ctl note 7 "mmap rejected: load is 5% of the run"\n'
                   '  $ clarity-ctl note 7 "DECISION: stdlib only, the ops boxes have no pip"\n'
                   '  $ clarity-ctl note 7 "HANDOFF: lexer ported; parser half done, start at '
                   'parse_expr"', section=work)
    _id_arg(p_note, "the item")
    p_note.add_argument("text", nargs="?", metavar="<text>", help="the note")

    p_spawn = _leaf(sub, "spawn", "start a subepoch of an active epoch, for another agent",
                    section=work, description=
                    "Adds and starts one part of an active epoch, numbered under it: "
                    "spawning under 7 gives 7.1, then 7.2. Its branch is cut from 7's and "
                    "merges back into it; only 7 merges onward. It branches 7's repos "
                    "unless --repo names some of them. Its folder goes in "
                    "EPOCHS/subepochs/<7's folder>/, and 7 cannot close while it is "
                    "active.\n\n"
                    "The lease is left free for the agent doing the part: it claims with "
                    "claim <id> --as <name>, and writes a HANDOFF: note when it stops. "
                    "Whoever owns 7 reviews, merges, and closes it.\n\n"
                    "Quick work that needs no branch of its own is a note on 7, not a "
                    "subepoch.")
    _id_arg(p_spawn, "the active epoch it is a part of")
    p_spawn.add_argument("name", help="what the part is, a few words like a title")
    p_spawn.add_argument("--brief", metavar="<text|file>",
                         help="what this part is for and what limits apply — the text, or "
                              "a file holding it; the first thing its agent reads")
    p_spawn.add_argument("--type", default="feature", choices=TYPES)
    _repo_arg(p_spawn)

    p_refresh = _leaf(sub, "refresh", "catch the epoch branch up with its base",
                      section=work,
                      description="Merges each repo's base into the epoch's branch, in its "
                      "own worktree. The base is the branch that repo's checkout was on when "
                      "the epoch first branched it (main or master if it was detached), "
                      "recorded then — switching the checkout later changes nothing. "
                      "Nothing is deleted and no commit is discarded, so a "
                      "refresh cannot lose work. Refuses on a dirty worktree, and aborts "
                      "the merge on conflict rather than leaving it half-done.")
    _id_arg(p_refresh)
    p_refresh.add_argument("--base", metavar="<branch>",
                           help="catch up with this branch from now on, instead of the "
                                "recorded one; recorded before merging")
    p_refresh.add_argument("--repo", action="append", metavar="<repo>", dest="repos",
                           help="refresh only this one of the epoch's repos, and set "
                                "--base only for it; repeat for more")

    p_claim = _leaf(sub, "claim", "take the lease on an epoch",
                    "start already claims; claim is for taking over an epoch, or "
                    "for the agent doing a subepoch.\n\n"
                    "Says who is working an epoch, and refuses a second claim. It is a "
                    "warning, not a lock — nothing stops another agent editing the "
                    "worktree. Leases never expire on their own: if one is stale, check "
                    "whether that agent is still running, then --steal it. close lets "
                    "it go.", section=work)
    _id_arg(p_claim)
    p_claim.add_argument("--steal", action="store_true",
                         help="take over someone else's lease, recording who held it")
    p_claim.add_argument("--as", dest="as_name", metavar="<name>",
                         help="name the holder, e.g. epoch15-opus, so status --json shows "
                              "which agent holds what")

    p_rename = _leaf(sub, "rename", "change an item's name after the fact",
                     "For when the scope shifts and the title stops matching the work. "
                     "The folder and branch keep their old slug — they are paths other "
                     "things point at, and the id prefix already identifies them. The "
                     "old name is kept as a note.", section=work)
    _id_arg(p_rename, "the item")
    p_rename.add_argument("name", metavar="<name>", help="the new name, a short title")

    p_add_repo = _leaf(sub, "add-repo", "branch another listed repo in an epoch in flight",
                       section=work, description=
                       "Gives each named repo the epoch's branch and a worktree at "
                       "wt/<folder name>, as start would have. The repo must be listed "
                       "first: clarity-ctl repo add <path>.")
    _id_arg(p_add_repo)
    p_add_repo.add_argument("repos", nargs="+", metavar="<repo>",
                            help="a listed repo — its path or folder name, exactly")

    p_drop_repo = _leaf(sub, "drop-repo", "stop branching a repo in an epoch in flight",
                        section=work, description=
                        "Removes the repo's worktree and keeps its branch, noting where "
                        "the branch was left. Refuses uncommitted changes, and the "
                        "epoch's last repo — close the epoch for that.")
    _id_arg(p_drop_repo)
    p_drop_repo.add_argument("repo", metavar="<repo>",
                             help="one of the epoch's repos — its path or folder name")

    # ---- capture ----
    p_idea = _leaf(sub, "idea", "write down something to do later — no folder, no branch",
                   "An idea is work not started: no folder, no branch. Name it like a "
                   "title, a few words, and put the why and the evidence in a note on it "
                   "straight after; lists show the name, the note is the detail. "
                   "start <id> picks it up.\n\n"
                   "example:\n"
                   '  $ clarity-ctl idea "flaky test on macOS" --type fix\n'
                   '  $ clarity-ctl note 12 "fails 1 in 5 on macOS 15 only; see CI run 4411"',
                   section=capture)
    p_idea.add_argument("text", metavar="<text>",
                        help="a short title, a few words — the detail goes in a note")
    p_idea.add_argument("--type", default="feature", choices=TYPES,
                        help="kind of work (default: feature)")
    p_idea.add_argument("--evidence",
                        help="where this came from, for an item you did not think "
                             "up yourself — a branch, a file and line, a PR")

    # ---- tidy ----
    _leaf(sub, "archive", "move closed epochs out of worklog.yaml into ARCHIVE/",
          "Closed epochs and dropped ideas leave the live worklog for ARCHIVE/<month>.yaml, "
          "one file per month they ended in. Their folders stay put and their ids are never "
          "reused. Archived epochs still read with show <id>; they cannot be changed.",
          section=tidy)

    # ---- setup ----
    p_init = _leaf(sub, "init", "create the layout in this folder",
                   "Creates .clarity/, EPOCHS/, worklog.yaml, puts the clarity block in "
                   "AGENTS.md and points CLAUDE.md at it — keeping whatever those files "
                   "already say. Refuses inside a git repo: clarity's files stay out of "
                   "your code, and adopt is the command that moves the code aside. In a "
                   "project that already exists it instead rewrites the agent files to this "
                   "version and says what changed.",
                   section=setup)
    p_init.add_argument("--name", help="project name (default: this folder's name)")
    p_init.add_argument("--objective", help="the overall objective — what this project is for")

    _leaf(sub, "adopt", "set up in a folder that already has files in it",
          "Does what init does, then writes .clarity/adopt.md — the procedure an "
          "agent follows to tidy the layout. It asks what the project is for first, "
          "then sorts the root: repos you change and the scripts around them go to "
          "workspace/, repos you only use go to 3rd_party/, and logs and results from "
          "work already done go into a baseline epoch, closed on arrival. The "
          "workspace/ repos are listed with `clarity-ctl repo add`, so epochs branch "
          "them.\n\n"
          "If the folder is itself a git repo, adopt first moves all of it, .git "
          "included, to workspace/<folder name>/ and lists it. Either way the root "
          "becomes a repo for clarity's own files only, with nothing committed.\n\n"
          "The moves are proposed as a table and wait for your yes, because moving a "
          "build tree or a virtualenv costs a rebuild. Nothing in flight is added to "
          "the worklog — what you are working on now stays yours to write down. Point "
          "an agent at that file; it deletes it when done, and its absence is what "
          "'adoption finished' means.",
          section=setup)

    p_obj = _leaf(sub, "objective", "say what the project is for, in one line",
                  "Printed at the top of clarity-ctl status; no file keeps a copy. What is "
                  "being worked on right now is not an objective — that is what `Active` "
                  "shows. `show objective` prints it.", section=setup)
    p_obj.add_argument("text", metavar="<text>", help="the objective, in one line")

    repo_rows: list = []
    p_repo = _leaf(sub, "repo", "the repos epochs branch, in a workspace of several",
                   section=setup)
    repo = p_repo.add_subparsers(dest="action", required=True, metavar="<action>")
    p_repo_add = _leaf(repo, "add", "branch this repo in every epoch from now on",
                       description="For a project whose root holds several checkouts. Once "
                       "any repo is listed, `start` gives each listed repo the "
                       "epoch's branch and a worktree at wt/<folder name>, and leaves the "
                       "root alone. With none listed, epochs branch the root, as in a "
                       "single-repo project. `show repos` lists them.\n\n"
                       "List the repos you change. Ones you only use — a tool, a "
                       "dependency — stay off it and live in 3rd_party/.", into=repo_rows)
    p_repo_add.add_argument("path", metavar="<path>",
                            help="the repo, e.g. workspace/mini-swe-agent — from the project "
                                 "root, or from where you are")
    p_repo_rm = _leaf(repo, "remove", "stop branching this repo in new epochs",
                      description="Epochs already started keep the repos they were "
                      "started with, so closing them still cleans up.", into=repo_rows)
    p_repo_rm.add_argument("path", metavar="<repo>",
                           help="the repo — its listed path or folder name, e.g. web")

    ACTIONS.clear()
    ACTIONS.update(repo=repo_rows)

    return parser


def _split_id_text(value: str | None, text: str | None) -> tuple[int | None, str | None]:
    """`close 7 "done"`. A lone non-numeric arg is the text, and the id is
    missing — resolve_id then refuses and lists the ids it could have meant."""
    if value is None:
        return None, text
    if parse_id(value) is not None:
        return parse_id(value), text
    return None, value


def _ask(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise ClarityError(f"{prompt} — pass it as an argument when not on a terminal", code=4)
    return input(f"{prompt} ").strip()


def _first_run(project) -> str:
    return (
        f"clarity initialised in {project.root}\n\n"
        f"{project.status_text()}\n"
        "next — your code goes in workspace/, as its own repo:\n"
        "  git clone <url> workspace/<name>   # or git init one there\n"
        "  clarity-ctl repo add workspace/<name>\n"
        '  clarity-ctl start "the first thing you want to fix" --repo all\n'
        "  clarity-ctl --help                 # how the work goes\n"
    )


def _adopt_text(project, doc: Path, moved: str | None) -> str:
    rel = doc.relative_to(project.root)
    return (
        f"clarity initialised in {project.root}\n"
        + (f"\nthis folder was a git repo, so all of it moved to {moved}/ — history,\n"
           f"branches and uncommitted work intact. Push from there from now on.\n"
           f"Anything that recorded an absolute path, like a virtualenv, needs a rebuild.\n\n"
           if moved else "")
        + f"this folder has files in it that predate clarity, and the root is now "
        f"clarity's\n\n"
        f"wrote {rel}: the procedure for tidying that up. It starts by asking\n"
        f"what the project is for. Repos you change go under workspace/, repos\n"
        f"you only use under 3rd_party/, and logs and results from work already\n"
        f"done into a baseline epoch, closed on arrival. Every move is proposed\n"
        f"as a table before anything is touched.\n"
        f"It is written for an agent. Point one at it:\n\n"
        f'  "read {rel} and follow it"\n\n'
        f"Nothing in flight is added to the worklog. What you are working on now\n"
        f"stays yours to write down afterwards, a line at a time.\n"
        + "\nthe root is a git repo now, for clarity's own files only. Nothing is\n"
          "committed; commit it when you want to keep or share it.\n"
    )


def _repos_view(repos: list[str], indent: str = "  ") -> str:
    return ("\n".join(f"{indent}{r}" for r in repos) if repos
            else "no repos listed — epochs branch the project root")


def _repos_line(item) -> str:
    """Which repos an epoch branches and what each follows: `repos: agent (main), web`."""
    bases = item.bases or {}
    shown = [f"{Path(r).name} ({bases[r]})" if r in bases else Path(r).name
             for r in item.repos or []]
    if not shown and "." in bases:
        return f"  base: {bases['.']}"
    return f"  repos: {', '.join(shown) or 'none'}"


def _started_text(item, verb: str, warnings: list[str]) -> str:
    lines = [f"epoch {item.id} {verb} on {item.branch or 'no branch'} — {item.folder}"]
    if item.branch:
        lines.append(_repos_line(item))
        for r in item.repos or []:
            lines.append(f"  work in: {item.folder}/wt/{Path(r).name}")
    elif item.repos == []:
        lines.append(f"  no repos yet — when code starts: "
                     f"clarity-ctl add-repo {item.id} <repo>")
    lines += [f"warning: {w}" for w in warnings]
    return "\n".join(lines)


def _refresh_text(item, report: dict) -> str:
    def where(repo: str) -> str:
        return "" if repo == "." else f" in {repo}"

    lines = []
    if report["merged"]:
        done = ", ".join(
            f"{m['base']}{where(m['repo'])} ({m['commits']} commit"
            f"{'s' if m['commits'] != 1 else ''})" for m in report["merged"])
        lines.append(f"epoch {item.id}: {item.branch} caught up with {done}")
    if report["up_to_date"]:
        same = ", ".join(f"{u['base']}{where(u['repo'])}" for u in report["up_to_date"])
        lines.append(f"epoch {item.id}: already up to date with {same}")
    return "\n".join(lines)


def _plain() -> bool:
    """The reads print for whoever is reading: tables and colour for a person at a
    terminal, plain text everywhere else — an agent's shell is never a terminal."""
    return not sys.stdout.isatty()


def run(args) -> int:
    if args.command == "init":
        here = Project.existing(Path.cwd())
        if here:
            done = here.install_agents()
            print("already a clarity project — agent files:\n"
                  + "\n".join(f"  {action:<10} {path.name}" for path, action in done))
            return 0
        project = Project.init(Path.cwd(), name=args.name, overall=args.objective)
        print(_first_run(project))
        return 0

    if args.command == "adopt":
        project, doc, moved = Project.adopt(Path.cwd())
        print(_adopt_text(project, doc, moved))
        return 0

    if args.command == "help":
        print((reference_text() if args.topic else build_parser().format_help()).rstrip())
        return 0

    project = Project.find()
    # A worklog from a newer clarity-ctl still reads; every write refuses on its own,
    # and main prints this after a read only, so a refusal does not say it twice.
    warning = project.worklog.newer_warning()
    args.worklog_warnings = [warning] if warning else []
    args.worklog_warnings += project.missing_warnings()

    plain = _plain()

    if args.command == "status":
        data = project.query("all" if args.all else "current")
        # the ⚠ lines status prints about bases, as data — keyed by id, like leases
        data["stale"] = project.stale_map()
        # whether each epoch's work reached its base, per repo — merged, unmerged, unknown
        landed = project.landed_map()
        # who holds which epoch — data only; the tables leave it out
        data["leases"] = project.leases()
        make = project.agent_status_text if plain else project.status_text
        text = make(show_all=args.all, oldest_first=args.order == "oldest", limit=args.limit,
                    landed=landed, children=args.children)
        # the JSON is the index, not the archive: a count in place of the notes (show <id>
        # has them), and marks only for the items it lists
        listed = {i["id"] for i in data["items"]}
        data["landed"] = {k: v for k, v in landed.items() if k in listed}
        for item in data["items"]:
            item["note_count"] = len(item.pop("notes", []))
        emit(args, "status", data, text)

    elif args.command == "show":
        name = args.name
        if parse_id(name) is not None:
            data = project.query("item", name)
            marks = project.landed_map(only=data["id"]).get(data["id"])
            if marks:
                data["landed"] = marks  # per repo, as status --json carries it
            page = render.agent_item if plain else render.item_text
            emit(args, "show.item", data, page(data, marks))
        else:
            if name not in Project.SHOW_NAMES:
                raise ClarityError(
                    f"unknown view {name!r}; try: {', '.join(Project.SHOW_NAMES)}, or an id",
                    code=2)
            data = project.query(name)
            if name == "objective":
                human = f"OBJECTIVE  {data['overall'] or '— not set —'}"
            elif name == "repos":
                human = _repos_view(data["repos"], indent="" if plain else "  ")
            else:
                human = (project.agent_view_text if plain else project.view_text)(name)
            emit(args, f"show.{name}", data, human)

    elif args.command == "search":
        by_id = {i.id: i for i in project.worklog.all_items()}
        hits = search.search(list(by_id.values()), args.words, args.limit)
        data = {"query": search.terms(args.words),
                "hits": [{"id": h.id, "name": h.name, "status": h.status,
                          "score": round(h.score, 2), "field": h.field,
                          "snippet": h.snippet} for h in hits]}
        emit(args, "search", data, render.search_text(hits, plain=plain))

    elif args.command == "objective":
        project.set_objective(_name_text("objective", args.text))
        print(project.status_text())

    elif args.command == "repo":
        repos = (project.repo_add(args.path) if args.action == "add"
                 else project.repo_remove(args.path))
        print(_repos_view(repos, indent="  "))

    elif args.command == "idea":
        item = project.add(_name_text("idea", args.text), type_=args.type,
                           evidence=args.evidence)
        print(f"idea {item.id}: {item.name}\n"
              f"  start it with: clarity-ctl start {item.id}"
              + (" --repo <repo|all|none>" if project.worklog.repos else ""))

    elif args.command == "start":
        # A name rather than an id: the idea and its start are one step, because an
        # agent about to work has no use for the idea on its own.
        # Added only once the checks pass, so a refused start leaves no stray idea.
        item_id = None if parse_id(args.id) is None else project.resolve_id(args.id)
        item = None if item_id is None else project.worklog.by_id(item_id)
        # a closed epoch comes back with the repos it had, so it is never asked which
        coming_back = item is not None and item.status in CLOSED and not item.never_started
        if coming_back and args.repos:
            raise ClarityError("a closed epoch comes back with the repos it had — add one "
                               f"after with:\n  clarity-ctl add-repo {item_id} <repo>", code=4)
        repos, no_repos = _repo_choice(project, item_id or f'"{args.id}"', args.repos,
                                       required=not coming_back)
        if no_repos and args.branch:
            raise ClarityError("--branch names the branch to make, and --repo none "
                               "makes none — pass one", code=2)
        made = item_id is None
        if made:
            item_id = project.add(args.id).id
        try:
            item, warnings = project.start(item_id, branch=args.branch,
                                           repos=repos, no_repos=no_repos,
                                           brief=args.brief)
        except Exception:
            if made:
                project.forget(item_id)  # start's own checks can still refuse
            raise
        print(_started_text(item, "reopened" if coming_back else "active", warnings))

    elif args.command == "spawn":
        repos, no_repos = _repo_choice(project, args.id, args.repos, required=False)
        item, warnings = project.spawn(args.id, args.name, type_=args.type,
                                       brief=args.brief, repos=repos, no_repos=no_repos)
        print(_started_text(item, "spawned", warnings)
              + f"\n  its agent claims it: clarity-ctl claim {item.id} --as <name>")

    elif args.command == "add-repo":
        item, added, warnings = project.add_repos(project.resolve_id(args.id), args.repos)
        head = (f"epoch {item.id}: added {', '.join(added)} on {item.branch}" if added
                else f"epoch {item.id} already has {', '.join(args.repos)}")
        print("\n".join([head, _repos_line(item), *(f"warning: {w}" for w in warnings)]))

    elif args.command == "drop-repo":
        item, dropped = project.drop_repo(project.resolve_id(args.id), args.repo)
        print(f"epoch {item.id}: dropped {dropped}, its branch kept\n" + _repos_line(item))

    elif args.command == "refresh":
        item, report = project.refresh(args.id, base=args.base, repos=args.repos)
        print(_refresh_text(item, report))

    elif args.command == "close":
        target, text = _split_id_text(args.id, args.outcome)
        outcome = text or _ask("outcome, in one line?")
        # a dropped epoch's work is not meant to land, so only done asks
        warnings = [] if args.drop else project.unmerged(project.resolve_id(target))
        item = project.close(target, outcome, dropped=args.drop)
        head = (f"idea {item.id} {item.status} without starting: {outcome}"
                if item.never_started else f"epoch {item.id} {item.status}: {outcome}")
        print("\n".join([head, *(f"warning: {w}" for w in warnings)]))

    elif args.command == "rename":
        item = project.rename(args.id, args.name)
        print(f"{item.id} is now: {item.name}")

    elif args.command == "archive":
        written = project.archive()
        print("\n".join(f"archived {n} into {ARCHIVE}/{name}" for name, n in written)
              or "nothing to archive — no closed epochs in worklog.yaml")

    elif args.command == "note":
        target, text = _split_id_text(args.id, args.text)
        if not text:
            raise ClarityError('nothing to note: clarity-ctl note <id> "..."', code=4)
        item = project.note(target, text)
        print(f"noted on {item.id} ({len(item.notes)} so far)")

    elif args.command == "claim":
        item, held = project.claim(args.id, steal=args.steal, as_name=args.as_name)
        # no expiry by design — a lease says who and since when, and waits for a person
        human = f"epoch {item.id} claimed by {held['owner']}@{held['host']}"
        if held.get("stolen_from"):
            human += f" (taken from {held['stolen_from']})"
        print(human)

    return 0


JSON_READS = ("status", "show", "search")


def _parse(argv: list[str]):
    """parse_args, except that a caller who asked for --json gets an envelope for
    a typo too, rather than usage text it cannot parse. Exit 2, as argparse's own.
    Only the reads have --json; a typo anywhere else is argparse's plain usage error."""
    if "--json" not in argv or argv[0] not in JSON_READS:
        return build_parser().parse_args(argv)
    caught = io.StringIO()
    try:
        with contextlib.redirect_stderr(caught):
            return build_parser().parse_args(argv)
    except SystemExit as stop:
        if stop.code in (0, None):
            raise  # --help asked for, and printed
        message = caught.getvalue().strip().splitlines()[-1]
        message = message.split(": error: ", 1)[-1]
        print(error_envelope(argv[0], message, 2))
        raise SystemExit(2) from None


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        code = run(args)
        if not getattr(args, "json", False):
            for warning in getattr(args, "worklog_warnings", []):
                print(f"warning: {warning}", file=sys.stderr)
        return code
    except ClarityError as err:
        if getattr(args, "json", False):
            print(error_envelope(args.command, str(err), err.code,
                                 getattr(args, "worklog_warnings", [])))
        else:
            print(f"clarity-ctl: {err}", file=sys.stderr)
        return err.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
