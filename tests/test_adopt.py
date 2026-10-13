"""Adopting a project that already has work in it.

Adopt ships a document, not an algorithm, so most of what could go wrong is in
the seams around it: does the file land, does the agent block point at it, does
deleting it actually end adoption, and does the procedure it describes still
match the commands the CLI offers.
"""

import re
import shlex
import subprocess

import pytest

from clarity import Project, adopt, agents
from clarity.cli import build_parser
from clarity.store import ClarityError


def test_adopt_leaves_the_procedure_and_deleting_it_ends_adoption(repo):
    project, doc, _ = Project.adopt(repo)

    assert (repo / "worklog.yaml").exists()
    assert doc == repo / ".clarity" / "adopt.md" and doc.exists()
    assert project.worklog.items == []  # adopt proposes nothing by itself
    assert ".clarity/adopt.md" in (repo / "AGENTS.md").read_text()

    # There is no flag in the worklog: deleting the file is what finishes adoption.
    assert adopt.pending(repo)
    adopt.doc_path(repo).unlink()
    assert not adopt.pending(repo)
    assert Project.find(repo).worklog.items == []


def test_adopt_and_init_each_refuse_the_others_case(repo, tmp_path):
    with pytest.raises(ClarityError) as exc:
        Project.init(repo)  # a code repo is adopt's job
    assert exc.value.code == 4 and "clarity-ctl adopt" in str(exc.value)
    assert not (repo / ".clarity").exists()

    # A project with no history to account for is not told to account for one,
    # and re-adopting would propose items for work the worklog already tracks.
    Project.create(repo)
    assert not adopt.pending(repo)
    with pytest.raises(ClarityError) as exc:
        Project.adopt(repo)
    assert exc.value.code == 4


def test_a_folder_that_is_not_a_repo_becomes_a_state_repo(tmp_path):
    """git init and ignores, nothing committed — and epochs never branch it."""
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    project = Project.init(fresh)
    assert (fresh / "worklog.yaml").exists()
    assert project.worklog.state_repo and (fresh / ".git").is_dir()
    assert "workspace/" in (fresh / ".gitignore").read_text().splitlines()

    root = tmp_path / "workspace-root"
    (root / "workspace").mkdir(parents=True)
    Project.adopt(root)
    assert (root / ".git").is_dir()
    ignored = (root / ".gitignore").read_text().splitlines()
    assert {"workspace/", "3rd_party/", "EPOCHS/*/LOGS/"} <= set(ignored)
    log = subprocess.run(["git", "log"], cwd=str(root), capture_output=True, text=True)
    assert log.returncode != 0  # no commits: that is the human's call

    project = Project.find(root)
    assert project.worklog.state_repo
    started, _ = project.start(project.add("first").id)
    assert started.branch is None  # nothing listed, and the root is state
    assert not (root / started.folder / "wt").exists()
    assert "no repo for epochs to branch" in project.status_text()


def test_adopt_moves_a_code_repo_aside_whole(repo, git):
    """The repo goes to workspace/<name>/ intact — ignored, uncommitted, and its own
    workspace/ too."""
    (repo / ".gitignore").write_text(".env\n")
    (repo / ".env").write_text("SECRET=1\n")          # ignored: must not be stranded
    (repo / "src" / "main.py").write_text("changed\n")  # uncommitted: must survive
    (repo / "workspace").mkdir()
    (repo / "workspace" / "notes.txt").write_text("mine\n")
    head = git(["rev-parse", "HEAD"], repo)

    project, _, moved = Project.adopt(repo)

    code = repo / "workspace" / "proj"
    assert moved == "workspace/proj"
    assert (code / ".env").exists() and (code / "src" / "main.py").read_text() == "changed\n"
    assert (code / "workspace" / "notes.txt").exists()
    assert git(["rev-parse", "HEAD"], code) == head
    assert not (repo / "src").exists()
    assert project.worklog.state_repo and project.worklog.repos == ["workspace/proj"]
    assert git(["ls-files"], repo) == ""

    started, _ = project.start(project.add("first").id)
    assert (repo / started.folder / "wt" / "proj" / "src" / "main.py").exists()


def test_linked_worktrees_are_refused_and_repaired(repo, git, tmp_path):
    linked = tmp_path / "linked"
    git(["worktree", "add", "-q", "-b", "side", str(linked)], repo)

    with pytest.raises(ClarityError) as exc:
        Project.adopt(linked)
    assert exc.value.code == 4
    assert (linked / "src" / "main.py").exists()  # nothing moved

    Project.adopt(repo)  # moving the main checkout must not orphan the linked one
    assert subprocess.run(["git", "status"], cwd=str(linked),
                          capture_output=True).returncode == 0


