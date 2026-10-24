"""epoch spawn at its edges: which repos a subepoch gets, what is left when it fails,
numbering across parents, and the parent it needs to start and reopen.
Run: .venv/bin/python -m pytest -q tests/test_spawn.py"""

import json

import pytest

from clarity import ClarityError, Project


def _active(project, name, **kwargs):
    item = project.add(name)
    started, _ = project.start(item.id, **kwargs)
    return started


def _spawn(monkeypatch, root, *argv):
    from clarity.cli import main
    monkeypatch.chdir(root)
    return main(["epoch", "spawn", *argv])


def _kids(project, parent):
    return [c.id for c in Project.find(project.root).children_of(parent.id)]


# ---- --repo on the command line ----

def test_repo_all_is_every_repo_the_parent_has(workspace, monkeypatch):
    parent = _active(workspace, "parent", repos=["workspace/agent"])

    assert _spawn(monkeypatch, workspace.root, str(parent.id), "part", "--repo", "all") == 0

    child = Project.find(workspace.root).worklog.by_id(f"{parent.id}.1")
    assert child.repos == ["workspace/agent"]  # the parent's, not the project's two


def test_repo_none_branches_nothing(workspace, monkeypatch):
    parent = _active(workspace, "parent", repos=["workspace/agent"])

    assert _spawn(monkeypatch, workspace.root, str(parent.id), "notes only",
                  "--repo", "none") == 0

    child = Project.find(workspace.root).worklog.by_id(f"{parent.id}.1")
    assert child.repos == [] and child.branch is None and child.bases is None


def test_repo_all_cannot_be_mixed_with_names(workspace, monkeypatch):
    parent = _active(workspace, "parent", repos=["workspace/agent"])

    assert _spawn(monkeypatch, workspace.root, str(parent.id), "part",
                  "--repo", "all", "--repo", "workspace/agent") == 2
    assert _kids(workspace, parent) == []


def test_a_repo_outside_the_parent_is_refused_and_leaves_nothing(workspace, monkeypatch, capsys):
    parent = _active(workspace, "parent", repos=["workspace/agent"])

    assert _spawn(monkeypatch, workspace.root, str(parent.id), "part",
                  "--repo", "workspace/harness") == 4
    assert f"epoch add-repo {parent.id}" in capsys.readouterr().err
    assert _kids(workspace, parent) == []


def test_repo_narrows_to_some_of_the_parents(workspace):
    parent = _active(workspace, "parent", repos=["workspace/agent", "workspace/harness"])

    child, _ = workspace.spawn(parent.id, "harness only", repos=["workspace/harness"])

    assert child.repos == ["workspace/harness"]
    assert child.bases == {"workspace/harness": parent.branch}
    wt = workspace.root / child.folder / "wt"
    assert (wt / "harness").is_dir() and not (wt / "agent").exists()


def test_a_parent_with_no_repos_spawns_subepochs_with_none(workspace):
    parent = _active(workspace, "planning", no_repos=True)

    child, _ = workspace.spawn(parent.id, "more planning")

    assert child.repos == [] and child.branch is None and child.bases is None


def test_naming_a_repo_under_a_root_branching_parent_is_refused(project):
    parent = _active(project, "parent")

    with pytest.raises(ClarityError, match="branches the project root"):
        project.spawn(parent.id, "part", repos=["anything"])


# ---- what spawn leaves behind ----

def test_a_spawn_that_fails_to_start_leaves_no_subepoch(project, monkeypatch):
    parent = _active(project, "parent")

    def broken(*args, **kwargs):
        raise ClarityError("git said no", code=1)

    monkeypatch.setattr(Project, "_attach_all", broken)
    with pytest.raises(ClarityError, match="git said no"):
        project.spawn(parent.id, "doomed")
    monkeypatch.undo()

    assert _kids(project, parent) == []
    again, _ = project.spawn(parent.id, "second try")
    assert again.id == f"{parent.id}.1"  # the failed one's number is free again


def test_unknown_type_is_refused_before_anything_is_written(project):
    parent = _active(project, "parent")

    with pytest.raises(ClarityError, match="unknown type"):
        project.spawn(parent.id, "part", type_="nonsense")
    assert _kids(project, parent) == []


def test_brief_type_and_page_title(project, tmp_path):
    parent = _active(project, "parent")
    brief = tmp_path / "brief.md"
    brief.write_text("Only the lexer.\n")

    child, _ = project.spawn(parent.id, "probe the lexer", type_="experiment",
                             brief=str(brief))

    stored = Project.find(project.root).worklog.by_id(child.id)
    assert stored.brief == "Only the lexer." and stored.type == "experiment"
    page = (project.root / child.folder / "EPOCH.md").read_text()
    assert f"# {child.code} · probe the lexer" in page


def test_an_experiment_subepoch_gets_no_unmerged_warning(project, commit):
    parent = _active(project, "parent")
    child, _ = project.spawn(parent.id, "probe", type_="experiment")
    commit(project.root / child.folder / "wt" / project.root.name, "probe.txt")

    assert project.unmerged(child.id) == []


def test_json_output(project, monkeypatch, capsys):
    parent = _active(project, "parent")
    capsys.readouterr()

    assert _spawn(monkeypatch, project.root, str(parent.id), "in json", "--json") == 0

    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["command"] == "epoch.spawn"
    assert out["data"]["id"] == f"{parent.id}.1"
    assert out["data"]["parent"] == parent.id
    assert out["data"]["status"] == "active"


# ---- numbering ----

def test_each_parent_counts_its_own(project):
    first = _active(project, "first parent")
    second = _active(project, "second parent")

    a, _ = project.spawn(first.id, "a")
    b, _ = project.spawn(second.id, "b")
    c, _ = project.spawn(first.id, "c")

    assert (a.id, b.id, c.id) == (f"{first.id}.1", f"{second.id}.1", f"{first.id}.2")


# ---- the parent it needs ----

def test_spawn_under_a_closed_parent_says_reopen(project):
    parent = _active(project, "parent")
    project.close(parent.id, "done")

    with pytest.raises(ClarityError, match=f"epoch reopen {parent.id}"):
        project.spawn(parent.id, "too late")


def test_spawn_under_an_archived_parent_is_refused(project):
    parent = _active(project, "parent")
    project.close(parent.id, "done")
    project.archive()

    with pytest.raises(ClarityError, match="archived") as caught:
        Project.find(project.root).spawn(parent.id, "too late")
    assert caught.value.code == 4


def test_spawn_needs_a_real_id(project):
    with pytest.raises(ClarityError, match="not an id"):
        project.spawn("seven", "part")
    with pytest.raises(ClarityError, match="no item with id 99"):
        project.spawn(99, "part")


def test_a_subepoch_reopens_only_while_its_parent_is_active(project):
    parent = _active(project, "parent")
    child, _ = project.spawn(parent.id, "part")
    project.close(child.id, "done")
    project.close(parent.id, "done")

    with pytest.raises(ClarityError, match=f"epoch reopen {parent.id}"):
        project.start(child.id, reopen=True)

    project.start(parent.id, reopen=True)
    again, _ = project.start(child.id, reopen=True)
    assert again.id == child.id and again.branch == child.branch
    assert again.bases == {".": parent.branch}  # still merges into the parent
