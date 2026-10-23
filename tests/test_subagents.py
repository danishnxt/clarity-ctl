"""Parent and child epochs: placement, the close guard, the roll-up, and the display.
Run: .venv/bin/python -m pytest -q tests/test_subagents.py"""

import pytest

from clarity import ClarityError, Project
from clarity.model import HANDOFF


def _active(project, name):
    item = project.add(name)
    started, _ = project.start(item.id)
    return started


def _child(project, parent, name):
    item = project.add(name)
    started, _ = project.start(item.id, parent=parent.id)
    return started


def test_child_folder_goes_under_subagents(project):
    parent = _active(project, "big job")
    child = _child(project, parent, "fan out one")

    assert child.folder.startswith("EPOCHS/subagents/")
    assert (project.root / child.folder).is_dir()
    assert not (project.root / parent.folder / "subagents").exists()


def test_parent_must_be_active(project):
    idea = project.add("not started yet")
    child = project.add("would be a child")

    with pytest.raises(ClarityError, match="start it first"):
        project.start(child.id, parent=idea.id)


def test_epochs_nest_one_level_only(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "child")
    grandchild = project.add("grandchild")

    with pytest.raises(ClarityError, match="one level only"):
        project.start(grandchild.id, parent=child.id)


def test_parent_cannot_be_itself(project):
    parent = _active(project, "self")
    with pytest.raises(ClarityError, match="own parent"):
        project._check_parent(parent, parent.id)


def test_close_parent_refused_while_child_runs(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "still going")

    with pytest.raises(ClarityError, match="subagents still running"):
        project.close(parent.id, "shipped")

    project.close(child.id, "done")
    closed = project.close(parent.id, "shipped")
    assert closed.status == "done"


def test_roll_up_carries_status_outcome_and_handoff(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "worker")
    project.note(child.id, f"{HANDOFF} parser done, tests not written")
    project.note(child.id, "tried a regex first, slower")

    data = Project.find(project.root).query("item", str(parent.id))

    [roll] = data["children"]
    assert roll["id"] == child.id
    assert roll["status"] == "active"
    assert roll["handoff"] == "parser done, tests not written"
    assert roll["lease"]["owner"]


def test_children_still_counted_after_archive(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "finished early")
    project.close(child.id, "done")
    project.archive()

    assert [c.id for c in project.children_of(parent.id)] == [child.id]
    roll = Project.find(project.root).query("item", str(parent.id))
    assert roll["children"][0]["status"] == "done"


def test_active_parent_lists_subagents_one_line_each(project):
    parent = _active(project, "parent")
    first = _child(project, parent, "worker one")
    second = _child(project, parent, "worker two")
    project.close(second.id, "done")
    fresh = Project.find(project.root)

    text = fresh.status_text()

    assert f"↳ #{first.id} ▸ worker one" in text
    assert f"↳ #{second.id} ✓ worker two" in text
    assert "subagents:" not in text  # a list, not a count, while the parent runs


def test_closed_parent_shows_only_the_count(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "finished worker")
    project.close(child.id, "done")
    project.close(parent.id, "shipped")

    text = Project.find(project.root).status_text(show_all=True)

    assert "1 subagent: 0 active, 1 closed" in text
    assert "finished worker" not in text


def test_children_flag_lists_them_as_rows(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "row of its own")

    expanded = Project.find(project.root).status_text(children=True)

    assert f"subagent of {parent.id}" in expanded
    assert "↳" not in expanded  # rows already list them; the parent shows the count
    assert [c.id for c in Project.find(project.root).children_by_parent()[parent.id]] == [child.id]


def test_json_status_is_never_collapsed(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "in the json")

    listed = Project.find(project.root).query("current")["items"]
    ids = {i["id"]: i for i in listed}

    assert ids[child.id]["parent"] == parent.id
    assert parent.id in ids


def test_show_text_has_subagents_section(project):
    from clarity import render

    parent = _active(project, "parent")
    child = _child(project, parent, "worker one")
    project.note(child.id, f"{HANDOFF} waiting on the API key")

    data = Project.find(project.root).query("item", str(parent.id))
    text = render.item_text(data)

    assert "Subagents (1)" in text
    assert "worker one" in text
    assert "handoff: waiting on the API key" in text


def test_child_handoff_reads_latest_only(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "x")
    project.note(child.id, f"{HANDOFF} first")
    project.note(child.id, "some detail")
    project.note(child.id, f"{HANDOFF} second")

    assert Project.find(project.root).worklog.by_id(child.id).handoff == "second"


def test_archive_keeps_parent_child_link(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "kept")
    project.close(child.id, "done")
    project.close(parent.id, "done")
    project.archive()

    fresh = Project.find(project.root)
    _, name = fresh.worklog.lookup(child.id)
    assert name and name.endswith(".yaml")  # archived, not live
    assert fresh.worklog.lookup(child.id)[0].parent == parent.id