def test_the_procedure_only_runs_what_the_cli_accepts():
    """The document is the product. A command or flag it invents is a bug in it."""
    commands = set(build_parser()._subparsers._group_actions[0].choices)

    # Only invocations: inside backticks, or in an indented code block.
    named = set(re.findall(r"`clarity-ctl ([a-z]+)", adopt.ADOPT_MD))
    named |= set(re.findall(r"^ {4}clarity-ctl ([a-z]+)", adopt.ADOPT_MD, re.M))
    assert named, "extracted no commands — the test stopped testing anything"
    assert named <= commands, f"adopt.md names commands that do not exist: {named - commands}"

    lines = re.findall(r"^ {4}clarity-ctl (.+?)(?:\s+#.*)?$", adopt.ADOPT_MD, re.M)
    assert lines
    for line in lines:
        try:
            build_parser().parse_args(shlex.split(line.replace("<id>", "1")))
        except SystemExit:
            pytest.fail(f"adopt.md says to run something the CLI rejects: clarity-ctl {line}")


def _step(n: int) -> str:
    doc = adopt.ADOPT_MD
    start = doc.index(f"## {n} ")
    return doc[start:doc.index(f"## {n + 1} ", start)]


def test_the_procedure_keeps_its_scope(repo):
    """Adoption is a tidying job with two destinations: working material to
    workspace/, existing records to a baseline epoch born closed. An earlier draft
    inventoried branches and TODO files and proposed epochs for in-flight work; that
    was cut, and this keeps it cut. Each phrase is a rule the document must still say."""
    doc = adopt.ADOPT_MD
    musts = {
        # a fresh worklog full of guessed items costs more to clean up than it saves
        "no inventory": ["Do not inventory the project's in-flight work",
                         "Do not add any other items on your way out"],
        "baseline born closed": ["clarity-ctl epoch start <id> --no-repos",
                                 "Do not create an empty epoch"],
        "both destinations": ["`workspace/`", "baseline epoch"],
        "clarity's own files stay": ["worklog.yaml", "EPOCHS/", "LEARNINGS/", ".clarity/",
                                     "AGENTS.md"],
        # repos you change get branched; repos you only use must never be
        "repos split by use": ["`3rd_party/`", "clarity-ctl repo add workspace/",
                               "3rd_party/` stay off the list"],
        # lifting runs/ out of a results dir silently breaks the script that reads it
        "whole directories": ["never reach inside one"],
        "propose, then stop": ["Then stop.", "any row can be struck"],
        # moving a build tree costs a rebuild; calling it breakage leaves 10G at the root
        "costs are priced": ["Cost of moving it", "the source is untouched",
                             "You are pricing them"],
        "absolute paths": ["pyvenv.cfg", "CMakeCache.txt", ".uv-cache", "symlink"],
        "history kept": ["git mv"],
        "nested checkout": ["moves as a whole"],  # its .git travels; merging it is out of scope
        "tidy is fine": ["already tidy is a valid outcome"],
    }
    # if install starts writing a new agent file, adopt must not sweep it away
    musts["agent files stay"] = [p.name for p in agents.local_paths(repo)]
    for rule, phrases in musts.items():
        for phrase in phrases:
            assert phrase in doc, f"{rule}: adopt.md no longer says {phrase!r}"
    assert "do not guess" in doc.lower()

    # The bucket was renamed src/ -> workspace/: "src/duckdb/src/" is ambiguous. The
    # document may mention a project's own src/ — it may not send anything there.
    assert "under `src/`" not in doc
    assert "`src/" not in doc.replace("A `src/` or `lib/`", "")

    # order: the goal decides what goes to workspace/, so it comes before the first ls;
    # layout docs are read before any move is proposed; the baseline closes after start
    goal = _step(0)
    assert "What are you trying to do in this project?" in goal
    assert "Ask the human; do not infer it from the code" in goal
    assert 'clarity-ctl objective set "' in goal and "ls -a" not in goal
    assert doc.index("What are you trying to do") < doc.index("ls -a")
    reading = _step(1)
    assert "*PLAN*.md" in reading and "README.md" in reading
    assert "one question" in _step(2).lower()
    assert doc.index("clarity-ctl epoch start <id> --no-repos") < doc.index("clarity-ctl epoch close")
