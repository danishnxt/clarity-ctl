"""Shared paths, environment scrubbing, claude command line and box creation for the meterbill eval.

Layout of a box (cwd of every session, NOT a git repo):
    <box>/workspace/meterbill/   code repo (git), committed by the harness only
    <box>/...                    the arm's memory files (CLAUDE.md, or clarity-ctl init output)
"""
from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
MB = HERE.parent                                    # eval/meterbill (story.yaml, arms.md, tasks/, harness/, results/)
RESULTS = MB / "results"
STORY = MB / "story.yaml"
ARMS_MD = MB / "arms.md"
SCRATCH = Path(os.environ.get("MB_SCRATCH") or Path(os.environ.get("TMPDIR", "/tmp")) / "meterbill-eval")
VENV = SCRATCH / "venv"
BUILD_BOX = SCRATCH / "build" / "box"
BUILD_REPO = BUILD_BOX / "workspace" / "meterbill"
CLAUDE = os.environ.get("CLAUDE_BIN") or shutil.which("claude") or "claude"   # resolved before PATH is scrubbed

ARMS = ("nothing", "claudemd", "clarity")
GIT_ID = {"GIT_AUTHOR_NAME": "eval", "GIT_AUTHOR_EMAIL": "eval@example.invalid",
          "GIT_COMMITTER_NAME": "eval", "GIT_COMMITTER_EMAIL": "eval@example.invalid"}
EXCLUDE = "__pycache__/\n*.pyc\n.pytest_cache/\n.DS_Store\n"
LIMIT_WORDS = ("usage limit", "limit reached", "rate limit", "quota")
TOOLS = ["Bash", "Read", "Edit", "Write", "Grep", "Glob"]
DISALLOWED = ["Agent", "Task", "WebFetch", "WebSearch"]


def jsonl_file(p: Path) -> Path | None:
    """`p` names a transcript as `x.jsonl`; returns it or `x.jsonl.gz` (the published results are gzipped), else None."""
    p = Path(p)
    for q in (p, p.with_name(p.name + ".gz")):
        if q.exists():
            return q
    return None


def read_jsonl(p: Path) -> str:
    """Text of a transcript given as `x.jsonl`, whether it is stored plain or as `x.jsonl.gz`."""
    q = jsonl_file(p)
    if q is None:
        raise FileNotFoundError(p)
    return gzip.open(q, "rt", encoding="utf-8").read() if q.suffix == ".gz" else q.read_text()


def sh(*cmd, **kw) -> subprocess.CompletedProcess:
    kw.setdefault("env", {**os.environ, **GIT_ID})
    return subprocess.run(cmd, check=kw.pop("check", True), text=True, capture_output=True, **kw)


def story() -> dict:
    return yaml.safe_load(STORY.read_text())


def claudemd_seed() -> str:
    """The claudemd seed: the indented block under '## claudemd seed' in arms.md, dedented."""
    lines = ARMS_MD.read_text().splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("## claudemd seed"))
    out, started = [], False
    for l in lines[i + 1:]:
        if l.startswith("    "):
            started = True
            out.append(l[4:])
        elif started and not l.strip():
            out.append("")
        elif started:
            break
    return "\n".join(out).rstrip() + "\n"


def setup_venv() -> None:
    """venv with pytest; its `pytest` is a wrapper for `python -m pytest`, so the repo root is importable
    (the project has no pytest config; a bare console-script pytest would not find the package)."""
    pytest_bin = VENV / "bin" / "pytest"
    if not pytest_bin.exists():
        SCRATCH.mkdir(parents=True, exist_ok=True)
        sh("uv", "venv", "--python", "3.12", str(VENV))
        sh("uv", "pip", "install", "--python", str(VENV / "bin" / "python"), "pytest")
    if "python -m pytest" not in pytest_bin.read_text(errors="ignore"):
        pytest_bin.write_text('#!/bin/sh\nexec "$(dirname "$0")/python" -m pytest "$@"\n')
        pytest_bin.chmod(0o755)


def has_clarity(entry: str) -> bool:
    p = Path(entry) / "clarity-ctl"
    return p.exists() and os.access(p, os.X_OK)


