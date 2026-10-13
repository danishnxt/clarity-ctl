"""Shared fixtures: a git repo, a clarity project on one, and a multi-repo workspace.

Every git call pins its identity and branch name, so no test depends on the
machine's git config.
"""

import subprocess
from pathlib import Path

import pytest

from clarity import Project

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t"]


def run_git(args, cwd) -> str:
    return subprocess.run(["git", *GIT_ID, *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout.strip()


def init_repo(path: Path) -> Path:
    """A repo on main with one commit holding src/main.py."""
    (path / "src").mkdir(parents=True)
    (path / "src" / "main.py").write_text("print('hi')\n")
    run_git(["init", "-q", "-b", "main"], path)
    run_git(["add", "-A"], path)
    run_git(["commit", "-qm", "init"], path)
    return path


@pytest.fixture
def git():
    return run_git


@pytest.fixture
def commit():
    """commit(repo, file) writes `file` and commits it; no file is an empty commit."""
    def _commit(repo: Path, file: str | None = None, msg: str = "work") -> None:
        if file is None:
            run_git(["commit", "-q", "--allow-empty", "-m", msg], repo)
            return
        (Path(repo) / file).write_text(f"{file}\n")
        run_git(["add", "-A"], repo)
        run_git(["commit", "-qm", msg], repo)
    return _commit


@pytest.fixture
def new_repo():
    return init_repo


@pytest.fixture
def repo(tmp_path) -> Path:
    """A plain git repo named proj — not yet a clarity project."""
    return init_repo(tmp_path / "proj")


@pytest.fixture
def project(repo) -> Project:
    """A single-repo project: the code repo is the project root."""
    Project.create(repo, name="proj")
    return Project.find(repo)


@pytest.fixture
def ws_root(tmp_path) -> Path:
    """No repo at the root, two repos we change, one we only use — none listed yet."""
    root = tmp_path / "ws"
    for repo in ("workspace/agent", "workspace/harness", "3rd_party/duckdb"):
        init_repo(root / repo)
    Project.create(root, name="ws")
    return root


@pytest.fixture
def workspace(ws_root) -> Project:
    """The workspace with agent and harness listed, so epochs branch both."""
    project = Project.find(ws_root)
    for name in ("agent", "harness"):
        project.repo_add(str(ws_root / "workspace" / name))
    return Project.find(ws_root)
