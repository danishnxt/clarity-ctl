"""A workspace of several repos: the root is a plain folder, the code is in checkouts."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clarity import ClarityError, Project  # noqa: E402
from clarity import gitops  # noqa: E402
from clarity.store import load_yaml  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]


def git(args, cwd):
    return subprocess.run(["git", *GIT_ID, *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def make_checkout(path: Path) -> Path:
    path.mkdir(parents=True)
    git(["init", "-q", "-b", "main"], path)
    (path / "code.py").write_text("x = 1\n")
    git(["add", "-A"], path)
    git(["commit", "-qm", "init"], path)
    return path


def make_workspace(tmp_path: Path) -> Path:
    """regressBot's shape: no repo at the root, one repo we change, one we only use."""
    root = tmp_path / "ws"
    make_checkout(root / "workspace" / "agent")
    make_checkout(root / "workspace" / "harness")
    make_checkout(root / "3rd_party" / "duckdb")
    Project.create(root, name="ws")
    return root


def test_listed_repos_each_get_the_branch_and_the_root_is_left_alone(tmp_path):
    root = make_workspace(tmp_path)
    project = Project.find(root)
    project.repo_add(str(root / "workspace" / "agent"))
    project.repo_add(str(root / "workspace" / "harness"))

    item = project.add("teach the agent to bisect", status="planned")
    item, _ = project.start(item.id)
    folder = root / item.folder

    assert item.repos == ["workspace/agent", "workspace/harness"]
    for name in ("agent", "harness"):
        wt = folder / "wt" / name
        assert wt.is_dir() and gitops.current_branch(wt) == item.branch
    assert not gitops.branch_exists(root / "3rd_party" / "duckdb", item.branch)
    assert "workspace/agent" in (folder / "EPOCH.md").read_text()

    # close: worktrees go, branches stay, and each repo's end commit is recorded
    (folder / "wt" / "agent" / "new.py").write_text("y = 2\n")
    git(["add", "-A"], folder / "wt" / "agent")
    git(["commit", "-qm", "work"], folder / "wt" / "agent")
    closed = Project.find(root).close(item.id, outcome="bisects")
    assert not (folder / "wt" / "agent").exists()
    assert gitops.branch_exists(root / "workspace" / "agent", item.branch)
    shas = closed.extra["end_shas"]
    assert shas["workspace/agent"] == gitops.branch_sha(root / "workspace" / "agent", item.branch)
    assert set(shas) == {"workspace/agent", "workspace/harness"}


def test_a_start_that_fails_partway_leaves_nothing_behind(tmp_path):
    root = make_workspace(tmp_path)
    # a branch named plain `epoch` makes `epoch/NNN-...` impossible in that repo
    git(["branch", "epoch"], root / "workspace" / "harness")
    project = Project.find(root)
    project.repo_add(str(root / "workspace" / "agent"))
    project.repo_add(str(root / "workspace" / "harness"))

    item = project.add("half a start", status="planned")
    with pytest.raises(ClarityError):
        project.start(item.id)

    after = Project.find(root).worklog.by_id(item.id)
    assert after.status == "planned" and after.branch is None and after.repos is None
    branch = f"epoch/{item.id:03d}-{item.slug}"
    assert not gitops.branch_exists(root / "workspace" / "agent", branch)
    assert not (root / item.folder / "wt" / "agent").exists()


def test_refresh_catches_up_every_repo(tmp_path):
    root = make_workspace(tmp_path)
    project = Project.find(root)
    for name in ("agent", "harness"):
        project.repo_add(str(root / "workspace" / name))
    item, _ = project.start(project.add("x", status="planned").id)

    for name in ("agent", "harness"):
        repo = root / "workspace" / name
        (repo / "later.py").write_text("z = 3\n")
        git(["add", "-A"], repo)
        git(["commit", "-qm", "later"], repo)
    assert "behind main" in Project.find(root).stale_map()[item.id]

    _, message = Project.find(root).refresh(item.id)
    assert "workspace/agent" in message and "workspace/harness" in message
    for name in ("agent", "harness"):
        assert (root / item.folder / "wt" / name / "later.py").exists()


def test_repo_add_refuses_what_it_cannot_branch(tmp_path):
    root = make_workspace(tmp_path)
    (root / "notes").mkdir()
    make_checkout(tmp_path / "elsewhere")
    make_checkout(root / "3rd_party" / "agent")  # same folder name as workspace/agent
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


def test_a_single_repo_worklog_does_not_grow_a_repos_key(tmp_path):
    root = tmp_path / "proj"
    make_checkout(root)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("x", status="planned").id)
    assert item.repos is None
    assert "repos" not in load_yaml(root / "worklog.yaml")
    assert (root / item.folder / "wt" / "proj").is_dir()


