"""The brief, experiments without the unmerged warning, and claim --as.
Run: .venv/bin/python -m pytest -q tests/test_brief.py"""

import pytest

from clarity import ClarityError, Project, lease, render


def test_brief_text_is_stored_and_shown(project):
    item = project.add("big refactor")
    project.start(item.id, brief="Move the parser to the new AST. Do not touch the lexer.")

    stored = Project.find(project.root).query("item", str(item.id))
    assert stored["brief"] == "Move the parser to the new AST. Do not touch the lexer."

    page = render.item_text(stored)
    assert "Brief" in page and "Do not touch the lexer." in page


def test_a_brief_too_long_to_be_a_path_is_text(project):
    """A long brief once crashed start with 'File name too long' instead of being stored."""
    item = project.add("long brief")
    brief = "Do the thing carefully. " * 20
    project.start(item.id, brief=brief)
    assert Project.find(project.root).query("item", str(item.id))["brief"] == brief


def test_brief_can_come_from_a_file(project, tmp_path):
    notes = tmp_path / "brief.md"
    notes.write_text("Goal: ship the parser.\nLimit: no new deps.\n")
    item = project.add("from a file")

    project.start(item.id, brief=str(notes))

    assert Project.find(project.root).worklog.by_id(item.id).brief == (
        "Goal: ship the parser.\nLimit: no new deps.")


def test_reopen_keeps_the_brief_unless_a_new_one_is_given(project):
    item = project.add("reopened")
    project.start(item.id, brief="first brief")
    project.close(item.id, "done")

    project.start(item.id, reopen=True)
    assert Project.find(project.root).worklog.by_id(item.id).brief == "first brief"

    project.close(item.id, "done again")
    project.start(item.id, reopen=True, brief="second brief")
    assert Project.find(project.root).worklog.by_id(item.id).brief == "second brief"


def test_experiment_gets_no_unmerged_warning(project, repo, git, commit):
    feature = project.add("a feature")
    experiment = project.add("a probe", type_="experiment")
    for item in (feature, experiment):
        started, _ = project.start(item.id)
        commit(repo / started.folder / "wt" / repo.name, f"{item.id}.txt", "work")

    assert project.unmerged(feature.id)  # a feature with unmerged commits warns
    assert project.unmerged(experiment.id) == []  # an experiment is meant to stay unmerged


def test_claim_as_names_the_holder(project):
    item = project.add("named holder")
    project.start(item.id)
    project.release(item.id)

    _, held = project.claim(item.id, as_name="epoch15-opus")

    assert held["owner"] == "epoch15-opus"
    assert Project.find(project.root).leases()[item.id]["owner"] == "epoch15-opus"


def test_release_needs_the_same_name_it_was_claimed_under(project):
    item = project.add("guarded")
    project.start(item.id)
    project.release(item.id)
    project.claim(item.id, as_name="agent-a")

    with pytest.raises(ClarityError, match="belongs to agent-a"):
        project.release(item.id, as_name="agent-b")

    project.release(item.id, as_name="agent-a")
    assert lease.read(project.folder_of(project.worklog.by_id(item.id))) is None


# ---- the repo choice on epoch start: required where the project lists repos ----

def _start(monkeypatch, root, *argv):
    from clarity.cli import main
    monkeypatch.chdir(root)
    return main(["epoch", "start", *argv])


def test_start_without_a_repo_choice_is_refused_with_the_three_answers(
        workspace, monkeypatch, capsys):
    item = workspace.add("needs a choice")

    code = _start(monkeypatch, workspace.root, str(item.id))

    err = capsys.readouterr().err
    assert code == 2
    assert "--repo <repo>" in err and "--repo all" in err and "--repo none" in err
    assert Project.find(workspace.root).worklog.by_id(item.id).status == "idea"


def test_repo_all_branches_every_listed_repo(workspace, monkeypatch):
    item = workspace.add("everything")

    assert _start(monkeypatch, workspace.root, str(item.id), "--repo", "all") == 0
    assert Project.find(workspace.root).worklog.by_id(item.id).repos == [
        "workspace/agent", "workspace/harness"]


def test_repo_none_branches_nothing(workspace, monkeypatch):
    item = workspace.add("planning")

    assert _start(monkeypatch, workspace.root, str(item.id), "--repo", "none") == 0
    assert Project.find(workspace.root).worklog.by_id(item.id).repos == []


def test_repo_all_cannot_be_mixed_with_names(workspace, monkeypatch):
    item = workspace.add("mixed")

    assert _start(monkeypatch, workspace.root, str(item.id),
                  "--repo", "all", "--repo", "workspace/agent") == 2


def test_a_project_that_branches_its_root_needs_no_choice(project, monkeypatch):
    item = project.add("single repo")

    assert _start(monkeypatch, project.root, str(item.id)) == 0
