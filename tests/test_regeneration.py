"""What each command owes the filesystem, and what it must not touch.

The rule these all test: a generated file may cache only a pure function of inputs
clarity owns. Leases, git ahead/behind and the PLANS/ directory are not owned, so
nothing caches them — they are answered when asked.
Run: .venv/bin/python -m pytest -q
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clarity import ClarityError, Project  # noqa: E402
from clarity.model import STATUSES  # noqa: E402
from clarity import store  # noqa: E402
from clarity.cli import main  # noqa: E402

from test_lifecycle import make_repo  # noqa: E402


def writes_during(monkeypatch, fn) -> list[str]:
    """Every path handed to write_atomic while `fn` runs."""
    seen: list[str] = []
    real = store.write_atomic

    def spy(path, text):
        seen.append(Path(path).name)
        return real(path, text)

    monkeypatch.setattr(store, "write_atomic", spy)
    monkeypatch.setattr("clarity.project.write_atomic", spy, raising=False)
    fn()
    return seen


def test_a_write_renders_only_the_epoch_that_changed(tmp_path, monkeypatch):
    """The whole point: a note on one epoch must not rewrite the other nineteen."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    for n in range(5):
        project.start(project.add(f"epoch {n}").id)

    touched = writes_during(monkeypatch, lambda: project.note(2, "only this one"))
    assert touched.count("EPOCH.md") == 1
    assert "worklog.yaml" in touched


def test_no_status_file_is_written(tmp_path):
    """The status view mixes in leases and git, so it is printed and never stored."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    project.add("something")
    assert not (root / "STATUS.md").exists()
    assert "something" in project.status_text(show_all=True)


def test_claiming_leaves_nothing_to_go_stale(tmp_path, monkeypatch):
    """A lease is a file. Nothing writes a sentence about it that could disagree."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("work").id)
    project.release(item.id)

    touched = writes_during(monkeypatch, lambda: project.claim(item.id))
    assert touched == []
    assert "held by" in project.status_text()  # composed live, every run


def test_an_unchanged_render_does_not_touch_the_file(tmp_path):
    """Byte-identical output must not bump mtime, or watching mtimes is worthless."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("work").id)
    path = root / item.folder / "EPOCH.md"

    before = path.stat().st_mtime_ns
    project.render_views()  # full rebuild, nothing changed
    assert path.stat().st_mtime_ns == before


def test_close_records_the_epochs_own_sha(tmp_path):
    """Not the main checkout's HEAD — the work being closed is on the epoch branch."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item = project.add("work")
    project.start(item.id)

    worktree = root / project.worklog.by_id(item.id).folder / "wt" / root.name
    (worktree / "new.txt").write_text("work happened\n")
    subprocess.run(["git", "add", "-A"], cwd=worktree, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "epoch work"], cwd=worktree, check=True,
                   capture_output=True)

    branch_tip = subprocess.run(
        ["git", "rev-parse", "--short", project.worklog.by_id(item.id).branch],
        cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    main_head = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root, capture_output=True, text=True, check=True).stdout.strip()
    assert branch_tip != main_head

    closed = project.close(item.id, "done")
    assert closed.extra["end_sha"] == branch_tip


def test_a_word_where_an_id_belongs_is_refused_not_crashed(tmp_path, monkeypatch):
    """Every id path goes through as_id, so a typo is exit 4 and never a traceback."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    monkeypatch.chdir(root)
    for argv in (["path", "nope"], ["show", "nope"], ["epoch", "start", "nope"]):
        assert main(argv) == 4


def test_claim_prints_without_crashing(tmp_path, monkeypatch, capsys):
    """A lease carries no expiry; the CLI must not reach for one."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("work").id)
    monkeypatch.chdir(root)

    assert main(["claim", str(item.id)]) == 0
    assert "claimed by" in capsys.readouterr().out


def test_plans_are_listed_when_asked_not_cached(tmp_path):
    """PLANS/ is a directory anyone can drop a file into — no command can know."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("work").id)
    folder = root / item.folder

    (folder / "PLANS" / "late.md").write_text("# dropped in by hand\n")
    assert project.query("item", str(item.id))["plans"] == ["late.md"]
    assert "late.md" not in (folder / "EPOCH.md").read_text()


def test_status_json_shows_what_status_prints(tmp_path):
    """The human sees in-flight and up-next; --json used to return in-flight only."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    idea = project.add("something later")
    started = project.add("in progress")
    project.start(started.id)

    ids = {i["id"] for i in project.query("current")["items"]}
    assert ids == {idea.id, started.id}


def test_rebranching_an_attached_epoch_is_refused(tmp_path):
    """Recording a branch that isn't the one checked out is worse than refusing."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item = project.add("work")
    project.start(item.id)
    was = project.worklog.by_id(item.id).branch

    with pytest.raises(ClarityError) as caught:
        project.start(item.id, branch="somewhere/else")
    assert caught.value.code == 4
    assert project.worklog.by_id(item.id).branch == was  # unchanged, not silently moved


def test_every_status_is_reachable(tmp_path):
    """No status exists that no command can set — `archived` used to."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)

    reached = {project.add("an idea").status}
    started = project.add("active one")
    reached.add(project.start(started.id)[0].status)
    done = project.add("done one")
    project.start(done.id)
    reached.add(project.close(done.id, "shipped").status)
    dropped = project.add("dropped one")
    project.start(dropped.id)
    reached.add(project.close(dropped.id, "gave up", dropped=True).status)

    assert reached == set(STATUSES)