def test_reopen_after_rename_finds_the_branch_it_had(tmp_path):
    """The slug follows the name; the branch must not, or a reopen makes a new one."""
    root = tmp_path / "proj"
    make_checkout(root)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("cache warmup", status="planned").id)
    branch = item.branch
    Project.find(root).close(item.id, outcome="done")
    Project.find(root).rename(item.id, "cache warmup and eviction")

    reopened, _ = Project.find(root).start(item.id, reopen=True)
    assert reopened.branch == branch
    assert gitops.current_branch(root / reopened.folder / "wt" / "proj") == branch


def test_repo_picks_which_repos_an_epoch_branches(tmp_path):
    root = make_workspace(tmp_path)
    project = Project.find(root)
    for name in ("agent", "harness"):
        project.repo_add(str(root / "workspace" / name))

    item, _ = project.start(project.add("x", status="planned").id, repos=["harness"])
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


def test_repo_refuses_what_it_cannot_pin_down(tmp_path):
    root = make_workspace(tmp_path)
    make_checkout(root / "workspace" / "agent-tools")
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

    item = project.add("x", status="planned")
    with pytest.raises(ClarityError):
        project.start(item.id, repos=["nope"])
    after = Project.find(root).worklog.by_id(item.id)
    assert after.status == "planned" and after.repos is None


def test_repo_never_picks_by_prefix(tmp_path):
    """Once `agent` leaves the list, `--repo agent` must not quietly mean agent-tools."""
    root = make_workspace(tmp_path)
    make_checkout(root / "workspace" / "agent-tools")
    project = Project.find(root)
    for name in ("agent", "agent-tools"):
        project.repo_add(str(root / "workspace" / name))
    project.repo_remove(str(root / "workspace" / "agent"))

    with pytest.raises(ClarityError) as err:
        project.pick_repos(["agent"])
    assert "not a listed repo" in str(err.value) and "agent-tools" in str(err.value)


def test_a_repo_name_means_the_same_from_any_directory(tmp_path, monkeypatch):
    root = make_workspace(tmp_path)
    project = Project.find(root)
    for name in ("agent", "harness"):
        project.repo_add(str(root / "workspace" / name))

    monkeypatch.chdir(root / "EPOCHS")
    assert project.pick_repos(["workspace/agent"]) == ["workspace/agent"]
    assert project.repo_remove("harness") == ["workspace/agent"]
    assert project.repo_add("workspace/harness") == ["workspace/agent", "workspace/harness"]
    monkeypatch.chdir(root / "workspace")
    assert project.repo_remove("workspace/agent") == ["workspace/harness"]
    assert project.repo_add("agent") == ["workspace/harness", "workspace/agent"]


def test_repo_needs_a_list_to_pick_from(tmp_path):
    root = tmp_path / "proj"
    make_checkout(root)
    Project.create(root, name="proj")
    project = Project.find(root)
    with pytest.raises(ClarityError) as err:
        project.start(project.add("x", status="planned").id, repos=["proj"])
    assert "no repos listed" in str(err.value)


def test_start_does_one_job(tmp_path):
    """start begins an epoch; adding a repo mid-flight is add-repo, and reopen takes
    back the repos the epoch had."""
    root = make_workspace(tmp_path)
    project = Project.find(root)
    for name in ("agent", "harness"):
        project.repo_add(str(root / "workspace" / name))
    item, _ = project.start(project.add("x", status="planned").id, repos=["agent"])

    for kwargs, says in (({}, "add-repo"), ({"repos": ["harness"]}, "add-repo")):
        with pytest.raises(ClarityError) as err:
            Project.find(root).start(item.id, **kwargs)
        assert err.value.code == 4 and says in str(err.value)
    Project.find(root).block(item.id, "waiting")
    with pytest.raises(ClarityError) as err:
        Project.find(root).start(item.id)
    assert "unblock" in str(err.value)
    Project.find(root).unblock(item.id)

    Project.find(root).close(item.id, "done")
    with pytest.raises(ClarityError) as err:
        Project.find(root).start(item.id, reopen=True, repos=["harness"])
    assert "add-repo" in str(err.value)
    reopened, _ = Project.find(root).start(item.id, reopen=True)
    assert reopened.repos == ["workspace/agent"]


def test_drop_repo_keeps_the_branch_and_refuses_what_would_lose_work(tmp_path):
    root = make_workspace(tmp_path)
    project = Project.find(root)
    for name in ("agent", "harness"):
        project.repo_add(str(root / "workspace" / name))
    item, _ = project.start(project.add("x", status="planned").id)
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

    with pytest.raises(ClarityError) as err:
        Project.find(root).drop_repo(item.id, "agent")
    assert "only repo" in str(err.value)
