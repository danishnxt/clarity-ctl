# clarity-ctl

**Project state you can read in one command, and your coding agent can query without crawling the tree.**

A coding agent can easily overtake your own thoughts and plans in a project and run away
with its own reasoning. That leaves you with:

1. Gaps in your understanding.
2. Logs too long to read, that confuse more than they explain.
3. Experiment results, good and bad, that can't be tied back to a cause.
4. Tokens burned on catching up. Every session starts with you re-explaining where
   things stand, and the agent re-reading the tree to find out for itself.

For a toy project that can be fine. For larger work, where you need a complete handle
on the state of things, it's a real problem.

clarity-ctl is a small CLI and a few simple rules for your agent that keep you in the
loop instead of floundering behind it. Good prompting can do this too; clarity-ctl makes
it close to automatic.

Each cycle of work is an **epoch**, which keeps its logs, learnings, worktrees and
branches together. I find it very hard to make sense of a repo after Claude or Codex has
ploughed through it. This is the fix.

The state lives in one file, `worklog.yaml`, written only by the CLI. It prints the
state for you and serves it as JSON to an agent. Nothing in it needs a model.

## Install

Requires Python 3.10+ and git.

```sh
uv tool install clarity-ctl         # or: pipx install clarity-ctl
```

## Quick start

An agent's notes and plans belong to the project, not your repo's history. So your code
lives in its own repo under `workspace/`, and pushing it never pushes the worklog.

```sh
mkdir parser && cd parser
clarity-ctl init --objective "Make the parser fast enough for 1GB inputs"
git clone git@github.com:you/parser.git workspace/parser
clarity-ctl repo add workspace/parser
```

