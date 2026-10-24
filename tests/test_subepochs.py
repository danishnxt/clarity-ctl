"""Subepochs: ids, placement, branching from the parent, the close guard and
warnings, the roll-up, and the display.
Run: .venv/bin/python -m pytest -q tests/test_subepochs.py"""

import pytest

from clarity import ClarityError, Project
from clarity.model import HANDOFF


def _active(project, name):
    item = project.add(name)
    started, _ = project.start(item.id)
    return started


def _child(project, parent, name):
    item, _ = project.spawn(parent.id, name)
    return item


def test_subepochs_are_kept_together_under_their_parent(project):
    parent = _active(project, "big job")
    one = _child(project, parent, "fan out one")
    two = _child(project, parent, "fan out two")

    home = f"EPOCHS/subepochs/{parent.folder.split('/')[-1]}/"
    assert one.folder.startswith(home) and two.folder.startswith(home)
    assert (project.root / one.folder).is_dir()


def test_a_child_lease_and_worktree_are_gitignored(project, git):
    parent = _active(project, "parent")
    child = _child(project, parent, "ignored bits")

    ignored = (project.root / ".gitignore").read_text()
    assert "EPOCHS/subepochs/*/*/wt/" in ignored and "EPOCHS/subepochs/*/*/.lease" in ignored
    lease_file = f"{child.folder}/.lease"
    assert git(["check-ignore", lease_file], project.root) == lease_file


def test_parent_must_be_active(project):
    idea = project.add("not started yet")

    with pytest.raises(ClarityError, match="epoch start"):
        project.spawn(idea.id, "would be a part")
    assert [i.id for i in Project.find(project.root).worklog.items] == [idea.id]


def test_epochs_nest_one_level_only(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "child")

    with pytest.raises(ClarityError, match="nest one level only"):
        project.spawn(child.id, "grandchild")


def test_close_parent_refused_while_child_runs(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "still going")

    with pytest.raises(ClarityError, match="subepochs still active"):
        project.close(parent.id, "shipped")

    project.close(child.id, "done")
    closed = project.close(parent.id, "shipped")
    assert closed.status == "done"


def test_roll_up_carries_status_outcome_and_handoff(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "worker")
    project.claim(child.id, as_name="worker-agent")
    project.note(child.id, f"{HANDOFF} parser done, tests not written")
    project.note(child.id, "tried a regex first, slower")

    data = Project.find(project.root).query("item", str(parent.id))

    [roll] = data["children"]
    assert roll["id"] == child.id
    assert roll["status"] == "active"
    assert roll["handoff"] == "parser done, tests not written"
    assert roll["lease"]["owner"] == "worker-agent"


def test_children_still_counted_after_archive(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "finished early")
    project.close(child.id, "done")
    project.archive()

    assert [c.id for c in project.children_of(parent.id)] == [child.id]
    roll = Project.find(project.root).query("item", str(parent.id))
    assert roll["children"][0]["status"] == "done"


def test_active_parent_lists_subepochs_one_line_each(project):
    parent = _active(project, "parent")
    first = _child(project, parent, "worker one")
    second = _child(project, parent, "worker two")
    project.close(second.id, "done")
    fresh = Project.find(project.root)

    text = fresh.status_text()

    assert f"↳ #{first.id} ▸ worker one" in text
    assert f"↳ #{second.id} ✓ worker two" in text
    assert "subepoch:" not in text and "subepochs:" not in text  # a list, not a count, while they run


def test_closed_parent_shows_only_the_count(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "finished worker")
    project.close(child.id, "done")
    project.close(parent.id, "shipped")

    text = Project.find(project.root).status_text(show_all=True)

    assert "1 subepoch: 0 active, 1 closed" in text
    assert "finished worker" not in text


def test_children_flag_lists_them_as_rows(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "row of its own")

    expanded = Project.find(project.root).status_text(children=True)

    assert f"subepoch of {parent.id}" in expanded
    assert "↳" not in expanded  # rows already list them; the parent shows the count
    assert [c.id for c in Project.find(project.root).children_by_parent()[parent.id]] == [child.id]


def test_json_status_is_never_collapsed(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "in the json")

    listed = Project.find(project.root).query("current")["items"]
    ids = {i["id"]: i for i in listed}

    assert ids[child.id]["parent"] == parent.id
    assert parent.id in ids


def test_show_text_has_subepochs_section(project):
    from clarity import render

    parent = _active(project, "parent")
    child = _child(project, parent, "worker one")
    project.note(child.id, f"{HANDOFF} waiting on the API key")

    data = Project.find(project.root).query("item", str(parent.id))
    text = render.item_text(data)

    assert "Subepochs (1)" in text
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


def test_show_text_gives_a_closed_child_its_outcome(project):
    from clarity import render

    parent = _active(project, "parent")
    child = _child(project, parent, "finished worker")
    project.note(child.id, f"{HANDOFF} almost there")
    project.close(child.id, "statements ported")

    text = render.item_text(Project.find(project.root).query("item", str(parent.id)))

    assert "outcome: statements ported" in text
    assert "handoff: almost there" not in text  # the outcome supersedes it


# ---- ids: numbered under the parent ----