def env_for(arm: str | None) -> dict:
    """Session environment. arm=None is a builder session (no clarity-ctl). The venv's bin is first on PATH."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLARITY_")}
    entries = [e for e in env.get("PATH", "").split(":") if e]
    if arm != "clarity":
        entries = [e for e in entries if not has_clarity(e)]
    env["PATH"] = ":".join([str(VENV / "bin")] + [e for e in entries if e != str(VENV / "bin")])
    env["VIRTUAL_ENV"] = str(VENV)
    env.update(GIT_ID)
    env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"      # auto-memory must not act as a hidden fourth memory
    return env


def claude_cmd(prompt: str, tools: list[str] = TOOLS, append_system: str | None = None) -> list[str]:
    cmd = [CLAUDE, "-p", "--model", "sonnet", "--setting-sources", "project,local", "--strict-mcp-config",
           "--no-session-persistence", "--output-format", "stream-json", "--verbose",
           "--allowedTools", *tools, "--disallowedTools", *DISALLOWED]
    if append_system:
        cmd += ["--append-system-prompt", append_system]
    return cmd + ["--", prompt]


def result_event(stdout: str) -> dict | None:
    for line in reversed(stdout.splitlines()):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            return ev
    return None


def _add_nums(a, b):
    """Recursive sum of two usage dicts: numbers add, nested dicts recurse, anything else takes the later value."""
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, bool) or v is None:
            out[k] = v
        elif isinstance(v, (int, float)) and isinstance(out.get(k), (int, float)) and not isinstance(out.get(k), bool):
            out[k] = out[k] + v
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _add_nums(out[k], v)
        else:
            out[k] = v
    return out


def session_result(stdout: str) -> dict | None:
    """The session's totals over ALL `result` events. A backgrounded Bash command's completion notification can wake
    the session for another turn after it finished, which emits a second result event. Per result event, `usage`,
    `num_turns` and `duration_ms` cover only that stretch, so they are summed. `total_cost_usd` (and `modelUsage`) are
    cumulative over the session already (second event = first + its own stretch), so the LAST value is the total;
    summing it would double count. Everything else comes from the last event."""
    evs = []
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "result":
            evs.append(ev)
    if not evs:
        return None
    out = dict(evs[-1])
    usage: dict = {}
    for ev in evs:
        usage = _add_nums(usage, ev.get("usage") or {})
    out["usage"] = usage
    for k in ("num_turns", "duration_ms", "duration_api_ms"):
        if any(ev.get(k) is not None for ev in evs):
            out[k] = sum(ev.get(k) or 0 for ev in evs)
    out["result_events"] = len(evs)
    return out


def hit_limit(ev: dict | None, stderr: str = "") -> bool:
    blob = (json.dumps(ev) if ev and ev.get("is_error") else "") + stderr
    return any(w in blob.lower().replace("_", " ") for w in LIMIT_WORDS)   # underscores read as spaces


def run_claude(cmd: list[str], cwd: Path, env: dict, timeout: int) -> tuple[str, str, int, float]:
    """Run one session; returns (stdout, stderr, returncode, wall seconds). Timeout -> rc -1, stderr 'TIMEOUT'."""
    import time
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
        out, err, rc = p.stdout, p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        err, rc = "TIMEOUT", -1
    return out, err, rc, time.time() - t0


def init_clarity(box: Path) -> None:
    env = env_for("clarity")
    sh("clarity-ctl", "init", "--name", "meterbill", "--objective",
       "Usage-billing library: metered events to invoices", cwd=box, env=env)


def arm_memory(arm: str, box: Path) -> None:
    """Write the arm's memory files at <box>/. Must run before workspace/meterbill exists (clarity init order).

    Note: `clarity-ctl init` runs `git init` in the box, so the clarity box is a git repo that tracks only
    clarity's own files (its .gitignore ignores workspace/); the code repo stays a separate nested repo.
    """
    if arm == "claudemd":
        (box / "CLAUDE.md").write_text(claudemd_seed())
    elif arm == "clarity":
        init_clarity(box)
    elif arm != "nothing":
        raise ValueError(arm)


CLARITY_OBJECTIVE = ("Usage-billing library (Python 3.12, stdlib only): metered events to invoices. "
                     "Code: workspace/meterbill")


def set_clarity_location(box: Path) -> None:
    """Give the clarity box the same code-location fact the claudemd seed carries (amended in arms.md).

    clarity's .gitignore ignores everything but its own files, so root-level Glob/Grep skip workspace/;
    the objective is the one place its memory can say where the code is. Must run after any memory
    snapshot is restored, since the snapshot's worklog holds the old objective.
    """
    sh("clarity-ctl", "objective", CLARITY_OBJECTIVE, cwd=box, env=env_for("clarity"))


def make_box_at(arm: str, code_tag: str, box: Path) -> Path:
    """Build a box at an exact path (must not exist yet)."""
    box.mkdir(parents=True)
    arm_memory(arm, box)
    clone_code(box, code_tag)
    return box


def make_box(arm: str, code_tag: str, parent: Path | None = None) -> Path:
    """A fresh box: arm memory files at <box>/, the build repo's history up to code_tag at workspace/meterbill."""
    parent = parent or SCRATCH / "boxes"
    parent.mkdir(parents=True, exist_ok=True)
    box = Path(tempfile.mkdtemp(prefix=f"{arm}-{code_tag}-", dir=parent))
    box.rmdir()
    make_box_at(arm, code_tag, box)
    if arm == "clarity":
        set_clarity_location(box)
    return box


