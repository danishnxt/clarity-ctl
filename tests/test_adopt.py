"""Adopting a project that already has work in it.

Adopt ships a document, not an algorithm, so most of what could go wrong is in
the seams around it: does the file land, does the agent block point at it, does
deleting it actually end adoption, and does the procedure it describes still
match the commands the CLI offers.
Run: .venv/bin/python -m pytest -q
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clarity import Project, adopt, agents  # noqa: E402
from clarity.store import ClarityError  # noqa: E402

from test_lifecycle import make_repo  # noqa: E402


def test_adopt_sets_up_and_leaves_the_procedure(tmp_path):
    root = make_repo(tmp_path)
    project, doc, moved = Project.adopt(root)

    assert (root / "worklog.yaml").exists()
    assert doc == root / ".clarity" / "adopt.md"
    assert doc.exists()
    assert project.worklog.items == []  # adopt proposes nothing by itself


def test_adopt_refuses_an_existing_project(tmp_path):
    """Re-running would propose items for work the worklog already tracks."""
    root = make_repo(tmp_path)
    Project.create(root)

    try:
        Project.adopt(root)
    except ClarityError as exc:
        assert exc.code == 4
    else:
        raise AssertionError("adopting twice should refuse")


def test_pending_is_the_files_presence_and_nothing_else(tmp_path):
    """There is no flag in the worklog: deleting the file is what finishes adoption."""
    root = make_repo(tmp_path)
    Project.adopt(root)
    assert adopt.pending(root)

    adopt.doc_path(root).unlink()
    assert not adopt.pending(root)
    assert Project.find(root).worklog.items == []  # nothing about it was written down


def test_adopt_makes_a_non_repo_root_a_repo_for_clarity_only(tmp_path):
    """git init and ignores, nothing committed — and epochs never branch it."""
    root = tmp_path / "workspace-root"
    (root / "workspace").mkdir(parents=True)
    project, _, _ = Project.adopt(root)

    assert (root / ".git").is_dir()
    ignored = (root / ".gitignore").read_text().splitlines()
    assert {"workspace/", "3rd_party/", "EPOCHS/*/LOGS/"} <= set(ignored)
    log = subprocess.run(["git", "log"], cwd=str(root), capture_output=True, text=True)
    assert log.returncode != 0  # no commits: that is the human's call

    project = Project.find(root)
    assert project.worklog.state_repo
    epoch = project.add("first", status="planned")
    started, _ = project.start(epoch.id)
    assert started.branch is None  # nothing listed, and the root is state
    assert not (root / started.folder / "wt").exists()
    assert "no repo for epochs to branch" in project.status_text()


def test_adopt_moves_a_code_repo_aside_whole(tmp_path):
    """The repo goes to workspace/<name>/ intact — ignored and uncommitted files too."""
    root = make_repo(tmp_path)
    (root / ".gitignore").write_text(".env\n")
    (root / ".env").write_text("SECRET=1\n")          # ignored: must not be stranded
    (root / "src" / "main.py").write_text("changed\n")  # uncommitted: must survive
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                          capture_output=True, text=True).stdout

    project, _, moved = Project.adopt(root)

    code = root / "workspace" / "proj"
    assert moved == "workspace/proj"
    assert (code / ".env").exists() and (code / "src" / "main.py").read_text() == "changed\n"
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(code),
                          capture_output=True, text=True).stdout == head
    assert not (root / "src").exists()
    assert project.worklog.state_repo and project.worklog.repos == ["workspace/proj"]
    assert subprocess.run(["git", "ls-files"], cwd=str(root),
                          capture_output=True, text=True).stdout == ""

    epoch = project.add("first", status="planned")
    started, _ = project.start(epoch.id)
    assert (root / started.folder / "wt" / "proj" / "src" / "main.py").exists()


def test_adopt_moves_a_repo_that_has_its_own_workspace(tmp_path):
    root = make_repo(tmp_path)
    (root / "workspace").mkdir()
    (root / "workspace" / "notes.txt").write_text("mine\n")
    Project.adopt(root)
    assert (root / "workspace" / "proj" / "workspace" / "notes.txt").exists()


def test_adopt_refuses_a_linked_worktree(tmp_path):
    root = make_repo(tmp_path)
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(linked)],
                   cwd=str(root), check=True, capture_output=True)
    with pytest.raises(ClarityError) as exc:
        Project.adopt(linked)
    assert exc.value.code == 4
    assert (linked / "src" / "main.py").exists()  # nothing moved


def test_adopt_repairs_the_repos_linked_worktrees(tmp_path):
    root = make_repo(tmp_path)
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "-q", "-b", "side", str(linked)],
                   cwd=str(root), check=True, capture_output=True)
    Project.adopt(root)
    status = subprocess.run(["git", "status"], cwd=str(linked),
                            capture_output=True, text=True)
    assert status.returncode == 0


def test_init_refuses_a_code_repo_and_points_at_adopt(tmp_path):
    root = make_repo(tmp_path)
    with pytest.raises(ClarityError) as exc:
        Project.init(root)
    assert exc.value.code == 4
    assert "clarity-ctl adopt" in str(exc.value)
    assert not (root / ".clarity").exists()


def test_init_sets_up_a_folder_that_is_not_a_repo(tmp_path):
    root = tmp_path / "fresh"
    root.mkdir()
    project = Project.init(root)
    assert (root / "worklog.yaml").exists()
    assert project.worklog.state_repo and (root / ".git").is_dir()
    assert "workspace/" in (root / ".gitignore").read_text().splitlines()


def test_init_alone_leaves_no_procedure(tmp_path):
    """A project with no history to account for should not be told to account for one."""
    root = make_repo(tmp_path)
    Project.create(root)
    assert not adopt.pending(root)


def test_the_agent_block_points_at_the_document(tmp_path):
    root = make_repo(tmp_path)
    Project.adopt(root)

    block = (root / "AGENTS.md").read_text()
    assert ".clarity/adopt.md" in block


def test_the_block_stays_short():
    """It loads every turn of every session. Adopt is allowed one line, not a section."""
    mentions = [line for line in agents.LOCAL_BLOCK.splitlines() if "adopt.md" in line]
    assert len(mentions) == 1


def test_the_procedure_only_names_commands_that_exist():
    """The document is the product. A command it invents is a bug in the product."""
    from clarity.cli import build_parser

    parser = build_parser()
    commands = set(parser._subparsers._group_actions[0].choices)

    # Only invocations: inside backticks, or in an indented code block.
    named = set(re.findall(r"`clarity-ctl ([a-z]+)", adopt.ADOPT_MD))
    named |= set(re.findall(r"^ {4}clarity-ctl ([a-z]+)", adopt.ADOPT_MD, re.M))
    assert named, "extracted no commands — the test stopped testing anything"
    assert named <= commands, f"adopt.md names commands that do not exist: {named - commands}"


def test_the_procedure_only_uses_flags_that_exist():
    """A removed flag is as broken as a removed command — parse every line it says to run."""
    import shlex

    from clarity.cli import build_parser

    lines = re.findall(r"^ {4}clarity-ctl (.+?)(?:\s+#.*)?$", adopt.ADOPT_MD, re.M)
    assert lines
    for line in lines:
        argv = shlex.split(line.replace("<id>", "1"))
        try:
            build_parser().parse_args(argv)
        except SystemExit:
            pytest.fail(f"adopt.md says to run something the CLI rejects: clarity-ctl {line}")


# The rest of this file guards the scope of adoption. It is a tidying job with
# two destinations: working material to workspace/, existing records to a
# baseline epoch that is born closed. An earlier draft inventoried branches and
# TODO files and proposed epochs for in-flight work; that was cut, and these
# keep it cut.


def test_adoption_does_not_inventory_in_flight_work():
    """A fresh worklog full of guessed items costs more to clean up than it saves."""
    assert "Do not inventory the project's in-flight work" in adopt.ADOPT_MD
    assert "Do not add any other items on your way out" in adopt.ADOPT_MD


def test_the_baseline_epoch_is_created_closed():
    """The one item adoption creates describes work already done, so it starts done."""
    assert "clarity-ctl epoch new" in adopt.ADOPT_MD
    assert "clarity-ctl epoch close" in adopt.ADOPT_MD
    close_at = adopt.ADOPT_MD.index("clarity-ctl epoch close")
    new_at = adopt.ADOPT_MD.index("clarity-ctl epoch new")
    assert new_at < close_at, "close must follow new — the epoch is never left in flight"
    assert "Do not create an empty epoch" in adopt.ADOPT_MD


def test_both_destinations_are_named():
    assert "`workspace/`" in adopt.ADOPT_MD
    assert "baseline epoch" in adopt.ADOPT_MD
    # The bucket was renamed src/ -> workspace/: in a workspace holding a checkout
    # that has its own src/, "src/duckdb/src/" is ambiguous. The document may still
    # mention a project's own src/ — what it may not do is send anything there.
    assert "under `src/`" not in adopt.ADOPT_MD
    assert "`src/" not in adopt.ADOPT_MD.replace("A `src/` or `lib/`", "")
    for own in ("worklog.yaml", "EPOCHS/", "LEARNINGS/", ".clarity/", "AGENTS.md"):
        assert own in adopt.ADOPT_MD, f"{own} is not listed as staying at the root"


def _step(n: int) -> str:
    doc = adopt.ADOPT_MD
    start = doc.index(f"## {n} ")
    return doc[start:doc.index(f"## {n + 1} ", start)]


def test_the_goal_is_asked_before_anything_is_listed():
    """It decides which repos go to workspace/ — so it comes before the first `ls`."""
    first = _step(0)
    assert "What are you trying to do in this project?" in first
    assert 'clarity-ctl objective set "' in first
    assert "ls -a" not in first
    assert adopt.ADOPT_MD.index("What are you trying to do") < adopt.ADOPT_MD.index("ls -a")


def test_layout_instructions_are_read_before_anything_is_proposed():
    """A move against a written 'do not move X' costs a rebuild to undo."""
    reading = _step(1)
    assert "*PLAN*.md" in reading and "README.md" in reading
    assert adopt.ADOPT_MD.index("## 1 ") < adopt.ADOPT_MD.index("## 2 ")


def test_repos_split_by_whether_the_project_changes_them():
    """Repos you change get branched; repos you only use must never be."""
    assert "`3rd_party/`" in adopt.ADOPT_MD
    assert "one question" in _step(2).lower()
    assert "clarity-ctl repo add workspace/" in adopt.ADOPT_MD
    assert "3rd_party/` stay off the list" in adopt.ADOPT_MD


def test_whole_directories_move_together():
    """Lifting runs/ out of a results dir silently breaks the script that reads it."""
    assert "never reach inside one" in adopt.ADOPT_MD
    assert "do not guess" in adopt.ADOPT_MD.lower()


def test_every_file_clarity_owns_is_named_as_staying(tmp_path):
    """If install starts writing a new agent file, adopt must not sweep it into src/."""
    from clarity import agents

    root = make_repo(tmp_path)
    for path in agents.local_paths(root):
        assert path.name in adopt.ADOPT_MD, \
            f"{path.name} is written by install but adopt.md does not list it as clarity's"


def test_moves_are_proposed_before_anything_happens():
    assert "Then stop." in adopt.ADOPT_MD
    assert "any row can be struck" in adopt.ADOPT_MD


def test_move_costs_are_priced_not_forbidden():
    """A build tree is an artifact: moving it costs a rebuild, it does not destroy work.
    Saying 'this breaks the build' leaves a 10G checkout at the root forever."""
    assert "Cost of moving it" in adopt.ADOPT_MD
    assert "the source is untouched" in adopt.ADOPT_MD
    assert "You are pricing them" in adopt.ADOPT_MD


def test_the_things_that_carry_absolute_paths_are_all_named():
    for artifact in ("pyvenv.cfg", "CMakeCache.txt", ".uv-cache", "symlink"):
        assert artifact in adopt.ADOPT_MD


def test_renames_keep_history():
    assert "git mv" in adopt.ADOPT_MD


def test_a_nested_checkout_moves_whole():
    """Its .git travels with it. Opening it or merging it up is out of scope."""
    assert "moves as a whole" in adopt.ADOPT_MD


def test_an_already_tidy_project_is_a_valid_outcome():
    assert "already tidy is a valid outcome" in adopt.ADOPT_MD


def test_objectives_are_asked_for_not_inferred():
    first = _step(0)
    assert "Ask the human; do not infer it from the code" in first
