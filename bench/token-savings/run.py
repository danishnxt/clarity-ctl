#!/usr/bin/env python3
"""How many tokens does it take a fresh session to get up to speed, with and without clarity?

    python3 bench/token-savings/run.py all --out /tmp/bench

Phases, each resumable on its own (`build`, `work`, `ripout`, `probe`, `grade`, `report`):

  build   lay out one project per arm from seed/, plus a venv for the agent's tools
  work    run the scripted sessions in scenario.SESSIONS, one fresh `claude -p` each
  ripout  copy the clarity arm, have Claude write CLAUDE.md from clarity, delete clarity
  probe   restore each arm's final state and ask every probe in a fresh session, --reps times
  grade   score each probe answer against its rubric with a separate Claude call
  report  write report.md: tokens, cost, turns and score per arm and probe

Arms:
  clarity   clarity-ctl initialised; its AGENTS.md block is all the agent is told
  claudemd  no clarity; CLAUDE.md tells the agent to keep CLAUDE.md current
  vanilla   no clarity; CLAUDE.md only names the objective — stock Claude Code
  ripout    clarity's final state, turned into CLAUDE.md by Claude, then clarity removed

Every call runs with a private CLAUDE_CONFIG_DIR per arm and the calling session's
own environment scrubbed, so nothing outside the arm's folder leaks into its context.
Tools are limited to ALLOWED instead of skipping permission checks.
"""

from __future__ import annotations

import argparse
import json
import os
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

# Set by the session that launches us; any of them can pull that session's context in.
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

SCRUB = [
    "CLAUDECODE", "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "CLAUDE_ADDITIONAL_DIRECTORIES",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_TEE_SDK_STDOUT",
    "CLAUDE_PID", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_AFTER_LAST_COMPACT", "VIRTUAL_ENV",
]


