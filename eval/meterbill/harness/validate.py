"""Validate the hidden tests and patches of each task against the e8 code.

    python validate.py --at e16 [T1 T2 ...]      # tasks live in tasks/<checkpoint>/<ID>/

For each task, in a fresh copy of the e8 tree every time:
  (a) unchanged tree        : target tests FAIL; keep tests and the visible suite PASS
  (b) reference.patch       : everything passes
  (c) each traps/<name>.patch: target tests PASS and at least one keep (trap) test FAILS
Hidden tests live in tasks/<ID>/hidden/; test_target*.py are target tests, test_keep*.py are keep/trap tests.
They run from <tree>/_hidden/ with `python -m pytest`, so they import the tree's meterbill package.
Exit 1 if any row is not as expected.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from common import MB, SCRATCH, VENV, clone_code, env_for, setup_venv, sh



def run_pytest(tree: Path, target: str, junit: Path | None = None) -> tuple[int, dict[str, bool]]:
    cmd = [str(VENV / "bin" / "python"), "-m", "pytest", target, "-q", "-p", "no:cacheprovider"]
    if junit:
        cmd.append(f"--junitxml={junit}")
    p = sh(*cmd, cwd=tree, env=env_for(None), check=False)
    results: dict[str, bool] = {}
    if junit and junit.exists():
        for case in ET.parse(junit).getroot().iter("testcase"):
            results[f"{case.get('classname', '').split('.')[-1]}::{case.get('name')}"] = not (
                case.find("failure") is not None or case.find("error") is not None)
    return p.returncode, results


def fresh_tree(at: str, task: str, patch: Path | None) -> Path:
    parent = SCRATCH / "validate"
    parent.mkdir(parents=True, exist_ok=True)
    box = Path(tempfile.mkdtemp(prefix=f"{task}-", dir=parent))
    tree = clone_code(box, at)
    if patch:
        sh("git", "apply", "--whitespace=nowarn", str(patch), cwd=tree)
    hidden = tree / "_hidden"
    shutil.copytree(MB / "tasks" / at / task / "hidden", hidden)
    (tree / ".git" / "info" / "exclude").open("a").write("_hidden/\n")
    return tree


def evaluate(at: str, task: str, scenario: str, patch: Path | None) -> dict:
    tree = fresh_tree(at, task, patch)
    try:
        vis_rc, _ = run_pytest(tree, "tests")
        _, res = run_pytest(tree, "_hidden", tree / "junit.xml")
    finally:
        shutil.rmtree(tree.parent.parent, ignore_errors=True)       # the box
    target = {k: v for k, v in res.items() if k.startswith("test_target")}
    keep = {k: v for k, v in res.items() if k.startswith("test_keep")}
    return {"task": task, "scenario": scenario, "visible": vis_rc == 0,
            "target_pass": bool(target) and all(target.values()), "target_n": len(target),
            "keep_pass": all(keep.values()) if keep else True, "keep_n": len(keep),
            "keep_failed": sorted(k for k, v in keep.items() if not v),
            "target_failed": sorted(k for k, v in target.items() if not v)}


def ok(r: dict, kind: str) -> bool:
    if kind == "unchanged":
        return not r["target_pass"] and r["target_n"] > 0 and r["keep_pass"] and r["visible"]
    if kind == "reference":
        return r["target_pass"] and r["keep_pass"] and r["visible"]
    return r["target_pass"] and not r["keep_pass"]          # trap


def main() -> None:
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        return
    setup_venv()
    SCRATCH.mkdir(parents=True, exist_ok=True)
    args = sys.argv[1:]
    at = "e8"
    if args[:1] == ["--at"]:
        at, args = args[1], args[2:]
    tasks = args or sorted(p.name for p in (MB / "tasks" / at).iterdir() if p.is_dir())
    rows = []
    for task in tasks:
        d = MB / "tasks" / at / task
        plan = [("unchanged", "unchanged", None)]
        if (d / "reference.patch").exists():
            plan.append(("reference", "reference.patch", d / "reference.patch"))
        for tp in sorted((d / "traps").glob("*.patch")) if (d / "traps").is_dir() else []:
            plan.append(("trap", f"trap {tp.stem}", tp))
        for kind, name, patch in plan:
            r = evaluate(at, task, name, patch)
            r["ok"], r["kind"] = ok(r, kind), kind
            rows.append(r)
    mark = lambda b: "PASS" if b else "FAIL"
    print(f"{'task':4} {'scenario':26} {'visible':7} {'target':7} {'keep':7} {'as expected':11}  failing keep tests")
    for r in rows:
        print(f"{r['task']:4} {r['scenario']:26} {mark(r['visible']):7} {mark(r['target_pass']):7} "
              f"{mark(r['keep_pass']) if r['keep_n'] else '-':7} {'yes' if r['ok'] else 'NO':11}  "
              f"{', '.join(r['keep_failed'])}")
    sys.exit(0 if all(r["ok"] for r in rows) else 1)


if __name__ == "__main__":
    main()
