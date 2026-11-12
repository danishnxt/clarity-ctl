"""Build meterbill, one builder session per epoch, into SCRATCH/build/box/workspace/meterbill.

    python build.py --upto 8

Resumable: an epoch is done when the repo has tag e<n>. A half-built epoch (session died, limit hit,
failed) is discarded: the tree is reset to the previous tag before the epoch is retried.
Stops at the first usage limit or failed session and says so (exit 3 / 1).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from common import (EXCLUDE, BUILD_BOX, BUILD_REPO, RESULTS, TOOLS, claude_cmd, env_for, hit_limit, result_event,
                    run_claude, setup_venv, sh, story)

TIMEOUT = 40 * 60
OUT = RESULTS / "build"


def init_repo() -> None:
    if (BUILD_REPO / ".git").exists():
        return
    BUILD_REPO.mkdir(parents=True, exist_ok=True)
    sh("git", "init", "-q", "-b", "main", cwd=BUILD_REPO)
    (BUILD_REPO / ".git" / "info" / "exclude").write_text(EXCLUDE)


def tags() -> set[str]:
    return set(sh("git", "tag", cwd=BUILD_REPO).stdout.split())


def reset_to(ref: str | None) -> None:
    if ref:
        sh("git", "reset", "-q", "--hard", ref, cwd=BUILD_REPO)
    else:                                       # nothing committed yet: empty the tree
        for p in BUILD_REPO.iterdir():
            if p.name != ".git":
                shutil.rmtree(p) if p.is_dir() else p.unlink()
    sh("git", "clean", "-fdxq", cwd=BUILD_REPO)


def stray_outside_repo() -> list[str]:
    """Anything in the box other than workspace/meterbill; recorded then deleted."""
    found = []
    for p in sorted(BUILD_BOX.iterdir()):
        if p.name == "workspace":
            found += [f"workspace/{q.name}" for q in sorted(p.iterdir()) if q.name != "meterbill"]
        else:
            found.append(p.name)
    for rel in found:
        p = BUILD_BOX / rel
        shutil.rmtree(p) if p.is_dir() and not p.is_symlink() else p.unlink()
    return found


def run_pytest() -> dict:
    p = sh("pytest", "-q", "-p", "no:cacheprovider", cwd=BUILD_REPO, env=env_for(None), check=False)
    out = (p.stdout + p.stderr).strip().splitlines()
    dirty = sh("git", "status", "--short", cwd=BUILD_REPO).stdout
    if dirty:                                   # tests that write into the tree must not leak into the next epoch
        reset_to("HEAD")
    return {"pytest_pass": p.returncode == 0, "pytest_rc": p.returncode, "pytest_tail": "\n".join(out[-8:]),
            "tree_dirty_after_pytest": dirty}


def build_epoch(ep: dict, prev_tag: str | None, rules: str) -> str:
    n = ep["n"]
    tag = f"e{n}"
    nn = f"{n:02d}"
    reset_to(prev_tag)
    head_before = sh("git", "rev-parse", "HEAD", cwd=BUILD_REPO, check=False).stdout.strip()
    cmd = claude_cmd(ep["prompt"], TOOLS, append_system=rules)
    stdout, stderr, rc, wall = run_claude(cmd, BUILD_BOX, env_for(None), TIMEOUT)
    ev = result_event(stdout)
    OUT.mkdir(parents=True, exist_ok=True)
    if hit_limit(ev, stderr):
        return "LIMIT"
    if ev is None or ev.get("is_error") or rc != 0:
        (OUT / f"e{nn}.failed.jsonl").write_text(stdout)
        (OUT / f"e{nn}.failed.txt").write_text(f"rc={rc}\n{stderr[-3000:]}\n")
        return f"FAILED rc={rc} {stderr[-200:]!r}"
    (OUT / f"e{nn}.jsonl").write_text(stdout)

    stray = stray_outside_repo()
    head_after = sh("git", "rev-parse", "HEAD", cwd=BUILD_REPO, check=False).stdout.strip()
    builder_committed = head_after != head_before
    if builder_committed:                       # rules forbid it; undo, keep the files
        sh("git", "reset", "-q", "--soft", prev_tag, cwd=BUILD_REPO) if prev_tag else None
    sh("git", "add", "-A", cwd=BUILD_REPO)
    sh("git", "commit", "-q", "--allow-empty", "-m", ep["commit"], cwd=BUILD_REPO)
    sh("git", "tag", tag, cwd=BUILD_REPO)
    base = prev_tag or sh("git", "hash-object", "-t", "tree", "/dev/null").stdout.strip()
    meta = {
        "n": n, "title": ep["title"], "commit_msg": ep["commit"], "prompt": ep["prompt"],
        "report": ev.get("result", ""),
        "diffstat": sh("git", "show", "--stat", "--format=", tag, cwd=BUILD_REPO).stdout,
        "shortstat": sh("git", "diff", "--shortstat", base, tag, cwd=BUILD_REPO).stdout.strip(),
        "usage": ev.get("usage"), "num_turns": ev.get("num_turns"), "total_cost_usd": ev.get("total_cost_usd"),
        "duration_ms": ev.get("duration_ms"), "wall_s": round(wall, 1), "returncode": rc,
        "stderr": stderr[-1000:], "stray_outside_repo": stray, "builder_committed": builder_committed,
        **run_pytest(),
    }
    (OUT / f"e{nn}.json").write_text(json.dumps(meta, indent=1))
    return (f"ok turns={meta['num_turns']} wall={wall:.0f}s pytest={'PASS' if meta['pytest_pass'] else 'FAIL'} "
            f"{meta['shortstat']}" + (f" STRAY={stray}" if stray else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--upto", type=int, default=10**6)
    a = ap.parse_args()
    setup_venv()
    init_repo()
    st = story()
    for ep in st["epochs"]:
        n = ep["n"]
        if n > a.upto:
            break
        have = tags()
        if f"e{n}" in have:
            continue
        prev = f"e{n - 1}" if n > 1 else None
        if prev and prev not in have:
            sys.exit(f"epoch {n}: previous tag {prev} missing")
        print(f"epoch {n} ({ep['title']}) ...", flush=True)
        r = build_epoch(ep, prev, st["builder_rules"])
        print(f"epoch {n}: {r}", flush=True)
        if r == "LIMIT":
            print("USAGE LIMIT: stopped; rerun to resume.")
            sys.exit(3)
        if r.startswith("FAILED"):
            sys.exit(1)


if __name__ == "__main__":
    main()
