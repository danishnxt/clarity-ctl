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
