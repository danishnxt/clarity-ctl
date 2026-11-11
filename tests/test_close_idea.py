"""`epoch close` on an idea: done already, or not wanted — closed without starting it.
No folder, branch, worktree, lease or end shas; everything else reads like any close.
Run: .venv/bin/python -m pytest -q tests/test_close_idea.py"""

import json

import pytest
import yaml

from clarity import ClarityError, Project
from clarity.cli import main
from clarity.store import ARCHIVE


def _nothing_made(project, repo, git, item):
    """No folder, no epoch branch, no worktree, no lease, no end shas."""
    assert item.folder is None and item.branch is None and item.repos is None
    assert "end_sha" not in item.extra and "end_shas" not in item.extra
    assert not project.epochs_dir.exists() or not list(project.epochs_dir.glob("*"))
    assert git(["branch", "--format=%(refname:short)"], repo).split() == ["main"]
    assert project.leases() == {}


def test_closing_an_idea_makes_it_done_and_creates_nothing(project, repo, git):
    idea = project.add("already built")

    item = project.close(idea.id, "built under epoch 12")

    assert item.status == "done" and item.outcome == "built under epoch 12"
    assert item.ended and item.closed_seq == 1
    assert item.started is None and item.never_started
    _nothing_made(project, repo, git, item)
    reread = Project.find(repo).worklog.by_id(idea.id)
    assert reread.status == "done" and reread.closed_seq == 1


def test_dropping_an_idea(project, repo, git):
    idea = project.add("not wanted")
    item = project.close(idea.id, "we decided against it", dropped=True)

    assert item.status == "dropped" and item.outcome == "we decided against it"
    assert item.ended and item.closed_seq == 1
    _nothing_made(project, repo, git, item)


def test_closing_an_idea_in_a_workspace_touches_no_repo(workspace, ws_root, git):
    idea = workspace.add("done elsewhere")
    def branches():
        return {r: git(["branch", "--format=%(refname:short)"], ws_root / "workspace" / r)
                for r in ("agent", "harness")}
    before = branches()

    item = workspace.close(idea.id, "shipped in the harness")

    assert item.status == "done" and item.folder is None and item.repos is None
    assert not (ws_root / "EPOCHS").exists() or not list((ws_root / "EPOCHS").glob("*"))
    assert before == branches() and set(before.values()) == {"main"}


def test_an_idea_has_no_subepochs_and_a_closed_idea_cannot_close_again(project):
    idea = project.add("plain")
    assert project.children_of(idea.id) == []
    project.close(idea.id, "done")
    with pytest.raises(ClarityError) as err:
        project.close(idea.id, "again")
    assert err.value.code == 4 and "already done" in str(err.value)


def test_cli_closes_an_idea_and_json_says_no_repo_work_was_done(project, repo, monkeypatch,
                                                                  capsys):
    monkeypatch.chdir(repo)
    first, second = project.add("one").id, project.add("two").id
    capsys.readouterr()

    assert main(["epoch", "close", str(first), "built under epoch 3"]) == 0
    assert capsys.readouterr().out.startswith(
        f"idea {first} done without starting: built under epoch 3")

    assert main(["epoch", "close", str(second), "--drop", "not wanted", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["command"] == "epoch.close"
    assert out["data"]["status"] == "dropped" and out["data"]["repo_work"] is False
    assert "branch" not in out["data"] and "folder" not in out["data"]

    # a started epoch's close does not claim repo_work either way
    epoch, _ = project.start(project.add("real").id)
    capsys.readouterr()
    assert main(["epoch", "close", str(epoch.id), "shipped", "--json"]) == 0
    assert "repo_work" not in json.loads(capsys.readouterr().out)["data"]


def test_closing_an_idea_without_an_outcome_is_refused_off_a_terminal(project, repo,
                                                                        monkeypatch, capsys):
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    idea = project.add("quiet")
    capsys.readouterr()

    assert main(["epoch", "close", str(idea.id)]) == 4
    assert "pass it as an argument" in capsys.readouterr().err
    assert Project.find(repo).worklog.by_id(idea.id).status == "idea"


def test_status_show_and_digest_read_a_closed_idea_like_any_closed_item(
        project, repo, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    done = project.add("already built")
    project.close(done.id, "built under epoch 12")
    dropped = project.add("not wanted")
    project.close(dropped.id, "decided against", dropped=True)

    status = project.status_text(show_all=True)
    assert "already built" in status and "outcome: built under epoch 12" in status
    assert "not merged" not in status and "✅" not in status      # nothing landed, no mark

    capsys.readouterr()
    assert main(["show", str(done.id)]) == 0
    page = capsys.readouterr().out
    assert "✓ done" in page and "without starting" in page
    assert "==> Where" not in page and "built under epoch 12" in page
    assert main(["show", "closed"]) == 0 and "already built" in capsys.readouterr().out

    digest = project.state_digest()
    assert f"#{done.id} ✓ already built" in digest
    assert f"#{dropped.id} ✗ not wanted" in digest

    # a started epoch's page does not say it
    epoch, _ = project.start(project.add("real work").id)
    project.close(epoch.id, "shipped")
    assert main(["show", str(epoch.id)]) == 0
    assert "without starting" not in capsys.readouterr().out


def test_archive_moves_a_closed_idea_and_show_still_reads_it(project, repo, monkeypatch,
                                                              capsys):
    monkeypatch.chdir(repo)
    idea = project.add("already built")
    project.close(idea.id, "built under epoch 12")

    written = project.archive()

    assert written
    stored = yaml.safe_load((project.root / ARCHIVE / written[0][0]).read_text())["items"]
    assert stored[0]["id"] == idea.id and "folder" not in stored[0]
    capsys.readouterr()
    assert main(["show", str(idea.id)]) == 0
    assert "without starting" in capsys.readouterr().out


def test_reopening_a_closed_idea_makes_it_an_idea_again(project, repo, git, monkeypatch, capsys):
    monkeypatch.chdir(repo)
    idea = project.add("changed my mind")
    project.close(idea.id, "built under epoch 12")
    capsys.readouterr()

    assert main(["epoch", "reopen", str(idea.id)]) == 0
    assert f"epoch start {idea.id}" in capsys.readouterr().out

    again = Project.find(repo).worklog.by_id(idea.id)
    assert again.status == "idea" and again.outcome is None
    assert again.ended is None and again.closed_seq is None
    assert "previous outcome: built under epoch 12" in again.notes[-1].text
    _nothing_made(project, repo, git, again)

    # and it starts like any idea, then closes like any epoch
    started, _ = Project.find(repo).start(idea.id)
    assert started.status == "active" and started.folder and started.branch


def test_reopening_a_closed_idea_with_json_and_a_branch_is_refused(project, repo, monkeypatch,
                                                                    capsys):
    monkeypatch.chdir(repo)
    idea = project.add("x")
    project.close(idea.id, "done")
    capsys.readouterr()

    assert main(["epoch", "reopen", str(idea.id), "--branch", "feature/x"]) == 4
    assert "ever being started" in capsys.readouterr().err
    assert Project.find(repo).worklog.by_id(idea.id).status == "done"

    assert main(["epoch", "reopen", str(idea.id), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["command"] == "epoch.reopen" and out["data"]["status"] == "idea"


def test_start_of_a_closed_idea_still_asks_for_reopen(project):
    idea = project.add("x")
    project.close(idea.id, "done")
    with pytest.raises(ClarityError) as err:
        project.start(idea.id)
    assert err.value.code == 4 and "reopen" in str(err.value)
