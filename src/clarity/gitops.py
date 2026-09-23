"""The few git operations clarity needs. Never destructive."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .store import ClarityError


def _run(args: list[str], cwd: Path) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise ClarityError(f"git {' '.join(args)}: {proc.stderr.strip()}", code=4)
    return proc.stdout.strip()


def is_repo(root: Path) -> bool:
    return (root / ".git").exists()


def init(root: Path) -> None:
    """A new, empty repo. Nothing is staged or committed — that stays the human's call."""
    _run(["init", "-q"], root)


def repair_worktrees(root: Path) -> None:
    """After the main checkout moves, point its linked worktrees back at it.

    Best effort: the move has already happened, and a worktree git can't find is
    one `git worktree repair <path>` away, not a reason to fail the whole adopt.
    """
    subprocess.run(["git", "worktree", "repair"], cwd=str(root),
                   capture_output=True, text=True, check=False)


def current_branch(root: Path) -> str | None:
    if not is_repo(root):
        return None
    try:
        return _run(["rev-parse", "--abbrev-ref", "HEAD"], root)
    except ClarityError:
        return None


def head_sha(root: Path) -> str | None:
    if not is_repo(root):
        return None
    try:
        return _run(["rev-parse", "--short", "HEAD"], root)
    except ClarityError:
        return None


def branch_sha(root: Path, branch: str) -> str | None:
    """The tip of `branch`. Works whether or not it is checked out anywhere."""
    if not is_repo(root):
        return None
    try:
        return _run(["rev-parse", "--short", branch], root)
    except ClarityError:
        return None


def is_dirty(root: Path) -> list[str]:
    if not is_repo(root):
        return []
    out = _run(["status", "--porcelain"], root)
    return [line for line in out.splitlines() if line.strip()]


def branch_exists(root: Path, branch: str) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def worktree_path_for(root: Path, branch: str) -> Path | None:
    """Where `branch` is already checked out, if anywhere."""
    if not is_repo(root):
        return None
    path: Path | None = None
    for line in _run(["worktree", "list", "--porcelain"], root).splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :])
        elif line == f"branch refs/heads/{branch}":
            return path
    return None


def default_branch(root: Path) -> str | None:
    for name in ("main", "master"):
        if branch_exists(root, name):
            return name
    return None


def base_branch(root: Path) -> str | None:
    """The branch a new epoch is cut from: whatever the repo's own checkout is on.

    Work often lives on a long-running branch rather than main, and the checkout
    is where that choice is visible. A detached HEAD names no branch, so it falls
    back to main or master. Read once, when an epoch first branches the repo, and
    recorded — see Item.bases.
    """
    current = current_branch(root)
    if current and current != "HEAD":
        return current
    return default_branch(root)


def ahead_behind(root: Path, branch: str, base: str) -> tuple[int, int]:
    """(ahead, behind) of `branch` relative to `base`."""
    out = _run(["rev-list", "--left-right", "--count", f"{base}...{branch}"], root)
    behind, ahead = (int(n) for n in out.split())
    return ahead, behind


def _merging(worktree: Path) -> bool:
    """True only while git is stopped part-way through a merge."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "MERGE_HEAD"],
        cwd=str(worktree), capture_output=True, text=True, check=False,
    )
    return proc.returncode == 0


def merge_into(worktree: Path, base: str) -> str:
    """Merge `base` into whatever is checked out at `worktree`.

    Aborts on conflict rather than leaving a half-merged tree behind: clarity hands
    back a clean worktree or none at all, and a conflict is yours to resolve. Any
    other git failure is git's to explain — don't dress it up as a conflict.
    """
    try:
        return _run(["merge", "--no-edit", base], worktree)
    except ClarityError:
        if not _merging(worktree):
            raise
        _run(["merge", "--abort"], worktree)
        raise ClarityError(
            f"{base} conflicts with this branch — resolve it by hand:\n"
            f"  cd {worktree} && git merge {base}",
            code=4,
        ) from None


def add_worktree(root: Path, target: Path, branch: str, create: bool) -> None:
    args = ["worktree", "add"]
    if create:
        args += ["-b", branch]
    args.append(str(target))
    if not create:
        args.append(branch)
    _run(args, root)


def remove_worktree(root: Path, target: Path) -> None:
    """Drop the worktree, keep the branch."""
    try:
        _run(["worktree", "remove", "--force", str(target)], root)
    except ClarityError:
        pass  # already gone, or it was a symlink we made


def delete_branch(root: Path, branch: str) -> None:
    """Only for undoing a branch clarity created a moment ago, in a start that failed."""
    try:
        _run(["branch", "-D", branch], root)
    except ClarityError:
        pass
