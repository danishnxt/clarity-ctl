#!/usr/bin/env python3
"""How many tokens does it take a fresh session to get up to speed, with and without clarity?

    python3 bench/token-savings/run.py all --out /tmp/bench/r1 --blocks 8 --checkpoints 1,3,8

Phases, each resumable (`build`, `work`, `ripout`, `probe`, `grade`, `report`):

  build   lay out one project per arm from seed/, plus venvs for the agent's tools
  work    run scenario sessions, one fresh `claude -p` each; snapshot at every checkpoint
  ripout  at each checkpoint, copy the clarity arm, have Claude write CLAUDE.md from clarity, delete clarity
  probe   restore each arm at each checkpoint and ask that checkpoint's probes, --reps times each
  grade   score each answer against its rubric with a separate Claude call
  report  report.md and summary.csv; pass --out once per replicate to combine them

Arms:
  clarity   clarity-ctl initialised; its AGENTS.md block is all the agent is told
  claudemd  no clarity; CLAUDE.md tells the agent to keep CLAUDE.md current
  vanilla   no clarity; CLAUDE.md only names the objective — stock Claude Code
  ripout    the clarity arm at a checkpoint, turned into CLAUDE.md by Claude, then clarity removed

Every call runs with a private CLAUDE_CONFIG_DIR per arm and the calling session's
own environment scrubbed, so nothing outside the arm's folder leaks into its context.
Tools are limited to ALLOWED, unless --bypass (only inside a throwaway container or CI
runner) skips permission checks so denied commands don't add noise.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import scenario  # noqa: E402

WORK_ARMS = ["clarity", "claudemd", "vanilla"]
ALL_ARMS = WORK_ARMS + ["ripout"]

# What the agent may run. Scoped rather than --dangerously-skip-permissions: enough to
# code, test, commit and use clarity, nothing that reaches outside the arm's folder.
ALLOWED = [
    "Read", "Edit", "Write", "Glob", "Grep",
    "Bash(git *)", "Bash(python *)", "Bash(python3 *)", "Bash(pytest *)", "Bash(clarity-ctl *)",
    "Bash(cd *)", "Bash(ls *)", "Bash(cat *)", "Bash(head *)", "Bash(tail *)", "Bash(wc *)",
    "Bash(grep *)", "Bash(find *)", "Bash(time *)", "Bash(diff *)", "Bash(echo *)", "Bash(pwd)",
    "Bash(sed *)", "Bash(awk *)", "Bash(sort *)", "Bash(uniq *)", "Bash(mkdir *)", "Bash(which *)",
    "Bash(timeout *)", "Bash(/usr/bin/time *)", "Bash(tree *)", "Bash(stat *)", "Bash(du *)",
]

# Set by the session that launches us; any of them can pull that session's context in.
SCRUB = [
    "CLAUDECODE", "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "CLAUDE_ADDITIONAL_DIRECTORIES",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_TEE_SDK_STDOUT",
    "CLAUDE_PID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_AFTER_LAST_COMPACT", "VIRTUAL_ENV",
    "CLAUDE_CODE_INCLUDE_PARTIAL_MESSAGES",
]

# Our own snapshots, worktree links included; the default filter would strip them on 3.14.
TRUSTED = {"filter": "fully_trusted"} if hasattr(tarfile, "fully_trusted_filter") else {}

READS = ("cat ", "head ", "tail ", "sed -n", "less ")
CLARITY = re.compile(r"(?:^|[\s;&|(`])clarity-ctl(?=\s|$)")  # the command, not a path with the name in it
SEARCHES = ("grep ", "rg ", "find ", "git log", "git show", "git diff", "git branch", "ls ")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sh(cmd, cwd=None, env=None, check=True):
    return subprocess.run(cmd, cwd=cwd, env=env, check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout


def summarise_tools(tools, root: Path, out: Path):
    """Counts that say how a session found things out, from its tool calls.

    `escapes` counts calls that reach outside the arm's project into the run folder
    (other arms, results, traces) or this repo (the scenario and its answers). Any
    non-zero count means that session's answers may not be its own.
    """
    cmds = [t["input"].get("command", "") for t in tools if t["name"] == "Bash"]
    first = tools[0] if tools else None

    def escapes(t):
        text = json.dumps(t["input"])
        outside = [m for m in re.findall(re.escape(str(out)) + r"[^\s\"'`;|&<>()]*", text)
                   if not m.startswith(str(root))]
        return bool(outside) or str(REPO) in text or "../.." in text

    return {
        "tool_calls": len(tools),
        "clarity_cmds": sum(bool(CLARITY.search(c)) for c in cmds),
        "notes": sum(bool(re.search(CLARITY.pattern + r"\s+note\b", c)) for c in cmds),
        "closes": sum(bool(re.search(CLARITY.pattern + r"\s+epoch\s+close\b", c)) for c in cmds),
        "escapes": sum(escapes(t) for t in tools),
        "reads": sum(t["name"] == "Read" for t in tools) + sum(c.lstrip().startswith(READS) for c in cmds),
        "searches": sum(t["name"] in ("Grep", "Glob") for t in tools)
                    + sum(c.lstrip().startswith(SEARCHES) for c in cmds),
        "md_edits": sum(t["name"] in ("Edit", "Write") and
                        str(t["input"].get("file_path", "")).endswith("CLAUDE.md") for t in tools),
        "first_tool": "" if not first else
                      (first["input"].get("command", "")[:120] if first["name"] == "Bash" else first["name"]),
    }


class Bench:
    def __init__(self, out: Path, model: str, grader: str, bypass: bool, blocks=None, checkpoints=None,
                 replicate=1):
        self.out = out.resolve()
        if self.out.is_relative_to(REPO):
            sys.exit(f"--out must be outside {REPO}: an agent that wanders up the tree would find the answers")
        self.replicate = replicate
        self.model, self.grader, self.bypass = model, grader, bypass
        self.results = self.out / "results.jsonl"
        cfg = self.out / "config.json"
        if cfg.exists():  # a run keeps the scenario it started with
            c = json.loads(cfg.read_text())
            blocks, checkpoints, self.replicate = c["blocks"], c["checkpoints"], c.get("replicate", 1)
        elif blocks is None:
            sys.exit(f"{self.out} has no config.json; run build first")
        self.blocks, self.cp_blocks = blocks, checkpoints
        self.scen = scenario.build(blocks, checkpoints)
        self.ckpts = sorted(self.scen.checkpoints)  # in sessions

    def save_config(self):
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "config.json").write_text(json.dumps(
            {"replicate": self.replicate, "blocks": self.blocks, "checkpoints": self.cp_blocks, "model": self.model,
             "grader": self.grader, "bypass": self.bypass,
             "claude_code": sh(["claude", "--version"], check=False).strip(),
             "clarity": sh(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, check=False).strip()}, indent=2))

    # ------------------------------------------------------------- places

    def armdir(self, arm, ckpt=None):
        return self.out / "arms" / (f"ripout-{ckpt}" if arm == "ripout" else arm)

    def project(self, arm, ckpt=None):
        return self.armdir(arm, ckpt) / "project"

    def snap(self, arm, n, ckpt=None):
        return self.armdir(arm, ckpt) / f"snap-{n}.tar"

    def save_snap(self, arm, n, ckpt=None):
        with tarfile.open(self.snap(arm, n, ckpt), "w") as t:
            t.add(self.project(arm, ckpt), arcname="project")
        log(f"snapshot: {arm} after session {n}")

    def restore(self, arm, n, ckpt=None):
        shutil.rmtree(self.project(arm, ckpt), ignore_errors=True)
        with tarfile.open(self.snap(arm, n, ckpt)) as t:
            t.extractall(self.armdir(arm, ckpt), **TRUSTED)

    # ---------------------------------------------------------------- env

    def env(self, arm, ckpt=None, with_clarity=False):
        env = {k: v for k, v in os.environ.items() if k not in SCRUB}
        venv = self.out / ("venv-clarity" if with_clarity else "venv-base")
        paths = env["PATH"].split(":")
        if not with_clarity:  # a globally installed clarity-ctl would leak into the control arms
            paths = [p for p in paths if not (Path(p) / "clarity-ctl").exists()]
        env["PATH"] = ":".join([str(venv / "bin"), *paths])
        env["CLAUDE_CONFIG_DIR"] = str(self.armdir(arm, ckpt) / "cfg")
        env.update(GIT_AUTHOR_NAME="bench", GIT_AUTHOR_EMAIL="bench@example.com",
                   GIT_COMMITTER_NAME="bench", GIT_COMMITTER_EMAIL="bench@example.com")
        if self.bypass:
            env["IS_SANDBOX"] = "1"  # lets the bypass flag run as root inside a container
        return env

    def claude(self, prompt, cwd, env, trace: Path, model=None, tools=None, timeout=2400):
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose",
               "--model", model or self.model, "--no-session-persistence"]
        if tools is not None:
            cmd += ["--tools", tools]
        elif self.bypass:
            cmd += ["--dangerously-skip-permissions"]
        else:
            cmd += ["--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED]
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
            lines, tail = p.stdout.splitlines(), p.stderr[-1000:]
        except subprocess.TimeoutExpired as e:
            lines, tail = (e.stdout or b"").decode(errors="replace").splitlines(), "timeout"
        tools_used, res = [], None
        for line in lines:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "assistant":
                for c in d.get("message", {}).get("content", []):
                    if c.get("type") == "tool_use":
                        tools_used.append({"name": c["name"], "input": c.get("input", {})})
            elif d.get("type") == "result":
                res = d
        trace.parent.mkdir(parents=True, exist_ok=True)
        trace.write_text("\n".join(json.dumps({"name": t["name"], "input": {
            k: (v[:300] if isinstance(v, str) else v) for k, v in t["input"].items()}}) for t in tools_used))
        res = res or {"is_error": True, "result": tail or "no result event", "usage": {}}
        u = res.get("usage") or {}
        return {
            "input": u.get("input_tokens", 0),
            "cache_write": u.get("cache_creation_input_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens", 0),
            "output": u.get("output_tokens", 0),
            "cost_usd": res.get("total_cost_usd", 0.0),
            "turns": res.get("num_turns", 0),
            "seconds": round(time.time() - t0, 1),
            "error": bool(res.get("is_error")),
            "denied": len(res.get("permission_denials") or []),
            "denials": [json.dumps(x.get("tool_input", x))[:160] for x in res.get("permission_denials") or []],
            "result": res.get("result", ""),
            **summarise_tools(tools_used, Path(cwd).resolve(), self.out),
        }

    def record(self, **row):
        with open(self.results, "a") as f:
            f.write(json.dumps(row) + "\n")

    def rows(self):
        if not self.results.exists():
            return []
        return [json.loads(l) for l in self.results.read_text().splitlines() if l.strip()]

    # -------------------------------------------------------------- build

    def build(self):
        self.save_config()
        for venv, pkgs in [("venv-base", ["pytest"]), ("venv-clarity", ["pytest", str(REPO)])]:
            if not (self.out / venv).exists():
                sh(["uv", "venv", "-q", str(self.out / venv)])
                sh(["uv", "pip", "install", "-q", "--python", str(self.out / venv / "bin" / "python"), *pkgs])
        for arm in WORK_ARMS:
            proj = self.project(arm)
            if proj.exists():
                continue
            (self.armdir(arm) / "cfg").mkdir(parents=True)
            proj.mkdir()
            env = self.env(arm, with_clarity=arm == "clarity")
            if arm == "clarity":
                sh(["clarity-ctl", "init", "--objective", scenario.OBJECTIVE], cwd=proj, env=env)
            code = proj / "workspace" / "logstat"
            shutil.copytree(HERE / "seed" / "logstat", code)
            (code / ".gitignore").write_text("__pycache__/\n*.log\n!sample.log\n")
            sh(["git", "init", "-q", "-b", "main"], cwd=code, env=env)
            sh(["git", "add", "-A"], cwd=code, env=env)
            sh(["git", "commit", "-q", "-m", "logstat: first version"], cwd=code, env=env)
            if arm == "clarity":
                sh(["clarity-ctl", "repo", "add", "workspace/logstat"], cwd=proj, env=env)
            else:
                (proj / "CLAUDE.md").write_text(scenario.CLAUDE_MD_RULE if arm == "claudemd"
                                                else scenario.VANILLA_MD)
            log(f"build: {arm} ready")

    # --------------------------------------------------------------- work

    def work(self, arms):
        done = {(r["arm"], r["step"]) for r in self.rows() if r["phase"] == "work"}
        n = len(self.scen.sessions)

        def run(arm):
            env = self.env(arm, with_clarity=arm == "clarity")
            todo = [i for i in range(1, n + 1) if (arm, i) not in done]
            if not todo:
                return
            # Pick up from the last snapshot: probing may have left an earlier state behind.
            prev = [c for c in self.ckpts if c < todo[0] and self.snap(arm, c).exists()]
            if prev and prev[-1] == todo[0] - 1:
                self.restore(arm, prev[-1])
            for i in todo:
                log(f"work: {arm} session {i}/{n}")
                r = self.claude(self.scen.sessions[i - 1], self.project(arm), env,
                                self.out / "traces" / f"work-{arm}-{i}.jsonl")
                self.record(phase="work", arm=arm, step=i, **r)
                if r["error"]:
                    log(f"work: {arm} session {i} errored: {r['result'][:300]}")
                if i in self.ckpts or i == n:
                    self.save_snap(arm, i)

        with ThreadPoolExecutor(len(arms)) as ex:
            list(ex.map(run, [a for a in arms if a in WORK_ARMS]))

    # ------------------------------------------------------------- ripout

    def ripout(self):
        done = {r["ckpt"] for r in self.rows() if r["phase"] == "ripout"}

        def one(c):
            if c in done or not self.snap("clarity", c).exists():
                return
            arm = self.armdir("ripout", c)
            shutil.rmtree(arm, ignore_errors=True)
            (arm / "cfg").mkdir(parents=True)
            with tarfile.open(self.snap("clarity", c)) as t:
                t.extractall(arm, **TRUSTED)
            proj = self.project("ripout", c)
            env = self.env("ripout", c, with_clarity=True)
            code = proj / "workspace" / "logstat"
            wts = [str(p) for p in proj.glob("EPOCHS/**/wt/*") if (p / ".git").is_file()]
            if wts:  # worktree links are absolute; point them at this copy
                sh(["git", "worktree", "repair", *wts], cwd=code, env=env, check=False)
            log(f"ripout: CLAUDE.md from clarity at session {c}")
            r = self.claude(scenario.RIPOUT_PROMPT, proj, env, self.out / "traces" / f"ripout-{c}.jsonl")
            self.record(phase="ripout", arm="ripout", ckpt=c, step="write", **r)
            sh(["clarity-ctl", "install", "--remove"], cwd=proj, env=env, check=False)
            for wt in wts:
                sh(["git", "worktree", "remove", "--force", wt], cwd=code, env=env, check=False)
            sh(["git", "worktree", "prune"], cwd=code, env=env, check=False)
            for name in [".clarity", "EPOCHS", "ARCHIVE", "LEARNINGS", ".git", "worklog.yaml"]:
                p = proj / name
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
            agents = proj / "AGENTS.md"
            if agents.exists() and not agents.read_text().strip():
                agents.unlink()
            left = sh(["grep", "-rli", "clarity", ".", "--exclude-dir=.git"], cwd=proj, check=False)
            if left.strip():
                log(f"ripout {c}: still mentions clarity (left as is): {left.split()}")
            self.save_snap("ripout", c, c)

        with ThreadPoolExecutor(max(1, len(self.ckpts))) as ex:
            list(ex.map(one, self.ckpts))

    # -------------------------------------------------------------- probe

    def probe(self, arms, reps):
        done = {(r["arm"], r["ckpt"], r["step"], r["rep"]) for r in self.rows() if r["phase"] == "probe"}
        last = len(self.scen.sessions)

        def run(arm, ckpts):
            for c in ckpts:
                ck = c if arm == "ripout" else None
                env = self.env(arm, ck, with_clarity=arm == "clarity")
                for p in self.scen.checkpoints[c]:
                    for rep in range(1, reps + 1):
                        if (arm, c, p.id, rep) in done:
                            continue
                        self.restore(arm, c, ck)  # every probe starts from the same state
                        log(f"probe: {arm} @{c} {p.id} #{rep}")
                        r = self.claude(p.q, self.project(arm, ck), env,
                                        self.out / "traces" / f"probe-{arm}-{c}-{p.id}-{rep}.jsonl",
                                        tools="" if p.id == "ok" else None)
                        self.record(phase="probe", arm=arm, ckpt=c, step=p.id, rep=rep, **r)
            if arm != "ripout" and self.snap(arm, last).exists():
                self.restore(arm, last)

        jobs = []
        for arm in arms:
            if arm == "ripout":  # each checkpoint's ripout is its own folder, so they can run in parallel
                jobs += [("ripout", [c]) for c in self.ckpts if self.snap("ripout", c, c).exists()]
            elif arm in WORK_ARMS:
                jobs.append((arm, [c for c in self.ckpts if self.snap(arm, c).exists()]))
        with ThreadPoolExecutor(max(1, len(jobs))) as ex:
            list(ex.map(lambda j: run(*j), jobs))

    # -------------------------------------------------------------- grade

    def grade(self):
        graded = {(r["arm"], r["ckpt"], r["step"], r["rep"]) for r in self.rows() if r["phase"] == "grade"}
        rubric = {(c, p.id): p for c, ps in self.scen.checkpoints.items() for p in ps}
        todo = [r for r in self.rows() if r["phase"] == "probe" and rubric[(r["ckpt"], r["step"])].facts
                and (r["arm"], r["ckpt"], r["step"], r["rep"]) not in graded]
        neutral = self.out / "grader"
        neutral.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k not in SCRUB}
        env["CLAUDE_CONFIG_DIR"] = str(self.out / "grader-cfg")

        def one(r):
            p = rubric[(r["ckpt"], r["step"])]
            prompt = scenario.GRADER.format(q=p.q, answer=r["result"],
                                            facts="\n".join(f"{i}. {f}" for i, f in enumerate(p.facts, 1)))
            g = self.claude(prompt, neutral, env, self.out / "traces" / "grader" /
                            f"{r['arm']}-{r['ckpt']}-{r['step']}-{r['rep']}.jsonl", model=self.grader, tools="")
            try:
                v = json.loads(g["result"].strip().removeprefix("```json").strip("`\n "))
                hits = [bool(h) for h in v["hits"]][:len(p.facts)]
                notes = v.get("notes", "")
            except (ValueError, KeyError, TypeError):
                hits, notes = [], f"unparseable: {g['result'][:200]}"
            score = sum(hits) / len(p.facts) if hits else 0.0
            self.record(phase="grade", arm=r["arm"], ckpt=r["ckpt"], step=r["step"], rep=r["rep"],
                        hits=hits, score=score, notes=notes, cost_usd=g["cost_usd"])
            log(f"grade: {r['arm']} @{r['ckpt']} {r['step']} #{r['rep']} = {score:.2f}")

        with ThreadPoolExecutor(8) as ex:
            list(ex.map(one, todo))


# ------------------------------------------------------------------ report

def ctx(r):
    return r["input"] + r["cache_write"] + r["cache_read"]


def ratio_ci(rows, num, n=2000, seed=0):
    """Sum of num over sum of score, with a 90% bootstrap interval over the rows."""
    def ratio(rs):
        s = sum(r["score"] for r in rs)
        return sum(num(r) for r in rs) / s if s else float("inf")
    rng = random.Random(seed)
    boots = sorted(ratio([rng.choice(rows) for _ in rows]) for _ in range(n))
    return ratio(rows), boots[int(0.05 * n)], boots[int(0.95 * n)]


def fmt_ci(v, lo, hi, money=False):
    def f(x):
        if x == float("inf"):
            return "∞"
        return f"{x:.3f}" if money else f"{x / 1000:,.0f}k"
    return f"{f(v)} ({f(lo)}–{f(hi)})"


def report(outs: list[Path]):
    rows = []
    for o in outs:  # one folder per replicate, or per replicate and arm (as CI runs it)
        bo = Bench(o, "", "", False)
        rows += [dict(r, replicate=bo.replicate) for r in bo.rows()]
    b = Bench(outs[0], "", "", False)
    nrep = len({r["replicate"] for r in rows}) or 1
    cfg = json.loads((b.out / "config.json").read_text())
    graded = {(r["replicate"], r["arm"], r["ckpt"], r["step"], r["rep"]): r["score"]
              for r in rows if r["phase"] == "grade"}
    probes = [dict(r, score=graded.get((r["replicate"], r["arm"], r["ckpt"], r["step"], r["rep"]), 0.0))
              for r in rows if r["phase"] == "probe" and r["step"] != "ok"]
    arms = [a for a in ALL_ARMS if any(r["arm"] == a for r in rows)]

    def med(xs):
        return statistics.median(xs) if xs else 0

    def sel(c, a, step=None):
        return [r for r in probes if r["ckpt"] == c and r["arm"] == a and (step is None or r["step"] == step)]

    out = ["# Token savings", "",
           f"Model `{cfg['model']}`, grader `{cfg['grader']}`, Claude Code {cfg.get('claude_code', '?')}, "
           f"clarity {cfg.get('clarity', '?')}, {nrep} replicate(s), "
           f"{cfg['blocks']} blocks of {scenario.SESSIONS_PER_BLOCK} sessions, "
           f"{'permissions bypassed' if cfg.get('bypass') else 'tool allowlist'}.", "",
           "- **ctx tokens**: everything the model read across all its turns (input + cache write + cache read).",
           "- **per correct answer**: total over every graded probe ÷ total score. Lower is better. "
           "Brackets are a 90% bootstrap interval.", ""]

    # Headline: what it takes to get up to speed at each size.
    out += ["## Tokens to get up to speed, by project size", "",
            "| sessions of history | arm | score | ctx tokens per correct answer | $ per correct answer |",
            "|---|---|---|---|---|"]
    summary = []
    for c in b.ckpts:
        for a in arms:
            rs = sel(c, a)
            if not rs:
                continue
            t = ratio_ci(rs, ctx)
            d = ratio_ci(rs, lambda r: r["cost_usd"])
            sc = statistics.mean(r["score"] for r in rs)
            out.append(f"| {c} | {a} | {sc:.2f} | {fmt_ci(*t)} | {fmt_ci(*d, money=True)} |")
            ok = [r for r in rows if r["phase"] == "probe" and r["ckpt"] == c and r["arm"] == a and r["step"] == "ok"]
            res = sel(c, a, "resume")
            wk = [r for r in rows if r["phase"] == "work" and r["step"] <= c
                  and r["arm"] == ("clarity" if a == "ripout" else a)]
            summary.append(dict(
                sessions=c, arm=a, score=round(sc, 3), probes=len(rs),
                ctx_per_correct=t[0], ctx_lo=t[1], ctx_hi=t[2],
                usd_per_correct=d[0], usd_lo=d[1], usd_hi=d[2],
                resume_ctx=med([ctx(r) for r in res]), resume_usd=med([r["cost_usd"] for r in res]),
                always_loaded_ctx=med([ctx(r) for r in ok]),
                work_usd=sum(r["cost_usd"] for r in wk) / nrep))
    out.append("")

    by = {(s["sessions"], s["arm"]): s for s in summary}
    out += ["## Clarity against each baseline", "",
            "Negative means clarity is cheaper. Score is clarity's minus the baseline's.", "",
            "| sessions | vs | ctx per correct answer | $ per correct answer | score |", "|---|---|---|---|---|"]
    for c in b.ckpts:
        cl = by.get((c, "clarity"))
        for a in ["claudemd", "vanilla", "ripout"]:
            o = by.get((c, a))
            if not (cl and o):
                continue
            rel = lambda k: (f"{cl[k] / o[k] - 1:+.0%}"  # noqa: E731
                             if 0 < o[k] < float("inf") and cl[k] < float("inf") else "n/a")
            out.append(f"| {c} | {a} | {rel('ctx_per_correct')} | {rel('usd_per_correct')} "
                       f"| {cl['score'] - o['score']:+.2f} |")
    out.append("")

    out += ["## What keeping the record costs", "",
            "**Always loaded**: context read by a session that does nothing (the `ok` probe). **Work $**: the "
            "scripted sessions up to that point, mean per replicate (ripout shows the clarity arm's). "
            "**Break-even**: how many fresh-session catch-ups (the `resume` probe) clarity's extra work cost "
            "pays for.", "",
            "| sessions | arm | always loaded | work $ | resume ctx | resume $ | clarity breaks even after |",
            "|---|---|---|---|---|---|---|"]
    for c in b.ckpts:
        cl = by.get((c, "clarity"))
        for a in arms:
            s = by.get((c, a))
            if not s:
                continue
            be = ""
            if cl and a in ("claudemd", "vanilla"):
                extra, saved = cl["work_usd"] - s["work_usd"], s["resume_usd"] - cl["resume_usd"]
                be = ("never: catch-up isn't cheaper" if saved <= 0 else
                      "from the start" if extra <= 0 else f"{extra / saved:.0f} catch-ups")
            out.append(f"| {c} | {a} | {s['always_loaded_ctx']:,.0f} | {s['work_usd']:.2f} "
                       f"| {s['resume_ctx']:,.0f} | {s['resume_usd']:.3f} | {be} |")
    out.append("")

    out += ["## How the agents behaved", "",
            "Probes: median tool calls, reads and searches per question, and how often the first tool call "
            "was clarity. Work: per session, clarity notes, epoch closes and CLAUDE.md edits.", "",
            "| arm | probe tool calls | reads | searches | first call is clarity | notes/session "
            "| closes/session | CLAUDE.md edits/session | denied calls | escapes |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for a in arms:
        pr = [r for r in probes if r["arm"] == a]
        wk = [r for r in rows if r["phase"] == "work" and r["arm"] == a]
        n = max(1, len(wk))
        first = sum(bool(CLARITY.search(r.get("first_tool", ""))) for r in pr) / max(1, len(pr))
        out.append(f"| {a} | {med([r.get('tool_calls', 0) for r in pr]):.0f} "
                   f"| {med([r.get('reads', 0) for r in pr]):.0f} | {med([r.get('searches', 0) for r in pr]):.0f} "
                   f"| {first:.0%} | {sum(r.get('notes', 0) for r in wk) / n:.2f} "
                   f"| {sum(r.get('closes', 0) for r in wk) / n:.2f} | {sum(r.get('md_edits', 0) for r in wk) / n:.2f} "
                   f"| {sum(r['denied'] for r in rows if r['arm'] == a and r['phase'] in ('work', 'probe'))} "
                   f"| {sum(r.get('escapes', 0) for r in rows if r['arm'] == a and r['phase'] in ('work', 'probe'))} |")
    out += ["", "**escapes** counts tool calls that reached outside the arm's own project, into other arms, "
            "the results or this repo. Anything above zero needs a look at the traces before the numbers "
            "are trusted.", ""]

    for c in b.ckpts:
        out += [f"## Each probe after {c} sessions", "", "Each cell: mean score · median ctx tokens.", "",
                "| probe | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
        for p in b.scen.checkpoints[c]:
            if p.id == "ok":
                continue
            cells = [f"{statistics.mean(r['score'] for r in rs):.2f} · {med([ctx(r) for r in rs]) / 1000:,.0f}k"
                     if (rs := sel(c, a, p.id)) else "—" for a in arms]
            out.append(f"| `{p.id}` | " + " | ".join(cells) + " |")
        out.append("")

    out += ["## Grader notes on answers that missed something", ""]
    out += [f"- **{r['arm']} @{r['ckpt']} `{r['step']}`** {r['replicate']}#{r['rep']} ({r['score']:.2f}): {r['notes']}"
            for r in rows if r["phase"] == "grade" and r["score"] < 1]

    dest = outs[0].resolve() if len(outs) == 1 else outs[0].resolve().parent
    (dest / "report.md").write_text("\n".join(out) + "\n")
    with open(dest / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]) if summary else ["sessions"])
        w.writeheader()
        w.writerows(summary)
    log(f"report: {dest / 'report.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["all", "build", "work", "ripout", "probe", "grade", "report"])
    ap.add_argument("--out", type=Path, action="append", required=True,
                    help="run folder, outside this repo; reusing one resumes it. report takes several")
    ap.add_argument("--blocks", type=int, default=8, help=f"{scenario.SESSIONS_PER_BLOCK} sessions each")
    ap.add_argument("--checkpoints", default="1,3,8", help="probe after these blocks")
    ap.add_argument("--model", default="claude-sonnet-5-5", help="model for work and probes")
    ap.add_argument("--grader", default="claude-sonnet-5-5")
    ap.add_argument("--arms", default=",".join(ALL_ARMS))
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--replicate", type=int, default=1, help="which replicate this folder is, for combining")
    ap.add_argument("--bypass", action="store_true",
                    help="skip permission checks; only in a throwaway container or CI runner")
    a = ap.parse_args()
    if a.phase == "report":
        return report(a.out)
    if len(a.out) > 1:
        sys.exit("only report takes more than one --out")
    b = Bench(a.out[0], a.model, a.grader, a.bypass, a.blocks, [int(x) for x in a.checkpoints.split(",")],
              a.replicate)
    arms = a.arms.split(",")
    phases = ["build", "work", "ripout", "probe", "grade"] if a.phase == "all" else [a.phase]
    for ph in phases:
        if ph == "build":
            b.build()
        elif ph == "work":
            b.work(arms)
        elif ph == "ripout" and "ripout" in arms:
            b.ripout()
        elif ph == "probe":
            b.probe(arms, a.reps)
        elif ph == "grade":
            b.grade()
    if a.phase == "all":
        report(a.out)


if __name__ == "__main__":
    main()
