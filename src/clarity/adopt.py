"""Bringing a project that already has files in it into clarity.

`init` assumes an empty or tidy folder. `adopt` is for the other case: a
workspace that grew before anyone thought about layout, with checkouts, caches,
results and scripts all sitting at the root. Clarity wants that root for its own
scaffolding, so adoption is a tidying job.

It starts by asking what the project is for, because the answer decides the
sort. Then two passes, because a research workspace is not all source. Pass one
takes the repos and splits them: the ones the project changes go under
`workspace/` with the scripts and virtualenvs around them, and the ones it only
uses — a tool, a dependency — go under `3rd_party/`. The workspace repos are
listed with `clarity-ctl repo add`, which is what makes epochs branch them. Pass two
takes what is left, which in a project that has been running a while is usually
the larger pile: run outputs, results, logs, old experiments. That is a record
of work already done, so it goes into a baseline epoch, created and immediately
closed.

The bucket is `workspace/` and not `src/` because a workspace usually holds a
checkout that has its own `src/`, and `src/duckdb/src/optimizer/` reads as a
mistake every time someone says it out loud.

The baseline epoch is the only item adoption creates. That is not a reversal of
"do not inventory the work" — guessing what someone is *working on* fills a
worklog with items they then have to close, whereas the baseline is a container
for material already on disk, and it is born closed. It also gives the human a
place in the timeline: everything up to now is epoch 1, and the next thing they
do is theirs to start.

Directories move whole, never reaching inside one. A results directory often
ships the script that reads it, with the path hardcoded relative to itself, so
lifting one subdirectory out regenerates an index from nothing and drops rows
without failing.

The moves themselves are proposed, never performed unattended. Moving a
directory can break it — a virtualenv's scripts carry absolute shebangs, a
CMake build tree has absolute paths baked into its cache — and only the human
knows which of those they still need. So the agent brings a table and waits.

`adopt` therefore initialises the project and writes `.clarity/adopt.md`: the
procedure an agent follows to propose that layout. It deletes the file when it
is done, and the file's absence is what "adoption finished" means — there is no
flag to set and nothing to keep in sync.

That also decides where the pointer lives. The block in AGENTS.md loads on
every turn of every session, so a paragraph about a one-time operation would be
paid for forever. It gets one line instead, conditional on the file existing,
which costs nothing once the file is gone.
"""

from __future__ import annotations

from pathlib import Path

from .store import CONFIG_DIR, write_atomic

DOC = "adopt.md"