# Our own snapshots, worktree links included; the default filter would strip them on 3.14.
TRUSTED = {"filter": "fully_trusted"} if hasattr(tarfile, "fully_trusted_filter") else {}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def sh(cmd, cwd=None, env=None, check=True):
    return subprocess.run(cmd, cwd=cwd, env=env, check=check, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout


class Bench:
    def __init__(self, out: Path, model: str, grader: str):
        self.out = out.resolve()
        self.model = model
        self.grader = grader
        self.results = self.out / "results.jsonl"

    def arm(self, name):
        return self.out / "arms" / name

    def project(self, name):
        return self.arm(name) / "project"

    # ---------------------------------------------------------------- env

    def env(self, arm: str, with_clarity: bool):
        env = {k: v for k, v in os.environ.items() if k not in SCRUB}
        venv = self.out / ("venv-clarity" if with_clarity else "venv-base")
        env["PATH"] = f"{venv / 'bin'}:{env['PATH']}"
        if not with_clarity:  # a globally installed clarity-ctl would leak into the control arms
            env["PATH"] = ":".join(p for p in env["PATH"].split(":")
                                   if not (Path(p) / "clarity-ctl").exists() or p == str(venv / "bin"))
        env["CLAUDE_CONFIG_DIR"] = str(self.arm(arm) / "cfg")
        for k, v in [("GIT_AUTHOR_NAME", "bench"), ("GIT_AUTHOR_EMAIL", "bench@example.com"),
                     ("GIT_COMMITTER_NAME", "bench"), ("GIT_COMMITTER_EMAIL", "bench@example.com")]:
            env[k] = v
        return env

    def claude(self, prompt, cwd, env, model=None, tools=None, timeout=1800):
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--model", model or self.model,
               "--no-session-persistence"]
        if tools is not None:
            cmd += ["--tools", tools]
        else:
            cmd += ["--permission-mode", "acceptEdits", "--allowedTools", *ALLOWED]
        t0 = time.time()
        p = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout)
        try:
            d = json.loads(p.stdout)
        except json.JSONDecodeError:
            d = {"is_error": True, "result": (p.stdout + p.stderr)[-2000:], "usage": {}}
        u = d.get("usage") or {}
        return {
            "input": u.get("input_tokens", 0),
            "cache_write": u.get("cache_creation_input_tokens", 0),
            "cache_read": u.get("cache_read_input_tokens", 0),
            "output": u.get("output_tokens", 0),
            "cost_usd": d.get("total_cost_usd", 0.0),
            "turns": d.get("num_turns", 0),
            "seconds": round(time.time() - t0, 1),
            "error": bool(d.get("is_error")),
            "denied": len(d.get("permission_denials") or []),
            "denials": [json.dumps(x.get("tool_input", x))[:160] for x in d.get("permission_denials") or []],
            "result": d.get("result", ""),
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
        self.out.mkdir(parents=True, exist_ok=True)
        for venv, pkgs in [("venv-base", ["pytest"]), ("venv-clarity", ["pytest", "-e", str(REPO)])]:
            if not (self.out / venv).exists():
                sh(["uv", "venv", "-q", str(self.out / venv)])
                sh(["uv", "pip", "install", "-q", "--python", str(self.out / venv / "bin" / "python"), *pkgs])
        for arm in WORK_ARMS:
            proj = self.project(arm)
            if proj.exists():
                log(f"build: {arm} exists, keeping it")
                continue
            (self.arm(arm) / "cfg").mkdir(parents=True)
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
            elif arm == "claudemd":
                (proj / "CLAUDE.md").write_text(scenario.CLAUDE_MD_RULE)
            else:
                (proj / "CLAUDE.md").write_text(scenario.VANILLA_MD)
            log(f"build: {arm} ready at {proj}")

    # --------------------------------------------------------------- work

    def work(self, arms, sessions):
        done = {(r["arm"], r["step"]) for r in self.rows() if r["phase"] == "work"}

        def run(arm):
            env = self.env(arm, with_clarity=arm == "clarity")
            for i, prompt in enumerate(scenario.SESSIONS[:sessions], 1):
                if (arm, i) in done:
                    continue
                log(f"work: {arm} session {i}/{sessions}")
                r = self.claude(prompt, self.project(arm), env)
                self.record(phase="work", arm=arm, step=i, **r)
                if r["error"]:
                    log(f"work: {arm} session {i} errored: {r['result'][:300]}")
            self.snapshot(arm)

        with ThreadPoolExecutor(len(arms)) as ex:
            list(ex.map(run, [a for a in arms if a in WORK_ARMS]))

    def snapshot(self, arm):
        with tarfile.open(self.arm(arm) / "final.tar", "w") as t:
            t.add(self.project(arm), arcname="project")
        log(f"snapshot: {arm}")

    def restore(self, arm):
        shutil.rmtree(self.project(arm), ignore_errors=True)
        with tarfile.open(self.arm(arm) / "final.tar") as t:
            t.extractall(self.arm(arm), **TRUSTED)

    # ------------------------------------------------------------- ripout

    def ripout(self):
        src = self.arm("clarity") / "final.tar"
        if not src.exists():
            sys.exit("ripout needs the clarity arm's work phase first")
        arm = self.arm("ripout")
        shutil.rmtree(arm, ignore_errors=True)
        (arm / "cfg").mkdir(parents=True)
        with tarfile.open(src) as t:
            t.extractall(arm, **TRUSTED)
        proj = self.project("ripout")
        env = self.env("ripout", with_clarity=True)
        code = proj / "workspace" / "logstat"
        wts = [str(p) for p in proj.glob("EPOCHS/**/wt/*") if (p / ".git").is_file()]
        if wts:  # worktree links are absolute; point them at this copy
            sh(["git", "worktree", "repair", *wts], cwd=code, env=env, check=False)

        log("ripout: Claude writes CLAUDE.md from clarity")
        r = self.claude(scenario.RIPOUT_PROMPT, proj, env)
        self.record(phase="ripout", arm="ripout", step=1, **r)

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
            log(f"ripout: still mentions clarity (left as is):\n{left}")
        self.snapshot("ripout")

    # -------------------------------------------------------------- probe

    def probe(self, arms, reps):
        done = {(r["arm"], r["step"], r["rep"]) for r in self.rows() if r["phase"] == "probe"}

        def run(arm):
            env = self.env(arm, with_clarity=arm == "clarity")
            for p in scenario.PROBES:
                for rep in range(1, reps + 1):
                    if (arm, p["id"], rep) in done:
                        continue
                    self.restore(arm)  # every probe starts from the same final state
                    log(f"probe: {arm} {p['id']} #{rep}")
                    r = self.claude(p["q"], self.project(arm), env,
                                    tools="" if p["id"] == "ok" else None)
                    self.record(phase="probe", arm=arm, step=p["id"], rep=rep, **r)
            self.restore(arm)

        arms = [a for a in arms if (self.arm(a) / "final.tar").exists()]
        with ThreadPoolExecutor(max(1, len(arms))) as ex:
            list(ex.map(run, arms))

    # -------------------------------------------------------------- grade

    def grade(self):
        graded = {(r["arm"], r["step"], r["rep"]) for r in self.rows() if r["phase"] == "grade"}
        rubric = {p["id"]: p for p in scenario.PROBES}
        todo = [r for r in self.rows() if r["phase"] == "probe" and rubric[r["step"]]["facts"]
                and (r["arm"], r["step"], r["rep"]) not in graded]
        neutral = self.out / "grader"
        neutral.mkdir(exist_ok=True)
        env = {k: v for k, v in os.environ.items() if k not in SCRUB}
        env["CLAUDE_CONFIG_DIR"] = str(self.out / "grader-cfg")

        def one(r):
            p = rubric[r["step"]]
            prompt = scenario.GRADER.format(q=p["q"], answer=r["result"],
                                            facts="\n".join(f"{i}. {f}" for i, f in enumerate(p["facts"], 1)))
            g = self.claude(prompt, neutral, env, model=self.grader, tools="")
            try:
                v = json.loads(g["result"].strip().removeprefix("```json").strip("`\n "))
                hits = [bool(h) for h in v["hits"]][:len(p["facts"])]
                notes = v.get("notes", "")
            except (ValueError, KeyError, TypeError):
                hits, notes = [], f"unparseable: {g['result'][:200]}"
            score = sum(hits) / len(p["facts"]) if hits else 0.0
            self.record(phase="grade", arm=r["arm"], step=r["step"], rep=r["rep"],
                        hits=hits, score=score, notes=notes, cost_usd=g["cost_usd"])
            log(f"grade: {r['arm']} {r['step']} #{r['rep']} = {score:.2f}")

        with ThreadPoolExecutor(6) as ex:
            list(ex.map(one, todo))

    # ------------------------------------------------------------- report

    def report(self):
        rows = self.rows()
        med = lambda xs: statistics.median(xs) if xs else 0  # noqa: E731
        ctx = lambda r: r["input"] + r["cache_write"] + r["cache_read"]  # noqa: E731
        arms = [a for a in ALL_ARMS if any(r["arm"] == a for r in rows)]
        scores = {(r["arm"], r["step"], r["rep"]): r["score"] for r in rows if r["phase"] == "grade"}
        out = [f"# Token savings: {self.out.name}", "",
               f"Model `{self.model}`, grader `{self.grader}`. Each cell is the median over reps.",
               "**ctx** = input + cache write + cache read tokens, everything the model read across "
               "all its turns. **score** = share of rubric facts the answer got right.", ""]

        for p in scenario.PROBES:
            out += [f"## Probe `{p['id']}`", "", f"> {p['q']}", "",
                    "| arm | score | ctx tokens | output | cost $ | turns | errors | denied |",
                    "|---|---|---|---|---|---|---|---|"]
            for a in arms:
                rs = [r for r in rows if r["phase"] == "probe" and r["arm"] == a and r["step"] == p["id"]]
                if not rs:
                    continue
                sc = [scores[(a, p["id"], r["rep"])] for r in rs if (a, p["id"], r["rep"]) in scores]
                out.append(f"| {a} | {f'{statistics.mean(sc):.2f}' if sc else '—'} | {med([ctx(r) for r in rs]):,.0f} "
                           f"| {med([r['output'] for r in rs]):,.0f} | {med([r['cost_usd'] for r in rs]):.3f} "
                           f"| {med([r['turns'] for r in rs]):.0f} | {sum(r['error'] for r in rs)} "
                           f"| {sum(r.get('denied', 0) for r in rs)} |")
            out.append("")

        out += ["## Getting up to speed, all graded probes together", "",
                "Cost per correct answer = total probe cost ÷ total score. Lower is better.", "",
                "| arm | mean score | total ctx tokens | total cost $ | $ per correct answer |",
                "|---|---|---|---|---|"]
        for a in arms:
            rs = [r for r in rows if r["phase"] == "probe" and r["arm"] == a and r["step"] != "ok"]
            sc = [scores.get((a, r["step"], r["rep"]), 0) for r in rs]
            cost = sum(r["cost_usd"] for r in rs)
            out.append(f"| {a} | {statistics.mean(sc) if sc else 0:.2f} | {sum(ctx(r) for r in rs):,} "
                       f"| {cost:.2f} | {cost / sum(sc) if sum(sc) else float('inf'):.3f} |")

        out += ["", "## What keeping the record cost during the work", "",
                "| arm | sessions | ctx tokens | output | cost $ | turns | errors | denied |",
                "|---|---|---|---|---|---|---|---|"]
        for a in arms:
            rs = [r for r in rows if r["phase"] in ("work", "ripout") and r["arm"] == a]
            if rs:
                out.append(f"| {a} | {len(rs)} | {sum(ctx(r) for r in rs):,} | {sum(r['output'] for r in rs):,} "
                           f"| {sum(r['cost_usd'] for r in rs):.2f} | {sum(r['turns'] for r in rs)} "
                           f"| {sum(r['error'] for r in rs)} | {sum(r.get('denied', 0) for r in rs)} |")
        out += ["", "ripout's row is only the CLAUDE.md-writing session; its work is the clarity arm's.", ""]

        out += ["## Grader notes", ""]
        for r in rows:
            if r["phase"] == "grade" and r["score"] < 1:
                out.append(f"- **{r['arm']} / {r['step']} #{r['rep']}** ({r['score']:.2f}): {r['notes']}")
        (self.out / "report.md").write_text("\n".join(out) + "\n")
        log(f"report: {self.out / 'report.md'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("phase", choices=["all", "build", "work", "ripout", "probe", "grade", "report"])
    ap.add_argument("--out", type=Path, required=True, help="run folder; reusing one resumes it")
    ap.add_argument("--model", default="claude-sonnet-5-5", help="model for work and probes")
    ap.add_argument("--grader", default="claude-sonnet-5-5")
    ap.add_argument("--arms", default=",".join(ALL_ARMS))
    ap.add_argument("--sessions", type=int, default=len(scenario.SESSIONS), help="run only the first N sessions")
    ap.add_argument("--reps", type=int, default=3)
    a = ap.parse_args()
    b = Bench(a.out, a.model, a.grader)
    arms = a.arms.split(",")
    phases = ["build", "work", "ripout", "probe", "grade", "report"] if a.phase == "all" else [a.phase]
    for ph in phases:
        if ph == "build":
            b.build()
        elif ph == "work":
            b.work(arms, a.sessions)
        elif ph == "ripout" and "ripout" in arms:
            b.ripout()
        elif ph == "probe":
            b.probe(arms, a.reps)
        elif ph == "grade":
            b.grade()
        elif ph == "report":
            b.report()


if __name__ == "__main__":
    main()