# --- memory snapshots: what the replay writes and the task boxes start from -------------------------
MEMORY = RESULTS / "memory"
MEMORY_PATHS = {
    "nothing": [],
    "claudemd": ["CLAUDE.md"],
    "clarity": ["worklog.yaml", "AGENTS.md", "CLAUDE.md", "EPOCHS", "LEARNINGS", ".clarity"],
}
MEMORY_SKIP = {"cache", "worklog.lock", ".DS_Store"}     # clarity runtime files, not memory


def mem_tag(at: str) -> str:
    """Directory name of a checkpoint's memory snapshot: e8 -> e08, e16 -> e16."""
    return f"e{int(at[1:]):02d}"


def snapshot_memory(arm: str, box: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for rel in MEMORY_PATHS[arm]:
        src = box / rel
        if src.is_dir():
            shutil.copytree(src, dest / rel, ignore=shutil.ignore_patterns(*MEMORY_SKIP))
        elif src.exists():
            shutil.copy2(src, dest / rel)


def restore_memory(arm: str, box: Path, src: Path) -> None:
    """Make the box's memory files exactly the snapshot (paths in the snapshot list are replaced)."""
    for rel in MEMORY_PATHS[arm]:
        dst = box / rel
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        if (src / rel).is_dir():
            shutil.copytree(src / rel, dst)
        elif (src / rel).exists():
            shutil.copy2(src / rel, dst)


def replay_template() -> str:
    """The replay prompt of arms.md: the indented block under '## replay prompt', dedented."""
    lines = ARMS_MD.read_text().splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("## replay prompt"))
    out = []
    for l in lines[i + 1:]:
        if l.startswith("## "):
            break
        out.append(l[4:] if l.startswith("    ") else l)
    return "\n".join(out).strip("\n") + "\n"


def clone_code(box: Path, code_tag: str) -> Path:
    """Copy the build repo's history up to code_tag into <box>/workspace/meterbill, on branch main.

    Same commit hashes as a clone reset to the tag, but later commits, tags and the origin remote are
    not copied, so `git log --all` and `git tag` show nothing from after code_tag.
    """
    dest = box / "workspace" / "meterbill"
    dest.mkdir(parents=True)
    sh("git", "init", "-q", "-b", "unborn", cwd=dest)
    sh("git", "fetch", "-q", "--no-tags", str(BUILD_REPO), f"refs/tags/{code_tag}:refs/heads/main", cwd=dest)
    sh("git", "checkout", "-q", "main", cwd=dest)
    sh("git", "branch", "-q", "-D", "unborn", cwd=dest, check=False)
    (dest / ".git" / "info" / "exclude").write_text(EXCLUDE)
    return dest