ADOPT_MD = """# Adopting clarity in this project

Someone ran `clarity-ctl adopt` here. The scaffolding exists now, and this project
already had files in it before clarity arrived.

Your job is to tidy the layout, and only that. Everything that is not clarity's
goes to one of three places:

- **`workspace/`** — what the project changes: the repos it modifies, and the
  scripts, fixtures, notebooks and virtualenvs around them. When in doubt about
  something that is not a record, it goes here.
- **`3rd_party/`** — repos the project only uses: a tool, a dependency, a
  benchmark harness. Nobody here changes them, so epochs never branch them.
- **A baseline epoch** — the record of work already done: old runs, results,
  logs, analysis, notes. You create it, and it is born closed.

Then delete this file, which is what marks adoption finished.

**Do not inventory the project's in-flight work.** Reading branches and TODO
files and guessing what someone is working on takes judgement you do not have
yet, and a worklog full of wrong items costs more to clean up than it saves.
The baseline epoch is the one item you create, and it is not a guess — it is a
container for material already on disk.

## 0 · Ask what the project is for

Before you list a single directory, ask the human:

> What are you trying to do in this project?

One or two lines is plenty. Record it straight away:

    clarity-ctl objective set "what this project is for"

Ask the human; do not infer it from the code — you haven't read any yet, and
a repo's contents say what it does, not what they want from it. If they
would rather not answer, carry on without it — but every step below is easier with
it, because the goal is what tells you which repos they change. "We're making
the SWE agent do X" means the agent's repo is the one in `workspace/`, and the
rest are support.

## 1 · Read what the project already says about its layout

Now read whatever the project says about itself: `README.md`, `CLAUDE.md`,
`AGENTS.md`, and anything matching `*PLAN*.md` or `*NOTES*.md` at the root.

**If the folder was itself a git repo**, `clarity-ctl adopt` has already moved
all of it to `workspace/<folder name>/` and listed it with `repo add` — its output
said so. Read those files there instead. That checkout is sorted: skip
passes one and two for it, and do not reach inside it. What is left at the root
is only what clarity just wrote.

You are looking for decisions already made — "don't move X", "Y has to stay next
to Z", a layout someone already argued about. A line like `Don't move duckdb/ or
eval-fixture/` outranks every rule below it. Quote it back in your proposal so
the human can see you found it, and leave those entries where they are.

A move you propose against a written instruction costs the human a rebuild to
undo, and costs you their trust in the rest of the table.

## 2 · Pass one — what the project changes, and what it uses

`ls -a` in the project root, and nothing deeper yet.

**Clarity's own — these stay at the root:**

    .clarity/      EPOCHS/      LEARNINGS/      worklog.yaml
    AGENTS.md      CLAUDE.md    GEMINI.md       QWEN.md       WARP.md
    .windsurfrules      .github/copilot-instructions.md
    .git/          .gitignore

Of what is left, find the repos first — any directory with a `.git` inside it.
Each one is either changed here or only used here. Propose the split from the
goal in step 0, as **one question** for the whole set, not one per repo:

> You're modifying the SWE agent, so `mini-swe-agent/` goes in `workspace/`.
> `duckdb/`, `eval-fixture/` and `perfagent-results/` look like support, so
> they go in `3rd_party/`. Right?

If you have no goal to go on, ask which repos they change, once, as a list.

Then the rest of the working material — scripts, fixtures, notebooks, config,
virtualenvs, caches. These go to **`workspace/`**.

## 3 · Pass two — what is a record

Now look at what pass one did not claim, and work out what each one *is*. In a
project that has been running a while this is usually the larger pile: run
outputs, result directories, logs, plots, analysis, old experiments, scratch
notes. These go to **the baseline epoch**.

**Move whole top-level directories, never reach inside one.** A results
directory often contains its own scripts, and those scripts hardcode paths
relative to it — `RUNS = ROOT / "runs"` breaks silently if you lift `runs/` out
on its own, regenerating an index from an empty directory rather than failing.
If a directory holds both records and the code that reads them, it moves as one
piece, and it goes wherever its *code* needs it to be.

**When you cannot tell, do not guess.** Is `eval-fixture/` live input or a
leftover from a finished experiment? Put it in the table with a `?` and ask. The
table already waits for approval; one more question in it costs nothing, and a
wrong guess costs a move and a move back.

## 4 · Propose the layout

First, price the moves. Check each candidate for the one thing a move does not
carry with it: absolute paths baked into generated files.

Nothing in this table is source. Every one of them is an artifact built from
something else, so a move costs time to regenerate, not work. Say that — a
human told "this breaks the build" leaves a 10G checkout at the root forever,
and the same human told "re-run cmake, about twenty minutes" just says yes.

| Look for | Tells you | Cost of moving it |
|---|---|---|
| `pyvenv.cfg`, `bin/python` | a virtualenv | shebangs point at the old path — delete and recreate it, seconds |
| `CMakeCache.txt`, `build/`, `_build/` | a configured build tree | the cache holds absolute source and binary dirs — re-run cmake and rebuild; the source is untouched |
| `.uv-cache`, `.cache`, `node_modules/.cache` | a tool cache | entries key on absolute paths — delete it, it repopulates |
| a symlink pointing outside the project | a link whose target may move | repoint it after, or leave it |

Estimate the cost where you can: a build tree's size, or how long its last build
took if a log says. "Rebuild, roughly twenty minutes" is a decision the human
can make. "Moving breaks the build" is not — it only sounds like one. You are
not deciding these. You are pricing them, so the human can.

Then print one table. A row per entry at the root, in this shape:

| Now | After | Note |
|---|---|---|
| `duckdb/` | `3rd_party/duckdb/` | 10G checkout with a configured build tree — needs `cmake` + rebuild after |
| `mini-swe-agent/` | `workspace/mini-swe-agent/` | the repo you're changing — epochs will branch it |
| `scripts/` | `workspace/scripts/` | plain python, nothing to redo |
| `.venv/` | `workspace/.venv/` | virtualenv — delete and recreate after, seconds |
| `runs-2025/` | baseline epoch, `LOGS/` | 400 run directories, nothing reads them |
| `perfagent-results/` | baseline epoch, `LOGS/` | moves whole — `update_index.py` inside it reads `./runs` |
| `eval-fixture/` | `?` | can't tell if a test still reads this — which is it? |
| `EPOCHS/` | — | clarity's |

Put the rows that cost something first, each with what it costs, then the `?`
rows, then the rest. Quote any layout instruction you found in step 1. Then stop.

Ask for approval of the table as a whole, and say that any row can be struck
out. Leaving a big checkout exactly where it is is a normal answer, not a
failure of the plan — but make sure it is being left because the human wants it
there, not because you made a rebuild sound like a catastrophe.

If nothing at the root needs moving, say so and go to step 6. A project that is
already tidy is a valid outcome.

## 5 · Move, once approved

Move only the rows that survived. Three rules:

- **Use `git mv` for anything git tracks**, and a plain `mv` for everything
  else. `git mv` records the rename, so history follows the file instead of
  showing a delete and an add.
- **One entry at a time, checking as you go.** If a move fails, stop and report
  rather than continuing — a half-moved tree is worse than an untidy one.
- **Create the baseline epoch before moving anything into it** (step 7), so its
  folder exists and you are moving into a real path.

A nested checkout moves as a whole: its `.git` travels with it and its history
is untouched. Do not open it, and do not try to merge it into the outer repo.

The root is a git repo now, made by `clarity-ctl adopt` for clarity's own files
only: its `.gitignore` keeps out `workspace/`, `3rd_party/`
and every epoch's `LOGS/`, because the nested repos have histories of their own
and the records can be large. Epochs never branch this repo. Do not commit to
it — when to snapshot or share the worklog is the human's call.

Afterwards, confirm nothing was left behind: `ls -a` the root again and check it
against your table.

## 6 · Tell clarity which repos epochs branch

Every repo that went to `workspace/` gets one line:

    clarity-ctl repo add workspace/mini-swe-agent

From then on, `clarity-ctl epoch start` gives each listed repo the epoch's branch
and a worktree. Repos in `3rd_party/` stay off the list — nobody changes them,
so nothing should branch them. `clarity-ctl repo list` shows what you added.

If the folder was itself a repo, adopt already listed it — `clarity-ctl repo
list` shows it. Nothing more to add unless another repo went to `workspace/`.

## 7 · The baseline epoch

If pass two found anything, give it an epoch of its own. It is created and
immediately closed, because it describes work that already happened:

    clarity-ctl epoch new "baseline: work before clarity" --type chore
    clarity-ctl epoch close <id> "existing logs and results, moved in at adoption"

`clarity-ctl path <id>` prints its folder. Put the records under its `LOGS/`, and
analysis or plots under `ANALYSIS/` and `VIZ/` if the split is obvious — if it
is not, `LOGS/` for all of it is fine. Do not reorganise what is inside the
directories you moved. They are someone's existing work, not yours to sort.

Then `clarity-ctl note <id> "..."` with one line on where the material came from.

If pass two found nothing, skip this step. Do not create an empty epoch.

## 8 · Finish

    clarity-ctl status          # objectives, the baseline epoch closed, nothing active
    clarity-ctl repo list       # the repos epochs will branch
    rm .clarity/adopt.md    # adoption is over; this file is the only marker

Then tell the human what moved, what you left alone and why, and what now needs
regenerating — the builds to re-run, the virtualenvs to recreate, the caches
that will refill themselves. Give them the commands.

And say plainly: everything up to now is epoch 1, and it is closed. The next
thing they work on is theirs to start with `clarity-ctl epoch start`, and it will
branch the repos listed above.

Do not add any other items on your way out. `clarity-ctl idea add "..."` is theirs
to run.
"""


def doc_path(root: Path) -> Path:
    return root / CONFIG_DIR / DOC


def pending(root: Path) -> bool:
    """True while adoption is unfinished. The file's absence is the only marker."""
    return doc_path(root).exists()


def write_doc(root: Path) -> Path:
    path = doc_path(root)
    write_atomic(path, ADOPT_MD)
    return path
