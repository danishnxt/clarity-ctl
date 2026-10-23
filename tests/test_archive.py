"""archive moves closed epochs out of worklog.yaml; they stay readable and unchangeable.
Run: .venv/bin/python -m pytest -q tests/test_archive.py"""

import pytest
import yaml

from clarity import ClarityError, Project
from clarity.store import ARCHIVE, Worklog


def _drop(project, name):
    """An idea, dropped: a closed item that needs no git work to close."""
    item = project.add(name)
    return project.close(item.id, outcome="not doing it", dropped=True)


def test_archive_moves_closed_and_keeps_open(project):
    closed = _drop(project, "old thing")
    open_idea = project.add("still open")

    written = project.archive()

    assert written and written[0][1] == 1
    live = Project.find(project.root).worklog
    assert [i.id for i in live.items] == [open_idea.id]
    archive_file = project.root / ARCHIVE / written[0][0]
    stored = yaml.safe_load(archive_file.read_text())["items"]
    assert [d["id"] for d in stored] == [closed.id]


def test_archive_with_nothing_closed_writes_nothing(project):
    project.add("open")
    assert project.archive() == []
    assert not (project.root / ARCHIVE).exists()


def test_archived_id_is_never_reused(project):
    closed = _drop(project, "gone")
    project.archive()

    fresh = project.add("new after archive")

    assert fresh.id == closed.id + 1


def test_closing_order_survives_archive(project):
    first = _drop(project, "first closed")
    project.archive()
    second = _drop(project, "second closed")

    assert second.closed_seq > first.closed_seq


def test_show_reads_archived_item(project):
    closed = _drop(project, "readable later")
    project.archive()

    data = Project.find(project.root).query("item", str(closed.id))

    assert data["name"] == "readable later"
    assert data["archived"].startswith(f"{ARCHIVE}/")


def test_archived_item_refuses_writes(project):
    closed = _drop(project, "frozen")
    project.archive()
    reopened = Project.find(project.root)

    with pytest.raises(ClarityError, match="archived"):
        reopened.note(closed.id, "too late")
    with pytest.raises(ClarityError, match="archived"):
        reopened.rename(closed.id, "renamed")


def test_live_copy_wins_over_archived_copy(project):
    """A crash between writing the archive and saving the worklog leaves an item in
    both. The live one is current, so reads must not see the archived copy."""
    closed = _drop(project, "in both places")
    project.archive()
    live_items = [closed]
    worklog = Worklog.load(project.root / "worklog.yaml")
    worklog.items = live_items
    worklog.save()

    loaded = Worklog.load(project.root / "worklog.yaml")

    assert closed.id not in loaded.archived
    assert [i.id for i in loaded.items] == [closed.id]
