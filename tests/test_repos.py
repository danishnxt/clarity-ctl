"""A workspace of several repos: the root is a plain folder, the code is in checkouts."""

import json

import pytest

from clarity import ClarityError, Project
from clarity import gitops
from clarity.cli import main
from clarity.store import load_yaml


def test_listed_repos_each_get_the_branch_and_the_root_is_left_alone(workspace, ws_root,
                                                                      commit):
    root = ws_root
    item, _ = workspace.start(workspace.add("teach the agent to bisect").id)
    folder = root / item.folder

    assert item.repos == ["workspace/agent", "workspace/harness"]
    for name in ("agent", "harness"):
        wt = folder / "wt" / name
        assert wt.is_dir() and gitops.current_branch(wt) == item.branch
    assert not gitops.branch_exists(root / "3rd_party" / "duckdb", item.branch)
    assert "workspace/agent" in (folder / "EPOCH.md").read_text()

    # close: worktrees go, branches stay, and each repo's end commit is recorded
    commit(folder / "wt" / "agent", "new.py")
    closed = Project.find(root).close(item.id, outcome="bisects")
    assert not (folder / "wt" / "agent").exists()
    assert gitops.branch_exists(root / "workspace" / "agent", item.branch)
    shas = closed.extra["end_shas"]
    assert shas["workspace/agent"] == gitops.branch_sha(root / "workspace" / "agent", item.branch)
    assert set(shas) == {"workspace/agent", "workspace/harness"}


def test_a_start_that_fails_partway_leaves_nothing_behind(workspace, ws_root, git):
    root = ws_root
    # a branch named plain `epoch` makes `epoch/NNN-...` impossible in that repo
    git(["branch", "epoch"], root / "workspace" / "harness")

    item = workspace.add("half a start")
    with pytest.raises(ClarityError):
        workspace.start(item.id)

    after = Project.find(root).worklog.by_id(item.id)
    assert after.status == "idea" and after.branch is None and after.repos is None
    branch = f"epoch/{item.id:03d}-{item.slug}"
    assert not gitops.branch_exists(root / "workspace" / "agent", branch)
    assert not list((root / "EPOCHS").glob("*/wt/agent"))


