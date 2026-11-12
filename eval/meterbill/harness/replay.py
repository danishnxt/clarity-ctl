"""Replay the story to the written-memory arms: one persistent box per arm, one session per epoch.

    python replay.py [--arm claudemd --arm clarity] [--upto 8]

Per arm (arms run in parallel, epochs sequentially): before epoch n the box's code repo is moved to tag e<n>;
a fresh session gets the replay prompt of arms.md filled from results/build/e<NN>.json and brings the
arm's memory up to date; afterwards the code repo must be clean and at e<n>, and the memory is snapshotted to
results/memory/<arm>/e<NN>/. Resumable per (arm, epoch): done = replay jsonl with a good result event
and a memory snapshot. On a usage limit, stops and lists what is left.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from common import (BUILD_REPO, jsonl_file, read_jsonl, MEMORY, RESULTS, SCRATCH, TOOLS, claude_cmd, env_for, hit_limit, make_box_at,
                    replay_template, restore_memory, result_event, run_claude, set_clarity_location, setup_venv, sh,
                    snapshot_memory)

TIMEOUT = 40 * 60
OUT = RESULTS / "replay"
stop = threading.Event()
problems: list[str] = []


def fill(template: str, build: dict) -> str:
    values = {"prompt": build["prompt"].rstrip("\n"), "report": build["report"].strip(),
              "diffstat": build["diffstat"].rstrip("\n")}
    return re.sub(r"\{(prompt|report|diffstat)\}", lambda m: values[m.group(1)], template)


def done(arm: str, n: int) -> bool:
    path = OUT / arm / f"e{n:02d}.jsonl"
    if not jsonl_file(path) or not (MEMORY / arm / f"e{n:02d}").exists():
        return False
    ev = result_event(read_jsonl(path))
    return bool(ev) and not ev.get("is_error")


def move_code_to(box, n: int) -> None:
    repo = box / "workspace" / "meterbill"
    sh("git", "fetch", "-q", "--no-tags", str(BUILD_REPO), f"refs/tags/e{n}", cwd=repo)
    sh("git", "reset", "-q", "--hard", "FETCH_HEAD", cwd=repo)
    sh("git", "clean", "-fdxq", cwd=repo)


def check_code(box, n: int) -> None:
    repo = box / "workspace" / "meterbill"
    dirty = sh("git", "status", "--porcelain", cwd=repo).stdout
    head = sh("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    want = sh("git", "rev-parse", f"e{n}^{{commit}}", cwd=BUILD_REPO).stdout.strip()
    if dirty or head != want:
        raise RuntimeError(f"code repo not clean at e{n}: head={head[:7]} want={want[:7]} status={dirty!r}")


def run_arm(arm: str, upto: int) -> None:
    box = SCRATCH / "arms" / arm
    last = max([n for n in range(1, upto + 1) if all(done(arm, k) for k in range(1, n + 1))], default=0)
    if last == 0:                               # nothing usable on disk: start the arm from scratch
        shutil.rmtree(box, ignore_errors=True)
        make_box_at(arm, "e1", box)
    elif not box.exists():
        sys.exit(f"{arm}: epochs 1-{last} are done but the box {box} is gone; delete results/*/{arm} and rerun")
    else:                                       # drop whatever an interrupted session left in the memory files
        restore_memory(arm, box, MEMORY / arm / f"e{last:02d}")
    if arm == "clarity" and last >= 16:
        set_clarity_location(box)              # e1-e16 ran without it (arms.md); from e17 on the objective names the code
    template = replay_template()
    for n in range(last + 1, upto + 1):
        if stop.is_set():
            problems.append(f"{arm}: stopped before e{n}")
            return
        build = json.loads((RESULTS / "build" / f"e{n:02d}.json").read_text())
        move_code_to(box, n)
        prompt = fill(template, build)
        stdout, stderr, rc, wall = run_claude(claude_cmd(prompt, TOOLS), box, env_for(arm), TIMEOUT)
        ev = result_event(stdout)
        if hit_limit(ev, stderr):
            stop.set()
            problems.append(f"{arm}: USAGE LIMIT at e{n}")
            restore_memory(arm, box, MEMORY / arm / f"e{n - 1:02d}") if n > 1 else None
            return
        (OUT / arm).mkdir(parents=True, exist_ok=True)
        (OUT / arm / f"e{n:02d}.jsonl").write_text(stdout)
        meta = {"arm": arm, "epoch": n, "returncode": rc, "wall_s": round(wall, 1), "stderr": stderr[-1500:],
                "usage": (ev or {}).get("usage"), "num_turns": (ev or {}).get("num_turns"),
                "total_cost_usd": (ev or {}).get("total_cost_usd"), "result": (ev or {}).get("result"),
                "is_error": (ev or {}).get("is_error"), "prompt": prompt}
        (OUT / arm / f"e{n:02d}.json").write_text(json.dumps(meta, indent=1))
        if ev is None or ev.get("is_error") or rc != 0:
            problems.append(f"{arm}: e{n} failed rc={rc} {stderr[-200:]!r}")
            return
        check_code(box, n)                       # raises: the replay agent must not touch the code
        snapshot_memory(arm, box, MEMORY / arm / f"e{n:02d}")
        print(f"{arm} e{n}: ok turns={meta['num_turns']} wall={wall:.0f}s", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", choices=["claudemd", "clarity"])
    ap.add_argument("--upto", type=int, default=8)
    a = ap.parse_args()
    setup_venv()
    arms = a.arm or ["claudemd", "clarity"]
    with ThreadPoolExecutor(len(arms)) as ex:
        futures = {arm: ex.submit(run_arm, arm, a.upto) for arm in arms}
        for arm, f in futures.items():
            try:
                f.result()
            except Exception as exc:                  # fail loudly, per arm
                problems.append(f"{arm}: {type(exc).__name__}: {exc}")
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(3 if any("USAGE LIMIT" in p for p in problems) else 1)


if __name__ == "__main__":
    main()
