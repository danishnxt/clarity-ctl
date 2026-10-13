"""What each command owes the filesystem, and what it must not touch.

The rule these all test: a generated file may cache only a pure function of inputs
clarity owns. Leases, git ahead/behind and the PLANS/ directory are not owned, so
nothing caches them — they are answered when asked.
Run: .venv/bin/python -m pytest -q
"""

from pathlib import Path

import pytest

from clarity import ClarityError
from clarity.model import STATUSES
from clarity import store
from clarity.cli import main


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


def test_a_write_renders_only_the_epoch_that_changed(project, monkeypatch):
    """The whole point: a note on one epoch must not rewrite the other nineteen."""
    for n in range(5):
        project.start(project.add(f"epoch {n}").id)

    touched = writes_during(monkeypatch, lambda: project.note(2, "only this one"))
    assert touched.count("EPOCH.md") == 1
    assert "worklog.yaml" in touched


def test_status_is_printed_never_stored(project, repo):
    """The status view mixes in leases and git, so it is printed and never stored —
    and --json shows what it prints: in-flight and up-next, not in-flight only."""
    idea = project.add("something later")
    started = project.add("in progress")
    project.start(started.id)

    assert not (repo / "STATUS.md").exists()
    assert "something later" in project.status_text(show_all=True)
    ids = {i["id"] for i in project.query("current")["items"]}
    assert ids == {idea.id, started.id}


def test_claiming_leaves_nothing_to_go_stale(project, monkeypatch):
    """A lease is a file. Nothing writes a sentence about it that could disagree."""
    item, _ = project.start(project.add("work").id)
    project.release(item.id)

    touched = writes_during(monkeypatch, lambda: project.claim(item.id))
    assert touched == []
    assert "held by" in project.status_text()  # composed live, every run


def test_an_unchanged_render_does_not_touch_the_file(project, repo):
    """Byte-identical output must not bump mtime, or watching mtimes is worthless."""
    item, _ = project.start(project.add("work").id)
    path = repo / item.folder / "EPOCH.md"

    before = path.stat().st_mtime_ns
    project.render_views()  # full rebuild, nothing changed
    assert path.stat().st_mtime_ns == before


def test_the_cli_refuses_a_bad_id_and_prints_a_claim(project, repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    # every id path goes through as_id, so a typo is exit 4 and never a traceback
    for argv in (["path", "nope"], ["show", "nope"], ["epoch", "start", "nope"]):
        assert main(argv) == 4

    # a lease carries no expiry; the CLI must not reach for one
    item, _ = project.start(project.add("work").id)
    capsys.readouterr()
    assert main(["claim", str(item.id)]) == 0
    assert "claimed by" in capsys.readouterr().out


def test_rebranching_an_attached_epoch_is_refused(project):
    """Recording a branch that isn't the one checked out is worse than refusing."""
    item = project.add("work")
    project.start(item.id)
    was = project.worklog.by_id(item.id).branch

    with pytest.raises(ClarityError) as caught:
        project.start(item.id, branch="somewhere/else")
    assert caught.value.code == 4
    assert project.worklog.by_id(item.id).branch == was  # unchanged, not silently moved


def test_every_status_is_reachable(project):
    """No status exists that no command can set — `archived` used to."""
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
