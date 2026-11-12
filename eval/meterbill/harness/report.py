"""Summarise the slice: per-session token and behaviour metrics, tables per task, paired differences vs clarity.

    python report.py            # writes results/SLICE.md and prints it

cost_weighted = input + 1.25*cache_creation + 0.1*cache_read + 5*output (relative price weights of the four
token classes); paired differences are arm minus clarity, per rep, then averaged.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from common import ARMS, MEMORY, RESULTS, jsonl_file, mem_tag, read_jsonl, session_result, story
from split import split_session

CLARITY_READ = {"show", "search", "status", "--help", "-h", "help"}
ARM_ORDER = list(ARMS)                    # nothing, claudemd, clarity
METRICS = [("input", "input"), ("cache_creation", "cache_creation"), ("cache_read", "cache_read"),
           ("output", "output"), ("cost_weighted", "cost_weighted"), ("num_turns", "turns"),
           ("total_cost_usd", "cost_usd"), ("wall_s", "wall_s")]


def events(path: Path):
    for line in read_jsonl(path).splitlines():
        try:
            yield json.loads(line)
        except ValueError:
            continue


def session_stats(jsonl: Path, meta: dict) -> dict:
    ev = session_result(read_jsonl(jsonl)) or {}      # sums over all result events
    u = ev.get("usage") or {}
    s = {"input": u.get("input_tokens", 0), "cache_creation": u.get("cache_creation_input_tokens", 0),
         "cache_read": u.get("cache_read_input_tokens", 0), "output": u.get("output_tokens", 0),
         "num_turns": ev.get("num_turns"), "total_cost_usd": ev.get("total_cost_usd"), "wall_s": meta.get("wall_s")}
    s["cost_weighted"] = s["input"] + 1.25 * s["cache_creation"] + 0.1 * s["cache_read"] + 5 * s["output"]
    tools, reads, cl_read, cl_write, cl_cmds = Counter(), [], Counter(), Counter(), []
    for e in events(jsonl):
        if e.get("type") != "assistant":
            continue
        for c in e["message"].get("content", []):
            if c.get("type") != "tool_use":
                continue
            tools[c["name"]] += 1
            inp = c.get("input", {})
            if c["name"] == "Read":
                reads.append(inp.get("file_path", ""))
            if c["name"] == "Bash" and "clarity-ctl" in inp.get("command", ""):
                for verb in re.findall(r"clarity-ctl\s+([\w-]+)", inp["command"]):
                    (cl_read if verb in CLARITY_READ else cl_write)[verb] += 1
                    cl_cmds.append(verb)
    s.update(tools=dict(tools), reads=len(reads), reads_distinct=len(set(reads)), clarity_reads=sum(cl_read.values()),
             clarity_writes=sum(cl_write.values()), clarity_verbs=dict(cl_read + cl_write))
    return s


def gather_tasks(at: str = "e8") -> dict:
    out: dict = {}
    for meta_path in sorted((RESULTS / "tasks" / at).glob("*/*/r*.meta.json")):
        meta = json.loads(meta_path.read_text())
        jl = meta_path.with_name(meta_path.name.replace(".meta.json", ".jsonl"))
        s = session_stats(jl, meta)
        g = meta["grade"]
        s["grade"] = (f"vis {'P' if g['visible'] else 'F'} / tgt {'P' if g['target'] else 'F'} / "
                      f"keep {'P' if g['keep'] else 'F' if g['keep'] is not None else '-'}")
        s["keep_failed"] = sorted(k for k, v in (g.get("keep_tests") or {}).items() if not v)
        s["flags"] = [k for k, v in meta["flags"].items() if v]
        s["memory_changed"] = meta.get("memory_changed", [])
        s["timeout"] = meta.get("timeout")
        out.setdefault(meta["task"], {}).setdefault(meta["arm"], {})[meta["rep"]] = s
    return out


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def md_table(header: list[str], rows: list[list]) -> str:
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)] +
                     ["| " + " | ".join(fmt(c) for c in r) + " |" for r in rows])


def mean(xs):
    xs = [x for x in xs if x is not None]
    return statistics.fmean(xs) if xs else None


def task_section(task: str, per_arm: dict) -> str:
    arms = [a for a in ARM_ORDER if a in per_arm]
    reps = sorted({r for a in arms for r in per_arm[a]})
    lines = [f"### {task}", ""]
    rows = []
    for key, label in METRICS:
        rows.append([label] + [mean([per_arm[a][r][key] for r in per_arm[a]]) for a in arms])
    for key, label in [("reads", "files read"), ("reads_distinct", "distinct files read"),
                       ("clarity_reads", "clarity-ctl reads"), ("clarity_writes", "clarity-ctl writes")]:
        rows.append([label] + [mean([per_arm[a][r][key] for r in per_arm[a]]) for a in arms])
    rows.append(["tool calls"] + [", ".join(f"{k} {v}" for k, v in sorted(Counter(
        {k: sum(per_arm[a][r]["tools"].get(k, 0) for r in per_arm[a]) for t in per_arm[a].values() for k in t["tools"]}).items()))
        for a in arms])
    rows.append(["clarity-ctl verbs"] + [", ".join(f"{k} {v}" for k, v in sorted(Counter(
        {k: sum(per_arm[a][r]["clarity_verbs"].get(k, 0) for r in per_arm[a]) for t in per_arm[a].values() for k in t["clarity_verbs"]}).items())) or "-"
        for a in arms])
    rows.append(["grade (rep 1)"] + [per_arm[a].get(1, {}).get("grade", "-") for a in arms])
    rows.append(["keep tests failed"] + ["; ".join(per_arm[a].get(1, {}).get("keep_failed", [])) or "-" for a in arms])
    rows.append(["cache/module-dict in diff"] + [", ".join(per_arm[a].get(1, {}).get("flags", [])) or "-" for a in arms])
    rows.append(["memory files changed"] + ["; ".join(per_arm[a].get(1, {}).get("memory_changed", [])) or "-" for a in arms])
    lines += [f"Means over reps ({len(reps)}); token columns are per session.", "",
              md_table(["metric"] + arms, rows), ""]
    if "clarity" in per_arm:
        diffs = []
        for a in arms:
            if a == "clarity":
                continue
            paired = [r for r in per_arm[a] if r in per_arm["clarity"]]
            row = [f"{a} - clarity (n={len(paired)})"]
            for key, _ in METRICS:
                row.append(mean([per_arm[a][r][key] - per_arm["clarity"][r][key] for r in paired
                                 if per_arm[a][r][key] is not None and per_arm["clarity"][r][key] is not None]))
            diffs.append(row)
        lines += ["Paired differences vs clarity (positive = the arm used more):", "",
                  md_table(["pair"] + [l for _, l in METRICS], diffs), ""]
    return "\n".join(lines)


def replay_section() -> str:
    rows = []
    for arm in ("claudemd", "clarity"):
        for p in sorted((RESULTS / "replay" / arm).glob("e??.json")):
            m = json.loads(p.read_text())
            u = m.get("usage") or {}
            cw = u.get("input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0) + \
                0.1 * u.get("cache_read_input_tokens", 0) + 5 * u.get("output_tokens", 0)
            rows.append([arm, f"e{m['epoch']}", m.get("num_turns"), u.get("input_tokens"),
                         u.get("cache_creation_input_tokens"), u.get("cache_read_input_tokens"), u.get("output_tokens"),
                         cw, m.get("wall_s")])
    mem = []
    for arm in ("claudemd", "clarity"):
        d = MEMORY / arm / "e08"
        if d.exists():
            files = [p for p in d.rglob("*") if p.is_file()]
            mem.append([arm, len(files), sum(len(p.read_text(errors="replace")) for p in files)])
    return "\n".join(["## Replay (memory writing), epochs 1-8", "",
                      md_table(["arm", "epoch", "turns", "input", "cache_creation", "cache_read", "output",
                                "cost_weighted", "wall_s"], rows), "",
                      "Memory at e08:", "", md_table(["arm", "files", "chars"], mem), ""])


def passed(s: dict) -> bool:
    return "tgt P" in s["grade"] and "vis P" in s["grade"] and "keep F" not in s["grade"]


def vals(per_arm: dict, arm: str, key: str):
    return [per_arm.get(arm, {})[r][key] for r in sorted(per_arm.get(arm, {}))]


CHECKPOINT_NOTES = {
    "e24": "**Partial run.** The e24 task run was stopped by the owner after 18 of the planned 30 sessions "
           "(5 tasks x 2 arms x 3 reps). Reps 1 and 2 exist for every task and arm except H1/claudemd and "
           "P1/clarity (rep 1 only); rep 3 was never started. Every mean and pass count below is over the 1-2 reps "
           "that exist (n is in each cell). The nothing arm and the controls were not run at e24 "
           "(owner's scope: claudemd vs clarity only). Usage is summed over all `result` events of a session "
           "(P1/clarity/r1 has two); turns likewise.",
}


def checkpoint_report(at: str, max_rep: int = 3) -> None:
    """E<NN>.md for a checkpoint: the arms and tasks found under results/tasks/<at>/, reps 1..max_rep only."""
    raw = {k: v for k, v in gather_tasks(at).items() if not k.endswith("-oracle")}
    data = {t: {a: {r: s for r, s in reps.items() if r <= max_rep} for a, reps in per_arm.items()} for t, per_arm in raw.items()}
    kinds = {t["id"]: t["kind"] for t in story()["tasks"]}
    arms = [a for a in ARM_ORDER if any(a in per_arm for per_arm in data.values())]
    others = [a for a in arms if a != "clarity"]
    order = sorted(data, key=lambda t: (kinds[t] == "control", t))
    present_reps = sorted({r for per_arm in data.values() for reps in per_arm.values() for r in reps})
    extra_reps = sorted({r for per_arm in raw.values() for reps in per_arm.values() for r in reps if r > max_rep})
    out = [f"# meterbill checkpoint {at}: tokens per task by arm", "",
           "cost_weighted = input + 1.25*cache_creation + 0.1*cache_read + 5*output. A session passes when the visible "
           "suite, the hidden target tests and the hidden keep tests (where the task has any) all pass. "
           "Paired differences are arm minus clarity for the same task and rep (positive = the arm used more). "
           f"Arms: {', '.join(arms)}. Reps present: {', '.join(str(r) for r in present_reps)} (at most 1-{max_rep} are used)"
           + (f"; reps {extra_reps} exist on disk and are left out." if extra_reps else "."), ""]
    if at in CHECKPOINT_NOTES:
        out += [CHECKPOINT_NOTES[at], ""]

    def cw(task, arm):
        return mean(vals(data[task], arm, "cost_weighted"))

    def diffs(task, arm, key="cost_weighted"):
        pa, pc = data[task].get(arm, {}), data[task].get("clarity", {})
        return [pa[r][key] - pc[r][key] for r in sorted(pa) if r in pc]

    disc = RESULTS / "tasks" / at / "_discarded-no-location"
    if disc.exists():
        rows = []
        for t in order:
            ss = []
            for m in sorted((disc / t / "clarity").glob("r*.meta.json")):
                meta = json.loads(m.read_text())
                st = session_stats(m.with_name(m.name.replace(".meta.json", ".jsonl")), meta)
                g = meta["grade"]
                st["grade"] = (f"vis {'P' if g['visible'] else 'F'} / tgt {'P' if g['target'] else 'F'} / "
                               f"keep {'P' if g['keep'] else 'F' if g['keep'] is not None else '-'}")
                ss.append(st)
            if ss:
                rows.append([t, len(ss), f"{sum(passed(x) for x in ss)}/{len(ss)}", mean([x['cost_weighted'] for x in ss]),
                             mean([x['num_turns'] for x in ss])])
        out += ["## Discarded: first clarity run (box objective without the code location)", "",
                "The clarity box's .gitignore hides workspace/ from root-level Glob/Grep and its memory never said where the "
                "code is (the claudemd seed does), so some sessions never found the code. These sessions are kept in "
                "`results/tasks/e16/_discarded-no-location/` and are NOT used anywhere else in this file; "
                "all 18 clarity sessions were rerun with the objective naming `workspace/meterbill`.", "",
                md_table(["task", "sessions", "passes", "mean cost_w", "mean turns"], rows), ""]

    rows = []
    for t in order:
        n = {a: f"{sum(passed(s) for s in data[t].get(a, {}).values())}/{len(data[t].get(a, {}))}" for a in arms}
        rows.append([t, kinds[t]] + [cw(t, a) for a in arms] + [n[a] for a in arms] + [mean(diffs(t, o)) for o in others])
    for label, pred in (("history + handoff (mean)", lambda k: k != "control"), ("controls (mean)", lambda k: k == "control")):
        sel = [t for t in order if pred(kinds[t])]
        if sel:
            rows.append([label, ""] + [mean([cw(t, a) for t in sel]) for a in arms] + [""] * len(arms) +
                        [mean([mean(diffs(t, o)) for t in sel]) for o in others])
    out += ["## Summary", "", md_table(["task", "kind"] + [f"{a} cost_w" for a in arms] + [f"{a} pass" for a in arms] +
                                      [f"{o} - clarity" for o in others], rows), ""]

    out.append("## Per task")
    for t in order:
        pa = data[t]
        rows = []
        for a in arms:
            ss = pa.get(a, {})
            rows.append([a, ", ".join(f"{ss[r]['cost_weighted']:,.0f}" for r in sorted(ss)), mean(vals(pa, a, "cost_weighted")),
                         mean(vals(pa, a, "num_turns")), mean(vals(pa, a, "output")),
                         f"{sum(passed(s) for s in ss.values())}/{len(ss)}",
                         f"{sum('vis P' in s['grade'] for s in ss.values())}/{sum('tgt P' in s['grade'] for s in ss.values())}/"
                         f"{sum('keep P' in s['grade'] for s in ss.values())}",
                         mean(vals(pa, a, "clarity_reads")), mean(vals(pa, a, "clarity_writes"))])
        out += ["", f"### {t} ({kinds[t]})", "",
                md_table(["arm", "cost_w per rep", "mean", "turns", "output", "passes", "vis/tgt/keep passes", "clarity reads", "clarity writes"], rows), ""]
        drows = []
        for o in others:
            d = diffs(t, o)
            drows.append([f"{o} - clarity", ", ".join(f"{x:+,.0f}" for x in d), mean(d)])
        if drows:
            out += [md_table(["pair", "per-rep diff (cost_w)", "mean"], drows), ""]
        failing = {a: sorted({k for s in pa.get(a, {}).values() for k in s["keep_failed"]}) for a in arms}
        out.append("Keep tests that failed in some rep: " + "; ".join(f"{a}: {', '.join(v)}" for a, v in failing.items() if v) if any(failing.values()) else "No keep test failed.")
        flagged = [f"{a} r{r}: {', '.join(s['flags'])}" for a in arms for r, s in sorted(pa.get(a, {}).items()) if s["flags"]]
        out.append("Flags (cache/module dict in diff): " + ("; ".join(flagged) if flagged else "none") + ".")
        mem = [f"{a} r{r}: {', '.join(s['memory_changed'])}" for a in ("nothing",) for r, s in sorted(pa.get(a, {}).items()) if s["memory_changed"]]
        if "nothing" in arms:
            out.append("nothing-arm sessions that changed files outside the code: " + ("; ".join(mem) if mem else "none") + ".")

    rows = []
    for t in order:
        ss = data[t].get("clarity", {})
        verbs = Counter()
        for s in ss.values():
            verbs.update(s["clarity_verbs"])
        rows.append([t, mean(vals(data[t], "clarity", "clarity_reads")), mean(vals(data[t], "clarity", "clarity_writes")),
                     ", ".join(f"{k} {v}" for k, v in sorted(verbs.items()))])
    if "clarity" in arms:
        out += ["", "## clarity arm: clarity-ctl calls per session", "",
                md_table(["task", "reads (show/search/status)", "writes (everything else)", "verbs over all reps"], rows), ""]

    # solving vs memory work, by attributing each model turn to its tool calls (see split.py)
    rows = []
    for t in order:
        for a in [x for x in arms if x != "nothing"]:
            parts = []
            for r in sorted(data[t].get(a, {})):
                jl = RESULTS / "tasks" / at / t / a / f"r{r}.jsonl"
                if jsonl_file(jl):
                    parts.append(split_session(jl))
            if parts:
                solve, memory = mean([p["solve_cw"] for p in parts]), mean([p["mem_cw"] for p in parts])
                rows.append([t, a, solve + memory, solve, memory, f"{memory / (solve + memory):.0%}",
                             mean([p["solve_turns"] + p["mem_turns"] for p in parts]), mean([p["mem_turns"] for p in parts])])
    out += ["## Solving vs memory work (per session means)", "",
            "Each model turn is attributed to the tool calls it made: a turn whose calls read or write memory "
            "(CLAUDE.md, clarity-ctl, worklog/AGENTS/EPOCHS files) is memory work, the rest is solving; mixed turns are "
            "split by their share of memory calls (method in `harness/split.py`).", "",
            md_table(["task", "arm", "cost_w", "solving", "memory", "memory share", "turns", "memory turns"], rows), ""]

    if at == "e16":
        old = gather_tasks("e8")
        rows = []
        for t in ("T1", "C1"):
            for a in arms:
                o, n = old.get(t, {}).get(a, {}), data.get(t, {}).get(a, {})
                rows.append([t, a, mean([s["cost_weighted"] for s in o.values()]), len(o),
                             mean([s["cost_weighted"] for s in n.values()]), len(n)])
        out += ["## e8 vs e16 (T1 and C1, same prompt; e8 had 1 rep)", "",
                md_table(["task", "arm", "e8 cost_w", "e8 reps", "e16 cost_w", "e16 reps"], rows), ""]

    rows, mem = [], []
    blocks = (("e1-e8", 1, 8), ("e9-e16", 9, 16), ("e17-e24", 17, 24))
    for arm in ("claudemd", "clarity"):
        tot = Counter()
        for p in sorted((RESULTS / "replay" / arm).glob("e??.json")):
            m = json.loads(p.read_text())
            u = m.get("usage") or {}
            for name, lo, hi in blocks:
                if lo <= m["epoch"] <= hi:
                    tot[name + " cost_w"] += u.get("input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0) + \
                        0.1 * u.get("cache_read_input_tokens", 0) + 5 * u.get("output_tokens", 0)
                    tot[name + " turns"] += m.get("num_turns") or 0
        rows.append([arm] + [tot[f"{n} {k}"] for n, _, _ in blocks for k in ("cost_w", "turns")])
        d = MEMORY / arm / mem_tag(at)
        files = [p for p in d.rglob("*") if p.is_file()]
        mem.append([arm, len(files), sum(len(p.read_text(errors="replace")) for p in files)])
    out += ["## Replay cost (memory writing)", "",
            md_table(["arm"] + [f"{n} {k}" for n, _, _ in blocks for k in ("cost_w", "turns")], rows), "",
            f"Memory at {at}:", "", md_table(["arm", "files", "chars"], mem), ""]
    text = "\n".join(out)
    (RESULTS / f"{at.upper()}.md").write_text(text)
    print(text)


def main() -> None:
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(__doc__ + "\n    python report.py --at e16|e24   # writes results/E16.md / E24.md (checkpoint report) and prints it")
        return
    if "--at" in sys.argv:
        return checkpoint_report(sys.argv[sys.argv.index("--at") + 1])
    data = gather_tasks()
    parts = ["# meterbill slice: tokens per task by arm", "",
             "cost_weighted = input + 1.25*cache_creation + 0.1*cache_read + 5*output. "
             "Grades: vis = visible suite, tgt = hidden target tests, keep = hidden keep/trap tests.", "",
             "## Tasks", ""]
    for task in sorted(data):
        parts.append(task_section(task, data[task]))
    parts.append(replay_section())
    text = "\n".join(parts)
    (RESULTS / "SLICE.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
