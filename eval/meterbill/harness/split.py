"""Split a session's cost into solving vs memory work, by attributing each model turn to the tool calls it made.

A turn is one assistant message (one API call). Its input-side cost (input + 1.25*cache_creation + 0.1*cache_read,
taken from the message's own usage) is attributed whole to the turn. The session's output tokens (the stream's
per-message output counts are partial, so the result event's total is used) are shared out over turns in proportion
to the characters each turn generated (thinking, text, tool-call arguments), then weighted by 5.
A turn is "memory" to the extent its tool calls touch memory: Bash commands that run clarity-ctl or name a memory file,
Read/Edit/Write/Grep/Glob on CLAUDE.md, AGENTS.md, worklog.yaml, EPOCHS/ or .clarity/ outside the code repo.
A turn that mixes both is split by the share of its calls that are memory calls. A turn with no tool call (the final
report) counts as solving. Approximate: the cached context a memory turn re-reads is charged to it, as it would be.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from common import _add_nums, read_jsonl

MEMORY_NAMES = ("CLAUDE.md", "AGENTS.md", "worklog.yaml")
MEMORY_DIRS = ("/EPOCHS/", "/.clarity/", "EPOCHS/", ".clarity/")
MEMORY_RX = re.compile(r"clarity-ctl|CLAUDE\.md|AGENTS\.md|worklog\.yaml|\bEPOCHS/|\.clarity/")


def is_memory_call(name: str, args: dict) -> bool:
    if name == "Bash":
        return bool(MEMORY_RX.search(args.get("command", "")))
    if name in ("Read", "Edit", "Write"):
        path = args.get("file_path", "")
        if "workspace/meterbill" in path:
            return False
        return Path(path).name in MEMORY_NAMES or any(d in path for d in MEMORY_DIRS)
    if name in ("Grep", "Glob"):
        text = " ".join(str(args.get(k, "")) for k in ("path", "pattern", "glob"))
        return bool(MEMORY_RX.search(text)) and "workspace/meterbill" not in text
    return False


def split_session(jsonl: Path) -> dict:
    turns: dict[str, dict] = {}
    order: list[str] = []
    result = {}
    for line in read_jsonl(jsonl).splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "result":
            result = {**e, "usage": _add_nums(result.get("usage") or {}, e.get("usage") or {})}
        if e.get("type") != "assistant":
            continue
        msg = e["message"]
        t = turns.setdefault(msg["id"], {"usage": msg["usage"], "chars": 0, "calls": []})
        if msg["id"] not in order:
            order.append(msg["id"])
        for c in msg.get("content", []):
            if c["type"] == "tool_use":
                t["calls"].append(is_memory_call(c["name"], c.get("input", {})))
                t["chars"] += len(json.dumps(c.get("input", {})))
            elif c["type"] == "text":
                t["chars"] += len(c.get("text", ""))
            elif c["type"] == "thinking":
                t["chars"] += len(c.get("thinking", ""))
    total_out = (result.get("usage") or {}).get("output_tokens", 0)
    chars_sum = sum(t["chars"] for t in turns.values()) or 1
    out = {"solve_cw": 0.0, "mem_cw": 0.0, "solve_turns": 0.0, "mem_turns": 0.0, "mem_calls": 0, "calls": 0}
    for mid in order:
        t = turns[mid]
        u = t["usage"]
        cost = (u.get("input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0)
                + 0.1 * u.get("cache_read_input_tokens", 0) + 5 * total_out * t["chars"] / chars_sum)
        share = (sum(t["calls"]) / len(t["calls"])) if t["calls"] else 0.0
        out["mem_cw"] += cost * share
        out["solve_cw"] += cost * (1 - share)
        out["mem_turns"] += share
        out["solve_turns"] += 1 - share
        out["mem_calls"] += sum(t["calls"])
        out["calls"] += len(t["calls"])
    ru = result.get("usage") or {}
    reported = ru.get("input_tokens", 0) + 1.25 * ru.get("cache_creation_input_tokens", 0) + \
        0.1 * ru.get("cache_read_input_tokens", 0) + 5 * total_out
    out["attributed_cw"] = out["solve_cw"] + out["mem_cw"]
    out["reported_cw"] = reported
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit("usage: python split.py FILE.jsonl[.gz]   (solving-vs-memory split of one session)")
    print(json.dumps(split_session(Path(sys.argv[1][:-3] if sys.argv[1].endswith(".gz") else sys.argv[1])), indent=1))