Already have a repo? Run `clarity-ctl adopt` inside it instead
([Existing projects](#existing-projects)). Then add ideas and start one:

```sh
clarity-ctl idea add "flaky test on macOS" --type fix
clarity-ctl idea add "try a ring buffer for the tokenizer" --type experiment

clarity-ctl epoch start 2
clarity-ctl note 2 "ring buffer 2x slower than the deque on small inputs — keeping the deque below 64KB"
clarity-ctl epoch close 2 "kept the deque; ring buffer only above 64KB"
```

`clarity-ctl status` tells you, and your agent, where things stand:

```
OBJECTIVE  Make the parser fast enough for 1GB inputs

Active (1)
┌───┬─────┬──────────────────────────────────────────────────────────────┐
│   │  id │ epoch                                                        │
├───┼─────┼──────────────────────────────────────────────────────────────┤
│ ▸ │   2 │ try a ring buffer for the tokenizer                          │
│   │     │ EPOCHS/002_2026-09-21__try-a-ring-buffer-for-the-tokenizer   │
│   │     │ held by you@laptop, just now                                 │
└───┴─────┴──────────────────────────────────────────────────────────────┘

Up next (1)
┌───┬─────┬──────────────────────────────────────────────────────────────┐
│   │  id │ idea                                                         │
├───┼─────┼──────────────────────────────────────────────────────────────┤
│ · │   1 │ flaky test on macOS                                          │
└───┴─────┴──────────────────────────────────────────────────────────────┘

0 closed or dropped — clarity-ctl status --all
```

## Ideas and epochs

Left alone, an agent starts the next thing before the last one is finished, and a week
later nobody knows which change came from which attempt.

An **idea** is one line in the worklog, so writing one down costs nothing. An **epoch**
is an idea you've started. `epoch start` gives it a folder and a branch `epoch/NNN-slug`
in every listed repo, checked out as a worktree inside that folder. `--repo` narrows
that to the repos the work touches (`--repo agent --repo harness`, by folder name),
and `epoch add-repo 7 other` adds one mid-flight; `epoch drop-repo 7 other` removes
its worktree and keeps its branch. Just planning, or analysis with no code expected
yet? `epoch start 7 --no-repos` gives it the folder and branches nothing until you
`add-repo`.

```
idea ──start──► active ──close──► done / dropped
                   ▲                  │
                   └──────reopen──────┘
```

`refresh` merges each repo's **base** into the
epoch's branch: the branch that repo's checkout was on when the epoch started (`main` if
it was detached), recorded then, so switching the checkout later for other work changes
nothing. `refresh 7 --base release --repo web` changes it on purpose. `close` records a
one-line outcome, removes the worktree and keeps the branch; `--drop` records it as
dropped. It never merges: merge first, and it warns if the branch has commits its
base doesn't.

## Notes and sessions

The diff shows what an agent did. What you lose is *why*: the approach it tried first
and dropped, the number that surprised it, the reason it changed direction.

```sh
clarity-ctl note 2 "ring buffer 2x slower on small inputs — keeping the deque below 64KB"
```

A note is one timestamped line on its epoch. The agent rules say to write one the moment
a decision changes, not at the end, because in a long session the end never comes.

This takes weight off the usual `work_so_far.md` handoff file rather than replacing it.
Notes survive a crash or a compacted history, and epochs nudge you to finish one thing
at a time, so a new session starts from "epoch 7, these notes", not the whole project.
Longer handoffs go in the epoch's `PLANS/` folder.

The record is only as good as the notes written, and a fast agent can forget. Glance at
`clarity-ctl show <id>` before you close an epoch.

## What's on disk

You should be able to open the folder and see what happened without asking the agent.

```
parser/
├── worklog.yaml            the source of truth
├── .clarity/config.yaml    project settings
├── AGENTS.md, CLAUDE.md    the rules for your agent
├── EPOCHS/
│   └── 002_2026-09-21__try-a-ring-buffer-for-the-tokenizer/
│       ├── EPOCH.md        summary and notes, generated; yours below the marker
│       ├── PLANS/          long-form docs for this piece of work
│       ├── LOGS/ ANALYSIS/ VIZ/
│       └── wt/parser/      the epoch's worktree of workspace/parser
└── workspace/
    └── parser/             your repo, with its own remote
```

The top folder is a git repo of clarity's files only. It ignores `workspace/`, has no
remote unless you add one, and clarity never commits to it. Worktrees get removed;
branches never do.

## Working with agents

An agent should ask for the state, not crawl for it. `init` writes a short block of
rules into `AGENTS.md`, imported by `CLAUDE.md`: query clarity, claim an epoch before
working on it, note decisions. The rest of those files is left alone.

```sh
clarity-ctl install            # put the block back, in a project that lost it
clarity-ctl install --remove   # take the block back out
```

Every command that writes keeps the block current, so after you upgrade clarity-ctl
the next write in each project updates what its agents read. A worklog written by a
newer clarity-ctl than yours still reads, with a warning, but refuses every write
until you upgrade.

Every read takes `--json` (`clarity-ctl show active --json`, `clarity-ctl show 2 --json`)
and answers `{ok, command, data, warnings, version}`; a failure has the same fields with
`error` and `code` in place of `data`, a mistyped command included. Exit codes: `0` ok · `1` error ·
`2` validation failed · `3` not a clarity project · `4` refused. The envelope and exit
codes are stable.

**Commands always take the epoch id.** A guess works until a second epoch starts, and
then the same command quietly means something else.

Several agents never share files, since each epoch has its own worktree.
`clarity-ctl claim 7` and `clarity-ctl release 7` show who is on what. A claim is a
warning, not a lock: a second one needs `--steal`, which records who it was taken from.

## Existing projects

Most projects worth this already exist, and they're the messiest. Run `clarity-ctl adopt`
in one.

- **A git repo**: adopt moves all of it, history and uncommitted work included, to
  `workspace/<folder name>/`. Anything with an absolute path, like a virtualenv, needs
  rebuilding.
- **Several checkouts and loose files**: adopt writes `.clarity/adopt.md`, a procedure
  for an agent. It proposes moves into `workspace/` (repos you change), `3rd_party/`
  (repos you only use) and a closed baseline epoch (past logs and results). Every move
  waits for your approval.

## Development

```sh
uv venv && uv pip install -e . pytest
.venv/bin/python -m pytest -q tests
```

## License

MIT — see [LICENSE](LICENSE).
