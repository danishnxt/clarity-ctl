"""Check that no fact's `leak` string appears in the built repo, anywhere in its history or tree.

    python leakcheck.py

For every fact of every epoch that has been built (tag e<n>), each leak string is searched, case-insensitively,
in `git log -p --all` (commit messages, and every added or removed line of every file) and in the current tree.
Prints hits with fact, commit and file; exit 1 if any.
"""
from __future__ import annotations

import os
import re
import sys

from common import BUILD_REPO, sh, story


def matcher(leak: str):
    """Case-insensitive substring; strings of 4 chars or fewer ('ERP', 'Q3') must match as whole words,
    or 'ERP' would hit 'enterprise'."""
    if len(leak) <= 4:
        rx = re.compile(rf"\b{re.escape(leak)}\b", re.I)
        return lambda text: bool(rx.search(text))
    return lambda text: leak.lower() in text.lower()


def built_epochs() -> set[int]:
    return {int(t[1:]) for t in sh("git", "tag", cwd=BUILD_REPO).stdout.split() if re.fullmatch(r"e\d+", t)}


def main() -> None:
    if sys.argv[1:2] in (["-h"], ["--help"]):
        print(__doc__)
        return
    built = built_epochs()
    needles = [(ep["n"], f["id"], leak) for ep in story()["epochs"] if ep["n"] in built
               for f in ep.get("facts", []) for leak in f.get("leak", [])]
    needles = [(n, fid, leak, matcher(leak)) for n, fid, leak in needles]
    hits = []
    log = sh("git", "log", "-p", "--all", "--no-color", cwd=BUILD_REPO).stdout.splitlines()
    commit = file = None
    in_msg = False
    for line in log:
        if line.startswith("commit "):
            commit, file, in_msg = line.split()[1][:9], "(commit message)", True
            continue
        if line.startswith("diff --git"):
            file, in_msg = line.split(" b/", 1)[-1], False
            continue
        if in_msg and line.startswith(("Author:", "Date:")):
            continue
        if in_msg or (line[:1] in "+-" and not line.startswith(("+++", "---"))):
            for n, fid, leak, match in needles:
                if match(line):
                    hits.append((fid, leak, f"history {commit}", file, line.strip()[:140]))
    for root, dirs, files in os.walk(BUILD_REPO):
        dirs[:] = [d for d in dirs if d not in (".git", ".pytest_cache", "__pycache__")]
        for fn in files:
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, BUILD_REPO)
            try:
                text = open(path, errors="strict").read()
            except (UnicodeDecodeError, OSError):
                continue
            for ln, line in enumerate(text.splitlines(), 1):
                for n, fid, leak, match in needles:
                    if match(line):
                        hits.append((fid, leak, "tree", f"{rel}:{ln}", line.strip()[:140]))
    print(f"{len(needles)} leak strings over epochs {sorted(built)}")
    groups: dict[tuple, list] = {}
    for h in dict.fromkeys(hits):                      # one entry per distinct hit, input order
        groups.setdefault((h[0], h[1], h[2].split()[0], h[3].split(":")[0]), []).append(h)
    for (fid, leak, where, file), hs in groups.items():
        commit = hs[0][2].split()[1] if where == "history" else ""
        print(f"HIT {fid} {leak!r} | {where} {commit} | {file} | {len(hs)} line(s), e.g. {hs[0][3] if where == 'tree' else ''} {hs[0][4]}")
    print(f"{len(hits)} hit lines in {len(groups)} (fact, word, file) groups")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
