"""Run the coding tasks: a fresh box per (task, arm, rep), then grade the result with the hidden tests.

    python tasks.py --at e16 --reps 3 [--task T1] [--arm clarity] [--workers 3]

Box = make_box(arm, <checkpoint>) with the arm's memory from results/memory/<arm>/<checkpoint> (nothing: none).
The session gets the task prompt verbatim; hidden tests are never in the box. Afterwards the code repo is
copied out, its full diff (tracked + untracked) saved, and hidden tests are copied into the copy and run.
Resumable per (task, arm, rep); on a usage limit nothing more is started and the rest is listed.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import (ARMS, MB, MEMORY, MEMORY_PATHS, RESULTS, SCRATCH, TOOLS, VENV, claude_cmd, env_for, hit_limit,
                    jsonl_file, make_box, mem_tag, read_jsonl, restore_memory, set_clarity_location, result_event, session_result, run_claude, setup_venv, sh, snapshot_memory, story)

TIMEOUT = 40 * 60
OUT = RESULTS / "tasks"
stop = threading.Event()
remaining: list[tuple] = []
lock = threading.Lock()

ORACLE_H1 = ("Context from earlier sessions: accounting remaps meters to new revenue accounts at year end, and a credit "
             "note has to post to the accounts the original invoice posted to, not to today's mapping. The plan was to "
             "record the revenue account on each InvoiceLine when the invoice is built. Credit notes reverse tax at the "
             "original line's stored tax amounts.")
CACHE_ADDED = re.compile(r"^\+.*\b(lru_cache|functools\.cache|@cache\b)", re.M)
MODULE_DICT_ADDED = re.compile(r"^\+(_?[A-Za-z_][A-Za-z0-9_]*)\s*(:[^=\n]+)?=\s*(\{\}|dict\(\)|defaultdict\(.*\)|\{[^}\n]*\})\s*$", re.M)


def path_for(at: str, task: str, arm: str, rep: int) -> Path:
    return OUT / at / task / arm / f"r{rep}"


def done(at: str, task: str, arm: str, rep: int) -> bool:
    p = path_for(at, task, arm, rep)
    jl = jsonl_file(p.with_suffix(".jsonl"))
    ev = result_event(read_jsonl(jl)) if jl else None
    return bool(ev) and not hit_limit(ev) and p.with_suffix(".meta.json").exists()


def pytest_run(tree: Path, target: str, junit: Path | None = None) -> tuple[int, dict[str, bool]]:
    cmd = [str(VENV / "bin" / "python"), "-m", "pytest", target, "-q", "-p", "no:cacheprovider"]
    if junit:
        cmd.append(f"--junitxml={junit}")
    p = sh(*cmd, cwd=tree, env=env_for(None), check=False, timeout=600)
    res: dict[str, bool] = {}
    if junit and junit.exists():
        for case in ET.parse(junit).getroot().iter("testcase"):
            res[f"{case.get('classname', '').split('.')[-1]}::{case.get('name')}"] = not (
                case.find("failure") is not None or case.find("error") is not None)
    return p.returncode, res


def grade(at: str, task: str, repo: Path, work: Path) -> dict:
    """Copy the repo, record its diff, run visible + hidden tests in the copy."""
    tree = work / "tree"
    shutil.copytree(repo, tree, symlinks=True)
    sh("git", "add", "-A", cwd=tree)
    diff = sh("git", "diff", "--cached", "HEAD", cwd=tree).stdout
    hidden_src = MB / "tasks" / at / task.removesuffix("-oracle") / "hidden"
    shutil.copytree(hidden_src, tree / "_hidden")
    vis_rc, _ = pytest_run(tree, "tests")
    _, res = pytest_run(tree, "_hidden", work / "junit.xml")
    target = {k: v for k, v in res.items() if k.startswith("test_target")}
    keep = {k: v for k, v in res.items() if k.startswith("test_keep")}
    return {
        "diff": diff,
        "grade": {
            "visible": vis_rc == 0,
            "target": bool(target) and all(target.values()), "target_tests": target,
            "keep": all(keep.values()) if keep else None, "keep_tests": keep,
            "hidden_collected": len(res),
        },
        "flags": {
            "cache_in_diff": bool(CACHE_ADDED.search(diff)),
            "module_level_dict_in_diff": bool(MODULE_DICT_ADDED.search(diff)),
        },
    }


def memory_changes(base: Path, arm: str, box: Path) -> list[str]:
    """Memory files the session changed relative to the box's starting memory (``base``), plus stray files in the box root."""
    changed: list[str] = []
    now = Path(tempfile.mkdtemp(prefix="memnow-", dir=SCRATCH))
    try:
        snapshot_memory(arm, box, now)
        a = {p.relative_to(base).as_posix(): p.read_bytes() for p in base.rglob("*") if p.is_file()} if base.exists() else {}
        b = {p.relative_to(now).as_posix(): p.read_bytes() for p in now.rglob("*") if p.is_file()}
        changed += [f"{k}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
    finally:
        shutil.rmtree(now, ignore_errors=True)
    expected = {"workspace"} | {Path(p).parts[0] for p in MEMORY_PATHS[arm]} | ({".git", ".gitignore"} if arm == "clarity" else set())
    changed += [f"(new in box root) {p.name}" for p in sorted(box.iterdir()) if p.name not in expected]
    return changed


def session(at: str, item: tuple[str, str, int], prompt: str) -> str:
    task, arm, rep = item
    if stop.is_set():
        with lock:
            remaining.append(item)
        return "skipped"
    parent = SCRATCH / "task-boxes"
    box = make_box(arm, at, parent)
    base = Path(tempfile.mkdtemp(prefix="membase-", dir=SCRATCH))
    if arm != "nothing":
        restore_memory(arm, box, MEMORY / arm / mem_tag(at))
    if arm == "clarity":
        set_clarity_location(box)               # after the restore: the snapshot's worklog has the old objective
    snapshot_memory(arm, box, base)             # the memory the session starts from
    stdout, stderr, rc, wall = run_claude(claude_cmd(prompt, TOOLS), box, env_for(arm), TIMEOUT)
    ev = result_event(stdout)               # last event: is_error / usage-limit check
    sev = session_result(stdout)            # totals over all result events (a late task-notification adds one)
    if hit_limit(ev, stderr):
        stop.set()
        with lock:
            remaining.append(item)
        shutil.rmtree(box, ignore_errors=True)
        shutil.rmtree(base, ignore_errors=True)
        return "USAGE LIMIT"
    p = path_for(at, task, arm, rep)
    p.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="grade-", dir=SCRATCH))
    try:
        g = grade(at, task, box / "workspace" / "meterbill", work)
        mem = memory_changes(base, arm, box)
    finally:
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(box, ignore_errors=True)
    p.with_suffix(".jsonl").write_text(stdout)
    p.with_suffix(".diff").write_text(g["diff"])
    meta = {"at": at, "task": task, "arm": arm, "rep": rep, "returncode": rc, "wall_s": round(wall, 1),
            "timeout": stderr == "TIMEOUT", "stderr": stderr[-1500:], "usage": (sev or {}).get("usage"),
            "num_turns": (sev or {}).get("num_turns"), "total_cost_usd": (sev or {}).get("total_cost_usd"),
            "result_events": (sev or {}).get("result_events"), "duration_ms": (sev or {}).get("duration_ms"),
            "is_error": (ev or {}).get("is_error"), "result": (ev or {}).get("result"),
            "memory_changed": mem, "prompt": prompt, **{k: g[k] for k in ("grade", "flags")}}
    p.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1))
    gr = g["grade"]
    return (f"ok rc={rc} {wall:.0f}s turns={meta['num_turns']} visible={gr['visible']} target={gr['target']} "
            f"keep={gr['keep']} flags={g['flags']} memory_changed={mem}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", required=True, help="checkpoint tag, e.g. e16")
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--task", nargs="+", action="extend", help="task ids, e.g. --task D1 P1 X1 H2 H1")
    ap.add_argument("--arm", nargs="+", action="extend", choices=list(ARMS), help="arms, e.g. --arm claudemd clarity")
    ap.add_argument("--list", action="store_true", help="print the sessions that would run, then exit")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--oracle", action="store_true",
                    help="control run: task H1 with the deciding facts appended to its prompt, saved as H1-oracle")
    a = ap.parse_args()
    setup_venv()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    prompts = {t["id"]: t["prompt"].rstrip("\n") for t in story()["tasks"] if "prompt" in t}
    if a.oracle:
        prompts["H1-oracle"] = prompts["H1"] + "\n\n" + ORACLE_H1
        a.task = ["H1-oracle"]
    have = {p.name for p in (MB / "tasks" / a.at).iterdir() if p.is_dir()} | ({"H1-oracle"} if a.oracle else set())
    tasks = a.task or sorted(have & set(prompts))
    arms = a.arm or (["claudemd", "clarity"] if a.at == "e24" else list(ARMS))
    if a.at == "e24" and "nothing" in arms:
        sys.exit("e24 runs only the claudemd and clarity arms (owner's scope in story.yaml)")
    for arm in arms:
        if arm != "nothing" and not (MEMORY / arm / mem_tag(a.at)).exists():
            sys.exit(f"memory snapshot missing: {MEMORY / arm / mem_tag(a.at)} (run replay.py first)")
    todo = [(t, arm, r) for r in range(1, a.reps + 1) for t in tasks for arm in arms if not done(a.at, t, arm, r)]
    print(f"{len(todo)} sessions to run", flush=True)
    if a.list:
        for item in todo:
            print(item)
        return

    def go(item):
        print(f"{item}: {session(a.at, item, prompts[item[0]])}", flush=True)

    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(go, todo))
    if remaining:
        print("REMAINING (usage limit):", sorted(remaining))
        sys.exit(3)


if __name__ == "__main__":
    main()
