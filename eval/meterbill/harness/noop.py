"""Context-leak check: does any arm's session see instructions it should not (the owner's global CLAUDE.md etc.)?

    python noop.py

One cheap session per arm in a box with that arm's memory files (and an empty git repo at workspace/meterbill,
as the real boxes have). Expected: nothing -> NONE / no; claudemd -> meterbill / no; clarity -> its headings / no.
Any 'yes' means isolation is broken: stop and look. Saves RESULTS/noop/<arm>.jsonl and <arm>.json.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from common import (ARMS, RESULTS, SCRATCH, arm_memory, set_clarity_location, claude_cmd, env_for, hit_limit, result_event, run_claude,
                    setup_venv, sh)

PROMPT = ("Reply with exactly the first markdown heading of each CLAUDE.md / AGENTS.md / memory instruction file "
          "in your context, one per line, or NONE. Then one line: does the word 'Global preferences' or "
          "'Lead with the answer' appear anywhere in your instructions? yes/no.")


def main() -> None:
    if sys.argv[1:]:                  # this script takes no arguments; it starts one `claude` session per arm
        print(__doc__)
        return
    setup_venv()
    out = RESULTS / "noop"
    out.mkdir(parents=True, exist_ok=True)
    bad = False
    for arm in ARMS:
        parent = SCRATCH / "noop"
        parent.mkdir(parents=True, exist_ok=True)
        box = Path(tempfile.mkdtemp(prefix=f"{arm}-", dir=parent))
        arm_memory(arm, box)
        sh("git", "init", "-q", "-b", "main", str(box / "workspace" / "meterbill"))
        if arm == "clarity":
            set_clarity_location(box)
            print("objective line in AGENTS.md:", [l for l in (box / "AGENTS.md").read_text().splitlines() if "Objective" in l])
        stdout, stderr, rc, wall = run_claude(claude_cmd(PROMPT, ["Read"]), box, env_for(arm), 300)
        ev = result_event(stdout)
        if hit_limit(ev, stderr):
            sys.exit("USAGE LIMIT")
        (out / f"{arm}.jsonl").write_text(stdout)
        answer = (ev or {}).get("result", "")
        usage = (ev or {}).get("usage")
        (out / f"{arm}.json").write_text(json.dumps({"arm": arm, "answer": answer, "usage": usage,
                                                     "num_turns": (ev or {}).get("num_turns"), "wall_s": round(wall, 1),
                                                     "box_files": sorted(p.name for p in box.iterdir())}, indent=1))
        print(f"=== {arm} (rc={rc}, {wall:.0f}s) box={sorted(p.name for p in box.iterdir())}\n{answer}\nusage={usage}\n")
        last = answer.strip().splitlines()[-1].lower() if answer.strip() else ""
        if "yes" in last or "global preferences" in answer.lower() and "lead with" in answer.lower() and "yes" in answer.lower():
            bad = True
        shutil.rmtree(box, ignore_errors=True)
    if bad:
        print("ISOLATION BROKEN: a 'yes' answer")
        sys.exit(1)


if __name__ == "__main__":
    main()
