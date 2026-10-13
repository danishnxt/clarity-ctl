"""Locks, leases, and working out which epoch a command means."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from clarity import ClarityError, Project
from clarity import lease


def write_lease(folder: Path, owner: str, at: str | None = None) -> None:
    """Someone else's lease, as another machine would have left it."""
    at = at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    lease.path_for(folder).write_text(yaml.safe_dump(
        {"owner": owner, "host": "otherbox", "at": at}))


def test_write_lock_keeps_concurrent_adds(project, repo):
    """Five processes adding at once: none may overwrite another's item."""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}

    def add(n: int):
        return subprocess.run(
            [sys.executable, "-m", "clarity.cli", "idea", "add", f"idea {n}"],
            cwd=str(repo), env=env, capture_output=True, text=True,
        )

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(add, range(5)))

    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    items = Project.find(repo).worklog.items
    assert len(items) == 5
    assert len({i.id for i in items}) == 5  # no duplicate ids either


def test_another_holders_lease_refuses_however_old(project, repo):
    """Nothing expires on its own — a years-old lease still refuses, and says how old."""
    item, _ = project.start(project.add("cache warmup").id)
    folder = repo / item.folder

    # (owner, written at, what the refusal says) — a live lease and an ancient one
    for owner, at, says in (("someone", None, "someone@otherbox"),
                            ("ghost", "2020-01-01T00:00:00+00:00", "--steal")):
        write_lease(folder, owner, at)
        if at:
            assert project.leases()[item.id]["age"].endswith("d ago")  # shown, not enforced

        with pytest.raises(ClarityError) as err:
            project.claim(item.id)
        assert err.value.code == 4 and says in str(err.value)

        _, held = project.claim(item.id, steal=True)
        assert f"{owner}@otherbox" in held["stolen_from"]
        assert lease.held_by_us(lease.read(folder))


def test_an_id_is_never_inferred(project, repo, monkeypatch):
    """No cwd, no env var, no "the only active one" — the id is in the command."""
    only, _ = project.start(project.add("cache warmup", type_="experiment").id)

    # the case that silently worked before: one epoch active, no id passed
    monkeypatch.chdir(repo)
    with pytest.raises(ClarityError) as err:
        Project.find(repo).resolve_id()
    assert err.value.code == 4

    second, _ = project.start(project.add("lto build", type_="experiment").id)
    ids = [only.id, second.id]

    # inside an epoch's own folder, and inside its worktree
    for cwd in (repo / only.folder / "LOGS", repo / second.folder / "wt" / repo.name):
        monkeypatch.chdir(cwd)
        with pytest.raises(ClarityError) as err:
            Project.find(repo).resolve_id()
        assert err.value.code == 4 and "needs an epoch id" in str(err.value)

    # a stale export from some other shell is not consulted either
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CLARITY_EPOCH", str(ids[1]))
    with pytest.raises(ClarityError) as err:
        Project.find(repo).resolve_id()
    assert err.value.code == 4

    # and the refusal names what it could have meant
    assert all(str(i) in str(err.value) for i in ids)


def test_our_own_lease_is_not_a_refusal(repo, monkeypatch):
    """Identity is the declared name, not a process — the same agent reclaims freely."""
    monkeypatch.setenv("CLARITY_AGENT", "agent-alpha")
    Project.create(repo, name="proj")
    project = Project.find(repo)
    item, _ = project.start(project.add("cache warmup").id)
    folder = repo / item.folder

    project.claim(item.id)                       # one command claims it
    assert lease.read(folder)["owner"] == "agent-alpha"
    project.claim(item.id)                       # a later command, a new process
    assert lease.held_by_us(lease.read(folder))

    monkeypatch.setenv("CLARITY_AGENT", "agent-beta")
    with pytest.raises(ClarityError) as err:     # a different agent is refused
        project.claim(item.id)
    assert err.value.code == 4 and "agent-alpha" in str(err.value)


def test_find_skips_a_worktree_copy_of_the_state(project, repo, monkeypatch):
    """Inside an epoch worktree, commands must reach the real project, not the copy."""
    item = project.add("cache warmup")
    project.start(item.id)

    worktree = repo / project.worklog.by_id(item.id).folder / "wt" / repo.name
    # simulate the state having been committed: the worktree now holds its own copy
    (worktree / ".clarity").mkdir(parents=True, exist_ok=True)
    (worktree / "worklog.yaml").write_text("version: 1\nobjectives: {}\nitems: []\n")

    monkeypatch.chdir(worktree)
    found = Project.find()
    assert found.root == repo
    assert [i.id for i in found.worklog.items] == [item.id]  # the real one, not the copy


def test_a_refused_lease_leaves_nothing_half_started(project, repo):
    """The claim happens inside the write lock, so a loser writes no state at all."""
    # an idea that already has a folder — one that was `planned` before worklog v2
    item = project.add("cache warmup")
    with project._write():
        project._make_folder(project.worklog.by_id(item.id))
    folder = repo / Project.find(repo).worklog.by_id(item.id).folder

    write_lease(folder, "someone")

    with pytest.raises(ClarityError) as err:
        project.start(item.id)
    assert err.value.code == 4

    fresh = Project.find(repo).worklog.by_id(item.id)
    assert fresh.status == "idea"             # not active
    assert fresh.started is None
    assert not (folder / "wt").exists()       # and no worktree it may not use