def test_refresh_catches_up_every_repo_and_says_what_came_in(workspace, ws_root, commit,
                                                            monkeypatch, capsys):
    root = ws_root
    item, _ = workspace.start(workspace.add("x").id)

    commit(root / "workspace" / "agent", "later.py", "later")
    assert "behind main" in " ".join(Project.find(root).stale_map()[item.id])

    # --json names what merged and what was already current, repo by repo
    monkeypatch.chdir(root)
    capsys.readouterr()
    assert main(["epoch", "refresh", str(item.id), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["merged"] == [{"repo": "workspace/agent", "base": "main", "commits": 1}]
    assert data["up_to_date"] == [{"repo": "workspace/harness", "base": "main"}]
    assert (root / item.folder / "wt" / "agent" / "later.py").exists()

    for name in ("agent", "harness"):
        commit(root / "workspace" / name, "again.py", "again")
    _, report = Project.find(root).refresh(item.id)
    assert [m["repo"] for m in report["merged"]] == ["workspace/agent", "workspace/harness"]
    for name in ("agent", "harness"):
        assert (root / item.folder / "wt" / name / "again.py").exists()


def test_repo_add_refuses_what_it_cannot_branch(ws_root, tmp_path, new_repo):
    root = ws_root
    (root / "notes").mkdir()
    new_repo(tmp_path / "elsewhere")
    new_repo(root / "3rd_party" / "agent")  # same folder name as workspace/agent
    project = Project.find(root)
    project.repo_add(str(root / "workspace" / "agent"))

    for bad, says in ((root / "notes", "not a git repo"),
                      (tmp_path / "elsewhere", "outside this project"),
                      (root, "project root"),
                      (root / "3rd_party" / "agent", "also called agent")):
        with pytest.raises(ClarityError) as err:
            project.repo_add(str(bad))
        assert err.value.code == 4 and says in str(err.value)

    with pytest.raises(ClarityError):
        project.repo_remove(str(root / "workspace" / "harness"))  # never listed
    assert project.repo_remove(str(root / "workspace" / "agent")) == []


def test_a_single_repo_project_has_no_repo_list(project, repo):
    item, _ = project.start(project.add("x").id)
    assert item.repos is None
    assert "repos" not in load_yaml(repo / "worklog.yaml")
    assert (repo / item.folder / "wt" / "proj").is_dir()

    # and so nothing to pick from
    with pytest.raises(ClarityError) as err:
        project.start(project.add("y").id, repos=["proj"])
    assert "no repos listed" in str(err.value)


def test_reopen_after_rename_finds_the_branch_it_had(project, repo):
    """The slug follows the name; the branch must not, or a reopen makes a new one."""
    item, _ = project.start(project.add("cache warmup").id)
    branch = item.branch
    Project.find(repo).close(item.id, outcome="done")
    Project.find(repo).rename(item.id, "cache warmup and eviction")

    reopened, _ = Project.find(repo).start(item.id, reopen=True)
    assert reopened.branch == branch
    assert gitops.current_branch(repo / reopened.folder / "wt" / "proj") == branch


def test_repo_picks_which_repos_an_epoch_branches(workspace, ws_root):
    root = ws_root
    item, _ = workspace.start(workspace.add("x").id, repos=["harness"])
    assert item.repos == ["workspace/harness"]
    assert (root / item.folder / "wt" / "harness").is_dir()
    assert not (root / item.folder / "wt" / "agent").exists()
    assert not gitops.branch_exists(root / "workspace" / "agent", item.branch)

    # mid-flight: the same branch in the new repo, the old worktree untouched
    item, added, _ = Project.find(root).add_repos(item.id, ["workspace/agent"])
    assert added == ["workspace/agent"]
    assert item.repos == ["workspace/harness", "workspace/agent"]  # in the order added
    assert gitops.current_branch(root / item.folder / "wt" / "agent") == item.branch
    assert Project.find(root).add_repos(item.id, ["agent"])[1] == []  # already there

    closed = Project.find(root).close(item.id, outcome="done")
    assert set(closed.extra["end_shas"]) == {"workspace/agent", "workspace/harness"}


def test_repo_refuses_what_it_cannot_pin_down(ws_root, new_repo):
    root = ws_root
    new_repo(root / "workspace" / "agent-tools")
    project = Project.find(root)
    for name in ("agent", "agent-tools", "harness"):
        project.repo_add(str(root / "workspace" / name))

    assert project.pick_repos(["agent"]) == ["workspace/agent"]
    assert project.pick_repos(["workspace/harness/"]) == ["workspace/harness"]
    for bad, says in ((["ag"], "not a listed repo"),
                      (["harnss"], "did you mean harness"),
                      (["duckdb"], "not a listed repo")):
        with pytest.raises(ClarityError) as err:
            project.pick_repos(bad)
        assert err.value.code == 4 and says in str(err.value)

    item = project.add("x")
    with pytest.raises(ClarityError):
        project.start(item.id, repos=["nope"])
    after = Project.find(root).worklog.by_id(item.id)
    assert after.status == "idea" and after.repos is None

    # once `agent` leaves the list, `--repo agent` must not quietly mean agent-tools
    project.repo_remove(str(root / "workspace" / "agent"))
    with pytest.raises(ClarityError) as err:
        project.pick_repos(["agent"])
    assert "not a listed repo" in str(err.value) and "agent-tools" in str(err.value)


def test_a_repo_name_means_the_same_from_any_directory(workspace, ws_root, monkeypatch):
    root, project = ws_root, workspace
    monkeypatch.chdir(root / "EPOCHS")
    assert project.pick_repos(["workspace/agent"]) == ["workspace/agent"]
    assert project.repo_remove("harness") == ["workspace/agent"]
    assert project.repo_add("workspace/harness") == ["workspace/agent", "workspace/harness"]
    monkeypatch.chdir(root / "workspace")
    assert project.repo_remove("workspace/agent") == ["workspace/harness"]
    assert project.repo_add("agent") == ["workspace/harness", "workspace/agent"]


def test_start_does_one_job(workspace, ws_root):
    """start begins an epoch; adding a repo mid-flight is add-repo, and reopen takes
    back the repos the epoch had."""
    root = ws_root
    item, _ = workspace.start(workspace.add("x").id, repos=["agent"])

    for kwargs, says in (({}, "add-repo"), ({"repos": ["harness"]}, "add-repo")):
        with pytest.raises(ClarityError) as err:
            Project.find(root).start(item.id, **kwargs)
        assert err.value.code == 4 and says in str(err.value)

    Project.find(root).close(item.id, "done")
    with pytest.raises(ClarityError) as err:
        Project.find(root).start(item.id, reopen=True, repos=["harness"])
    assert "add-repo" in str(err.value)
    reopened, _ = Project.find(root).start(item.id, reopen=True)
    assert reopened.repos == ["workspace/agent"]


def test_drop_repo_keeps_the_branch_and_refuses_what_would_lose_work(workspace, ws_root):
    root = ws_root
    item, _ = workspace.start(workspace.add("x").id)
    wt = root / item.folder / "wt"

    (wt / "harness" / "wip.py").write_text("w = 1\n")
    with pytest.raises(ClarityError) as err:
        Project.find(root).drop_repo(item.id, "harness")
    assert "uncommitted" in str(err.value)
    (wt / "harness" / "wip.py").unlink()

    with pytest.raises(ClarityError) as err:
        Project.find(root).drop_repo(item.id, "duckdb")
    assert "not one of epoch" in str(err.value)

    item, dropped = Project.find(root).drop_repo(item.id, "harness")
    assert dropped == "workspace/harness" and item.repos == ["workspace/agent"]
    assert not (wt / "harness").exists()
    assert gitops.branch_exists(root / "workspace" / "harness", item.branch)
    assert "dropped workspace/harness" in item.notes[-1].text
    assert item.bases == {"workspace/agent": "main"}

    with pytest.raises(ClarityError) as err:
        Project.find(root).drop_repo(item.id, "agent")
    assert "only repo" in str(err.value)


def test_refresh_base_can_be_set_for_one_repo(workspace, ws_root, git):
    root = ws_root
    item, _ = workspace.start(workspace.add("x").id)
    assert item.bases == {"workspace/agent": "main", "workspace/harness": "main"}

    git(["branch", "release"], root / "workspace" / "harness")
    Project.find(root).refresh(item.id, base="release", repos=["harness"])
    after = Project.find(root).worklog.by_id(item.id)
    assert after.bases == {"workspace/agent": "main", "workspace/harness": "release"}
    with pytest.raises(ClarityError) as err:
        Project.find(root).refresh(item.id, base="release")  # agent has no release
    assert "no branch release in workspace/agent" in str(err.value)


def test_show_item_reports_each_repos_git_state(workspace, ws_root, commit):
    root = ws_root
    item, _ = workspace.start(workspace.add("x").id)
    commit(root / "workspace" / "agent", msg="later")
    (root / item.folder / "wt" / "harness" / "wip.py").write_text("w = 1\n")

    state = {g["repo"]: g for g in Project.find(root).query("item", str(item.id))["git"]}
    agent, harness = state["workspace/agent"], state["workspace/harness"]
    assert agent["base"] == "main" and agent["behind"] == 1 and agent["dirty"] == 0
    assert agent["worktree"].endswith("wt/agent") and not agent["shared"]
    assert harness["dirty"] == 1 and harness["checkout"] == "main"