def test_subepochs_are_numbered_under_their_parent(project):
    parent = _active(project, "parent")
    one = _child(project, parent, "one")
    two = _child(project, parent, "two")
    later = project.add("a top-level idea")

    assert (one.id, two.id) == (f"{parent.id}.1", f"{parent.id}.2")
    assert later.id == parent.id + 1  # subepochs use up no top-level numbers
    assert one.parent == parent.id
    assert Project.find(project.root).worklog.by_id(f"{parent.id}.1").name == "one"


def test_a_subepoch_number_is_never_handed_out_twice(project):
    parent = _active(project, "parent")
    first = _child(project, parent, "first")
    project.close(first.id, "done")
    project.archive()

    again = _child(project, parent, "second")
    assert again.id == f"{parent.id}.2"


def test_subepoch_ids_sort_as_numbers(project):
    parent = _active(project, "parent")
    for n in range(10):
        _child(project, parent, f"part {n}")

    ids = [c.id for c in Project.find(project.root).children_of(parent.id)]
    assert ids[-2:] == [f"{parent.id}.9", f"{parent.id}.10"]


def test_dotted_ids_survive_a_reload(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "kept as text")

    fresh = Project.find(project.root)
    assert fresh.worklog.by_id(child.id).id == child.id
    assert "001.1_" in child.folder  # folder and branch carry the padded form
    assert child.branch.startswith("epoch/001.1-")


# ---- branches: cut from the parent, merged back into it ----

def _wt(project, item):
    return project.root / item.folder / "wt" / project.root.name


def test_a_subepoch_branches_from_its_parent(project, commit):
    parent = _active(project, "parent")
    commit(_wt(project, parent), "parent_work.txt")

    child = _child(project, parent, "part")

    assert (_wt(project, child) / "parent_work.txt").exists()  # not cut from main
    assert child.bases == {".": parent.branch}


def test_closing_an_unmerged_subepoch_names_the_merge_into_its_parent(project, commit, git):
    parent = _active(project, "parent")
    child = _child(project, parent, "part")
    commit(_wt(project, child), "part.txt")

    [line] = project.unmerged(child.id)
    assert f"not in {parent.branch}" in line
    assert f"merge it into epoch {parent.id}" in line
    assert f"merge {child.branch}" in line

    git(["merge", "-q", child.branch], _wt(project, parent))
    assert project.unmerged(child.id) == []


def test_a_parent_warns_when_a_done_subepoch_never_reached_it(project, commit):
    parent = _active(project, "parent")
    done = _child(project, parent, "done part")
    dropped = _child(project, parent, "dropped part")
    for item in (done, dropped):
        commit(_wt(project, item), f"{item.code}.txt")
    project.close(done.id, "finished")
    project.close(dropped.id, "gave up", dropped=True)

    lines = project.unmerged(parent.id)

    assert any(f"subepoch {done.id}'s" in w and "never reached" in w for w in lines)
    assert not any(f"subepoch {dropped.id}'s" in w for w in lines)  # dropped stays unmerged


def test_refresh_brings_in_what_a_sibling_merged(project, commit, git):
    parent = _active(project, "parent")
    first = _child(project, parent, "first")
    second = _child(project, parent, "second")
    commit(_wt(project, first), "first.txt")
    git(["merge", "-q", first.branch], _wt(project, parent))

    _, report = project.refresh(second.id)

    assert report["merged"][0]["base"] == parent.branch
    assert (_wt(project, second) / "first.txt").exists()


def test_spawn_leaves_the_lease_free(project):
    parent = _active(project, "parent")
    child = _child(project, parent, "for another agent")

    assert child.id not in Project.find(project.root).leases()
    assert parent.id in Project.find(project.root).leases()


# ---- repos: the parent's, or some of them ----

def test_a_subepoch_takes_its_parents_repos(workspace):
    parent = workspace.add("parent")
    workspace.start(parent.id, repos=["workspace/agent"])

    child, _ = workspace.spawn(parent.id, "part")

    assert child.repos == ["workspace/agent"]
    assert child.bases == {"workspace/agent": f"epoch/{parent.code}-parent"}


def test_a_subepoch_cannot_branch_a_repo_its_parent_does_not(workspace):
    parent = workspace.add("parent")
    workspace.start(parent.id, repos=["workspace/agent"])

    with pytest.raises(ClarityError, match="add it there first"):
        workspace.spawn(parent.id, "part", repos=["workspace/harness"])
    assert [c.id for c in Project.find(workspace.root).children_of(parent.id)] == []


# ---- the CLI takes dotted ids everywhere ----

def test_the_cli_reads_dotted_ids(project, monkeypatch, capsys):
    from clarity.cli import main

    parent = _active(project, "parent")
    monkeypatch.chdir(project.root)

    assert main(["epoch", "spawn", str(parent.id), "cli part", "--brief", "only this"]) == 0
    child_id = f"{parent.id}.1"
    assert f"claim {child_id} --as" in capsys.readouterr().out
    assert main(["claim", child_id, "--as", "part-agent"]) == 0
    assert main(["note", child_id, "HANDOFF: half done"]) == 0
    assert main(["show", child_id, "--json"]) == 0
    assert '"id": "1.1"' in capsys.readouterr().out
    assert main(["epoch", "close", child_id, "ported"]) == 0
    assert Project.find(project.root).worklog.by_id(child_id).status == "done"
