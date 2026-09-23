"""Argument parsing and output.

The CLI is the only thing that ships, so --help is the documentation: every command,
action and flag carries its own line. The machine-facing contract is the JSON envelope
and the exit codes below; human-readable text is free to change.

Exit codes: 0 ok · 1 error · 2 validation failed · 3 not a clarity project · 4 refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .model import TYPES
from .project import Project
from .store import ClarityError

VERSION = "0.1.0"

EPILOG = """examples:
  clarity-ctl init --objective "Compare parser A and B"   set up here, answer two questions
  clarity-ctl idea add "flaky test on macOS" --type fix   capture it, no folder yet
  clarity-ctl epoch start 3                               idea or planned -> active
  clarity-ctl note 3 "ring buffer was 2x slower"          record what you tried
  clarity-ctl epoch close 3 --outcome "bumped timeout"    -> done
  clarity-ctl q active --json                             what an agent calls

ids:
  Every command that acts on an epoch takes its id. Clarity never infers which epoch
  you mean — not from the directory you are in, not from an env var, not from there
  happening to be only one active. Pass it every time.

exit codes:
  0 ok · 1 error · 2 validation failed · 3 not a clarity project · 4 refused
"""

QUERY_NAMES = "active | future | current | inactive | all | item <id> | objectives | leases"


def envelope(command: str, data, warnings=None) -> str:
    return json.dumps(
        {"ok": True, "command": command, "data": data, "warnings": warnings or [],
         "version": VERSION},
        indent=2,
    )


def emit(args, command: str, data, human: str) -> None:
    print(envelope(command, data) if getattr(args, "json", False) else human)


SECTIONS: list[tuple[str, list[tuple[str, str]]]] = []


def _section(title: str) -> list:
    """A divided group in `clarity-ctl --help`. argparse has no notion of these."""
    rows: list[tuple[str, str]] = []
    SECTIONS.append((title, rows))
    return rows


ACTIONS: dict[str, list[tuple[str, str]]] = {}


def _command_listing(width: int = 72) -> str:
    out = ["commands"]
    for title, rows in SECTIONS:
        if not rows:
            continue
        rule = "─" * max(4, width - len(title) - 3)
        out.append(f"  {title} {rule}")
        for name, help_ in rows:
            out.append(f"    {name:<10} {help_}")
            for action, action_help in ACTIONS.get(name, []):
                out.append(f"    {'':<10}   -> {action:<9} {action_help}")
        out.append("")
    return "\n".join(out)


class _Parser(argparse.ArgumentParser):
    """Top-level help, composed by hand: usage, commands, examples, then options.

    argparse renders an empty "positional arguments:" block for a subparsers action
    whose entries are all hidden, and always puts options above the epilog.
    """

    def format_help(self) -> str:
        head = self._get_formatter()
        head.add_usage(self.usage, self._actions, self._mutually_exclusive_groups)
        head.add_text(self.description)

        options = self._get_formatter()
        for group in self._action_groups:
            if group.title in ("options", "optional arguments"):
                options.start_section("options")
                options.add_arguments(group._group_actions)
                options.end_section()

        return "\n".join([
            head.format_help().rstrip(),
            "",
            _command_listing(),
            EPILOG.rstrip(),
            "",
            options.format_help().rstrip(),
            "",
        ])


def _leaf(parent, name: str, help_: str, description: str | None = None,
          section: list | None = None, into: list | None = None):
    """A command or action, always with --json."""
    if into is not None:
        into.append((name, help_))
    kwargs = {}
    if section is None:
        kwargs["help"] = help_          # listed by argparse, for nested actions
    else:
        section.append((name, help_))   # listed by _command_listing, with dividers
    node = parent.add_parser(
        name,
        description=description or help_,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        **kwargs,
    )
    node.add_argument("--json", action="store_true",
                      help="print the machine-readable envelope instead of text")
    return node


def _id_arg(node, what: str = "the epoch"):
    node.add_argument("id", help=f"id of {what}")



def _repo_arg(parser) -> None:
    parser.add_argument(
        "--repo", action="append", metavar="<repo>", dest="repos",
        help="branch only this listed repo — its path or folder name, exactly; "
             "repeat for more. Default: every listed repo")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="clarity-ctl",
        description="Project state you can read in one command, and your agent can "
                    "query without crawling the tree.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=VERSION)
    # parser_class: children must not inherit _Parser, or every -h reprints the
    # whole top-level listing
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>",
                                parser_class=argparse.ArgumentParser)
    SECTIONS.clear()
    setup, look, work, parallel = (
        _section("set up"), _section("look"), _section("work"), _section("in parallel"),
    )

    # ---- setup ----
    p_init = _leaf(sub, "init", "create the layout in this folder",
                   "Creates .clarity/, EPOCHS/, worklog.yaml, puts the clarity block in "
                   "AGENTS.md and points CLAUDE.md at it — keeping whatever those files "
                   "already say. Refuses inside a git repo: clarity's files stay out of "
                   "your code, and adopt is the command that moves the code aside.",
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

    p_install = _leaf(sub, "install", "tell your agents this project uses clarity",
                      "Writes a short marker-fenced block into AGENTS.md, and points "
                      "CLAUDE.md at it with a one-line import rather than a second copy. "
                      "Everything outside the markers is left exactly as it was, and "
                      "re-running is idempotent.\n\n"
                      "--global writes it once into your own files (~/.claude/CLAUDE.md, "
                      "~/.codex/AGENTS.md, ...) for every agent you already run, so every "
                      "project is covered. The block states its own precondition — no "
                      "worklog.yaml, no clarity — so it stays quiet elsewhere.",
                      section=setup)
    p_install.add_argument("--global", dest="global_scope", action="store_true",
                           help="write to your own agent files instead of this repo's")
    p_install.add_argument("--remove", action="store_true",
                           help="take the block back out, leaving the rest of the file")

    # ---- reading ----
    p_status = _leaf(sub, "status", "print what's in flight and what's next",
                     "Prints only; it never writes. The view is composed on every run "
                     "from the worklog plus what is true on this machine right now — "
                     "who holds a lease, and how far each branch trails its base. None of "
                     "that is written down, so none of it can go stale.", section=look)
    p_status.add_argument("--all", action="store_true",
                          help="include closed and dropped items")

    p_q = _leaf(sub, "q", "named read-only query, for you or an agent",
                f"Named queries: {QUERY_NAMES}", section=look)
    p_q.add_argument("name", metavar="<name>", help=QUERY_NAMES)
    p_q.add_argument("arg", nargs="?", metavar="<arg>",
                     help="the item id, for `q item`")

    p_path = _leaf(sub, "path", "print an epoch's folder — cd $(clarity-ctl path 7)", section=look)
    _id_arg(p_path)


    # ---- objectives ----
    obj_rows: list = []
    p_obj = _leaf(sub, "objective", "what this project is for", section=work)
    obj = p_obj.add_subparsers(dest="action", required=True, metavar="<action>")
    p_obj_set = _leaf(obj, "set", "say what the project is for, in one line",
                      description="Printed at the top of clarity-ctl status; no file keeps a "
                      "copy. What is being worked on right now is not an objective — "
                      "that is what `In flight` shows.", into=obj_rows)
    p_obj_set.add_argument("text", metavar="<text>", help="the objective, in one line")
    _leaf(obj, "show", "print the objective", into=obj_rows)

    # ---- repos ----
    repo_rows: list = []
    p_repo = _leaf(sub, "repo", "the repos epochs branch, in a workspace of several",
                   section=setup)
    repo = p_repo.add_subparsers(dest="action", required=True, metavar="<action>")
    p_repo_add = _leaf(repo, "add", "branch this repo in every epoch from now on",
                       description="For a project whose root holds several checkouts. Once "
                       "any repo is listed, `epoch start` gives each listed repo the "
                       "epoch's branch and a worktree at wt/<folder name>, and leaves the "
                       "root alone. With none listed, epochs branch the root, as in a "
                       "single-repo project.\n\n"
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
    _leaf(repo, "list", "show the repos epochs branch", into=repo_rows)

    # ---- ideas ----
    idea_rows: list = []
    p_idea = _leaf(sub, "idea", "things you might do later — no folder, no branch",
                   section=work)
    idea = p_idea.add_subparsers(dest="action", required=True, metavar="<action>")

    p_idea_add = _leaf(idea, "add", "write down something to do later", into=idea_rows)
    p_idea_add.add_argument("text", metavar="<text>", help="what the work is, in one line")
    p_idea_add.add_argument("--type", default="feature", choices=TYPES,
                            help="kind of work (default: feature)")
    p_idea_add.add_argument("--evidence",
                            help="where this came from, for an item you did not think "
                                 "up yourself — a branch, a file and line, a PR")

    _leaf(idea, "list", "show ideas and anything planned but not started", into=idea_rows)

    # ---- epochs ----
    epoch_rows: list = []
    p_epoch = _leaf(sub, "epoch", "a unit of work: one feature, fix or experiment",
                    section=work)
    epoch = p_epoch.add_subparsers(dest="action", required=True, metavar="<action>")

    p_new = _leaf(epoch, "new", "set one up without starting it — skips the idea stage",
                  into=epoch_rows)
    p_new.add_argument("text", metavar="<text>", help="what the work is, in one line")
    p_new.add_argument("--type", default="feature", choices=TYPES,
                       help="kind of work (default: feature)")
    p_new.add_argument("--evidence",
                       help="where this came from, for an item you did not think "
                            "up yourself — a branch, a file and line, a PR")

    p_start = _leaf(epoch, "start", "begin work: branch, worktree and lease", into=epoch_rows,
                    description=
                    "Takes an idea or a planned item straight to active. Creates "
                    "epoch/NNN-slug unless --branch names one; if that branch is already "
                    "checked out somewhere, wt/ symlinks to it instead of adding a worktree. "
                    "Every listed repo is branched unless --repo picks some; to add one "
                    "later, use epoch add-repo.")
    _id_arg(p_start, "the item to start")
    p_start.add_argument("--branch", help="use this branch instead of epoch/NNN-slug")
    _repo_arg(p_start)

    p_block = _leaf(epoch, "block", "park it, recording what you're waiting on",
                    into=epoch_rows)
    _id_arg(p_block)
    p_block.add_argument("reason", nargs="?", metavar="<reason>",
                         help="what you're waiting on (asked for if omitted)")

    p_unblock = _leaf(epoch, "unblock", "pick it back up", into=epoch_rows)
    _id_arg(p_unblock)

    p_reopen = _leaf(epoch, "reopen", "pick a closed epoch back up — straight to active",
                     into=epoch_rows,
                     description="Sets a done or abandoned epoch active again, recreating "
                     "its worktree and taking the lease. The old outcome is kept as a note "
                     "rather than overwritten, so the trail still shows what you thought "
                     "when you closed it.")
    _id_arg(p_reopen, "the closed epoch")
    p_reopen.add_argument("--branch", help="use this branch instead of the recorded one")

    p_add_repo = _leaf(epoch, "add-repo", "branch another listed repo in an epoch in flight",
                       into=epoch_rows, description=
                       "Gives each named repo the epoch's branch and a worktree at "
                       "wt/<folder name>, as start would have. The repo must be listed "
                       "first: clarity-ctl repo add <path>.")
    _id_arg(p_add_repo)
    p_add_repo.add_argument("repos", nargs="+", metavar="<repo>",
                            help="a listed repo — its path or folder name, exactly")

    p_drop_repo = _leaf(epoch, "drop-repo", "stop branching a repo in an epoch in flight",
                        into=epoch_rows, description=
                        "Removes the repo's worktree and keeps its branch, noting where "
                        "the branch was left. Refuses uncommitted changes, and the "
                        "epoch's last repo — close the epoch for that.")
    _id_arg(p_drop_repo)
    p_drop_repo.add_argument("repo", metavar="<repo>",
                             help="one of the epoch's repos — its path or folder name")

    p_refresh = _leaf(epoch, "refresh", "catch the epoch branch up with its base",
                      into=epoch_rows,
                      description="Merges the branch each repo's own checkout is on (main or "
                      "master if it is detached) into the epoch's branch, in its "
                      "own worktree. Nothing is deleted and no commit is discarded, so a "
                      "refresh cannot lose work. Refuses on a dirty worktree, and aborts "
                      "the merge on conflict rather than leaving it half-done.")
    _id_arg(p_refresh)

    p_close = _leaf(epoch, "close", "finish it: asks for the outcome in one line",
                    into=epoch_rows, description=
                    "Keeps the branch and records its SHA. Releases the lease. "
                    "Does not merge anything — merge before closing.")
    _id_arg(p_close)
    p_close.add_argument("outcome", nargs="?", metavar="<outcome>",
                         help="what happened, in one line (asked for if omitted)")
    p_close.add_argument("--outcome", dest="outcome_flag",
                         help="same, as a flag — for scripts and agents")
    p_close.add_argument("--abandon", action="store_true",
                         help="close as abandoned rather than done")

    # ---- notes and leases ----
    p_note = _leaf(sub, "note", "record what you tried, on an epoch",
                   "The trail a one-line outcome can't hold. Write these as you go: "
                   "they're what a fresh session reads to pick the work up.", section=work)
    _id_arg(p_note)
    p_note.add_argument("text", nargs="?", metavar="<text>", help="what you tried")

    p_rename = _leaf(sub, "rename", "change an item's name after the fact",
                     "For when the scope shifts and the title stops matching the work. "
                     "The folder and branch keep their old slug — they are paths other "
                     "things point at, and the id prefix already identifies them. The "
                     "old name is kept as a note.", section=work)
    _id_arg(p_rename, "the item")
    p_rename.add_argument("name", metavar="<name>", help="the new name, in one line")

    p_claim = _leaf(sub, "claim", "take the lease on an epoch",
                    "Says who is working an epoch, and refuses a second claim. It is a "
                    "warning, not a lock — nothing stops another agent editing the "
                    "worktree. Leases never expire on their own: if one is stale, check "
                    "whether that agent is still running, then --steal it.", section=parallel)
    _id_arg(p_claim)
    p_claim.add_argument("--steal", action="store_true",
                         help="take over someone else's lease, recording who held it")

    p_release = _leaf(sub, "release", "drop the lease", section=parallel)
    _id_arg(p_release)
    p_release.add_argument("--force", action="store_true",
                           help="release a lease held by someone else")

    ACTIONS.clear()
    ACTIONS.update(objective=obj_rows, repo=repo_rows, idea=idea_rows, epoch=epoch_rows)

    return parser


def _item_line(item) -> str:
    return f"{item.id:>3}  {item.status:<8} {item.name}"


def _split_id_text(value: str | None, text: str | None) -> tuple[int | None, str | None]:
    """`epoch close 7 "done"`. A lone non-numeric arg is the text, and the id is
    missing — resolve_id then refuses and lists the ids it could have meant."""
    if value is None:
        return None, text
    if str(value).isdigit():
        return int(value), text
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
        '  clarity-ctl idea add "the first thing you want to fix"\n'
        "  clarity-ctl epoch start 1          # -> active: branch, worktree, lease\n"
        "  clarity-ctl --help                 # every command\n"
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


def _install_data(done, scope: str) -> dict:
    return {"scope": scope,
            "files": [{"path": str(path), "action": action} for path, action in done]}


def _install_text(done, scope: str) -> str:
    if not done:
        return ("no agent instructions files found for a global install — clarity looks "
                "for ~/.claude, ~/.codex, ~/.gemini and the like, and writes only to "
                "agents you already run" if scope == "global"
                else "nothing to write")
    home = Path.home()
    lines = []
    for path, action in done:
        try:  # a global install prints ~/… ; a local one prints the bare name
            shown = f"~/{path.relative_to(home)}" if scope == "global" else path.name
        except ValueError:
            shown = str(path)
        lines.append(f"  {action:<10} {shown}")
    touched = sum(1 for _, action in done if action not in ("unchanged", "absent"))
    removing = any(action == "removed" for _, action in done)
    if not touched:
        head = "every file was already up to date"
    else:
        head = (f"clarity block taken out of {touched} file(s)" if removing
                else f"clarity block written to {touched} file(s)")
    return f"{head}\n" + "\n".join(lines)


def run(args) -> int:
    if args.command == "init":
        project = Project.init(Path.cwd(), name=args.name, overall=args.objective)
        emit(args, "init", {"root": str(project.root)}, _first_run(project))
        return 0

    if args.command == "adopt":
        project, doc, moved = Project.adopt(Path.cwd())
        emit(args, "adopt",
             {"root": str(project.root), "doc": str(doc.relative_to(project.root)),
              "moved": moved},
             _adopt_text(project, doc, moved))
        return 0

    # A global install is about the user's own agent files, not about any one
    # project — so it must work from a directory that is not a clarity project.
    if args.command == "install" and args.global_scope:
        from . import agents
        done = agents.install(agents.global_paths(), remove_instead=args.remove, scope="global")
        emit(args, "install", _install_data(done, "global"), _install_text(done, "global"))
        return 0

    project = Project.find()
    action = getattr(args, "action", None)

    if args.command == "install":
        done = project.install_agents(remove=args.remove)
        emit(args, "install", _install_data(done, "local"), _install_text(done, "local"))

    elif args.command == "status":
        emit(args, "status", project.query("all" if args.all else "current"),
             project.status_text(show_all=args.all))

    elif args.command == "q":
        data = project.query(args.name, args.arg)
        emit(args, f"q.{args.name}", data, json.dumps(data, indent=2))

    elif args.command == "path":
        folder = project.path_of(args.id)
        emit(args, "path", {"path": str(folder)}, str(folder))

    elif args.command == "objective":
        if action == "set":
            project.set_objective(args.text)
            emit(args, "objective.set", project.query("objectives"), project.status_text())
        else:
            data = project.query("objectives")
            emit(args, "objective.show", data,
                 f"OBJECTIVE  {data['overall'] or '— not set —'}")

    elif args.command == "repo":
        if action == "add":
            repos = project.repo_add(args.path)
        elif action == "remove":
            repos = project.repo_remove(args.path)
        else:
            repos = list(project.worklog.repos)
        text = ("\n".join(f"  {r}" for r in repos) if repos
                else "no repos listed — epochs branch the project root")
        emit(args, f"repo.{action}", {"repos": repos}, text)

    elif args.command == "idea":
        if action == "add":
            item = project.add(args.text, type_=args.type, evidence=args.evidence)
            emit(args, "idea.add", item.to_dict(),
                 f"idea {item.id}: {item.name}\n"
                 f"  start it with: clarity-ctl epoch start {item.id}")
        else:
            human = "\n".join(
                _item_line(i) for i in project.worklog.with_status({"idea", "planned"})
            ) or "no ideas yet — clarity-ctl idea add \"...\""
            emit(args, "idea.list", project.query("future"), human)

    elif args.command == "epoch":
        if action == "new":
            item = project.add(args.text, type_=args.type, status="planned",
                               evidence=args.evidence)
            emit(args, "epoch.new", item.to_dict(),
                 f"epoch {item.id} — {item.folder}\n"
                 f"  begin work with: clarity-ctl epoch start {item.id}")
        elif action == "start":
            item, warnings = project.start(project.resolve_id(args.id), branch=args.branch,
                                           repos=args.repos)
            if args.json:
                print(envelope("epoch.start", item.to_dict(), warnings))
            else:
                lines = [f"epoch {item.id} active on {item.branch or 'no branch'} "
                         f"— {item.folder}"]
                lines += [f"warning: {w}" for w in warnings]
                print("\n".join(lines))
        elif action == "reopen":
            item, warnings = project.start(project.resolve_id(args.id), branch=args.branch,
                                           reopen=True)
            if args.json:
                print(envelope("epoch.reopen", item.to_dict(), warnings))
            else:
                lines = [f"epoch {item.id} reopened on {item.branch or 'no branch'} "
                         f"— {item.folder}"]
                lines += [f"warning: {w}" for w in warnings]
                print("\n".join(lines))
        elif action == "add-repo":
            item, added, warnings = project.add_repos(project.resolve_id(args.id), args.repos)
            if args.json:
                print(envelope("epoch.add-repo", {**item.to_dict(), "added": added}, warnings))
            else:
                head = (f"epoch {item.id}: added {', '.join(added)} on {item.branch}" if added
                        else f"epoch {item.id} already has {', '.join(args.repos)}")
                lines = [head, f"  repos: {', '.join(item.repos or [])}"]
                lines += [f"warning: {w}" for w in warnings]
                print("\n".join(lines))
        elif action == "drop-repo":
            item, dropped = project.drop_repo(project.resolve_id(args.id), args.repo)
            emit(args, "epoch.drop-repo", {**item.to_dict(), "dropped": dropped},
                 f"epoch {item.id}: dropped {dropped}, its branch kept\n"
                 f"  repos: {', '.join(item.repos or [])}")
        elif action == "refresh":
            item, message = project.refresh(args.id)
            emit(args, "epoch.refresh", item.to_dict(), message)
        elif action == "block":
            target, reason = _split_id_text(args.id, args.reason)
            reason = reason or _ask("why is it blocked?")
            item = project.block(target, reason)
            emit(args, "epoch.block", item.to_dict(), f"epoch {item.id} blocked: {reason}")
        elif action == "unblock":
            item = project.unblock(args.id)
            emit(args, "epoch.unblock", item.to_dict(), f"epoch {item.id} active again")
        else:
            target, text = _split_id_text(args.id, args.outcome)
            outcome = args.outcome_flag or text or _ask("outcome, in one line?")
            item = project.close(target, outcome, abandoned=args.abandon)
            emit(args, "epoch.close", item.to_dict(),
                 f"epoch {item.id} {item.status}: {outcome}")

    elif args.command == "rename":
        item = project.rename(args.id, args.name)
        emit(args, "rename", item.to_dict(), f"{item.id} is now: {item.name}")

    elif args.command == "note":
        target, text = _split_id_text(args.id, args.text)
        if not text:
            raise ClarityError('nothing to note: clarity-ctl note [id] "what you tried"', code=4)
        item = project.note(target, text)
        emit(args, "note", item.to_dict(), f"noted on {item.id} ({len(item.notes)} so far)")

    elif args.command == "claim":
        item, held = project.claim(args.id, steal=args.steal)
        # no expiry by design — a lease says who and since when, and waits for a person
        human = f"epoch {item.id} claimed by {held['owner']}@{held['host']}"
        if held.get("stolen_from"):
            human += f" (taken from {held['stolen_from']})"
        emit(args, "claim", {"item": item.to_dict(), "lease": held}, human)

    elif args.command == "release":
        item = project.release(args.id, force=args.force)
        emit(args, "release", item.to_dict(), f"epoch {item.id} released")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ClarityError as err:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(err), "code": err.code,
                              "version": VERSION}, indent=2))
        else:
            print(f"clarity-ctl: {err}", file=sys.stderr)
        return err.code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
