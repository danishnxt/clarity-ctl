# clarity-ctl

**Project state you can read in one command, and your coding agent can query without crawling the tree.**

clarity-ctl is a small command-line tool that records what a project is trying to do,
what has been tried, and what came of it. It is for people who work with coding agents
like Claude Code or Codex on anything bigger than a toy, and want to stay in charge.

## Why

A coding agent can easily overtake your own thoughts and plans in a project and run away
with its own reasoning. That leaves you with:

1. Gaps in your understanding.
2. Logs too long to read, that confuse more than they explain.
3. Experiment results, good and bad, that can't be tied back to a cause.
4. Tokens burned on catching up. Every session starts with you re-explaining where
   things stand, and the agent re-reading the tree to find out for itself.

clarity-ctl is a small CLI and a few simple rules for your agent that keep you in the
loop. Good prompting can do this too; clarity-ctl makes it close to automatic.

## How it works

A project has three kinds of things:

- **An objective**: one line saying what the project is for.
- **Ideas**: things you might do. One line each; no folder, no branch.
- **Epochs**: one attempt at one thing, such as a feature, a fix or an experiment.
  Starting an idea turns it into an epoch.

When an epoch starts, it gets its own folder, its own git branch, and a **worktree**: a
second checkout of your repo in that folder, so two attempts in parallel never touch
each other's files.

As you work, you write **notes**: what you tried, and why a decision changed. When
you're done, you **close** the epoch with a one-line outcome. All of it lives in one
file, `worklog.yaml`, written only by the CLI.

## Install

Requires Python 3.10+ and git.

```sh
uv tool install clarity-ctl         # or: pipx install clarity-ctl
```

## Quick start

clarity's files live in the project folder; your code lives in its own repo under
`workspace/`, so pushing your code never pushes the notes.

```sh
mkdir parser && cd parser
clarity-ctl init --objective "Make the parser fast enough for 1GB inputs"
git clone git@github.com:you/parser.git workspace/parser
clarity-ctl repo add workspace/parser

clarity-ctl idea add "memory-map the input file" --type experiment
clarity-ctl epoch start 1                  # folder, branch epoch/001-..., worktree
cd $(clarity-ctl path 1)/wt/parser         # work here
clarity-ctl note 1 "load time halved, total unchanged: the tokenizer is the bottleneck"
clarity-ctl epoch close 1 "no gain, I/O is not the bottleneck"
```

Already have a repo? Run `clarity-ctl adopt` inside it instead
([Existing projects](#existing-projects)).

## Reading the state

`clarity-ctl status` is the one-screen view: the objective, what's active, what's next.
`--all` adds the 15 most recent closed and dropped epochs (`--limit N` for more,
`--order oldest` to read them as a story).

```
$ clarity-ctl status --all
OBJECTIVE  Make the parser fast enough for 1GB inputs

Active (1)
┌───┬─────┬────────────────────────────────────────────────────────────────────┐
│   │  id │ epoch                                                              │
├───┼─────┼────────────────────────────────────────────────────────────────────┤
│ ▸ │   3 │ parallel chunk parsing                                             │
│   │     │ EPOCHS/003_2026-10-20__parallel-chunk-parsing                      │
│   │     │ held by you@laptop, just now                                       │
└───┴─────┴────────────────────────────────────────────────────────────────────┘

Up next (1)
┌───┬─────┬────────────────────────────────────────────────────────────────────┐
│   │  id │ idea                                                               │
├───┼─────┼────────────────────────────────────────────────────────────────────┤
│ · │   4 │ flaky test on macOS                                                │
└───┴─────┴────────────────────────────────────────────────────────────────────┘

Closed (2)
┌───┬─────┬────────────────────────────────────────────────────┬───────────────┐
│   │  id │ epoch                                              │ landed        │
├───┼─────┼────────────────────────────────────────────────────┼───────────────┤
│ ✓ │   2 │ ring buffer for the tokenizer                      │ ✅ merged     │
│   │     │ outcome: 1.6x faster on 1GB; deque kept under 64KB │               │
├───┼─────┼────────────────────────────────────────────────────┼───────────────┤
│ ✓ │   1 │ memory-map the input file                          │ ❌ not merged │
│   │     │ outcome: no gain, I/O is not the bottleneck        │               │
└───┴─────┴────────────────────────────────────────────────────┴───────────────┘
```

The **landed** column is read live from git, squash merges included. So the history
shows what stuck and what didn't, each with its reason. That makes clarity a good fit
for performance and research work, where you try five things and keep two, not just
for tracking bugs.

`clarity-ctl show <id>` prints one item as a page, with its full outcome and every note:

```
$ clarity-ctl show 1
memory-map the input file  #1
✓ done • ❌ not merged into main • experiment • closed today

  no gain, I/O is not the bottleneck

==> Where
  branch  epoch/001-memory-map-the-input-file
  folder  EPOCHS/001_2026-10-20__memory-map-the-input-file
  repo    workspace/parser — base main

==> Notes (2)
  just now · 2026-10-20 00:22
    Profile says 30% of a 1GB run is in read(); trying mmap to cut it.

  just now · 2026-10-20 00:22
    Load time halved, total time unchanged: the tokenizer is the bottleneck, not
    I/O.
```

Closing never merges and never deletes a branch: merge first if the work should land,
or don't. For an attempt that failed outright, `epoch close <id> --drop "why"` records
it as dropped instead of done.

## Working with agents

`init` writes a short block of rules into `AGENTS.md`, and `CLAUDE.md` imports it. The
rules tell an agent to:

- ask clarity for the state (`clarity-ctl status`, `clarity-ctl show active --json`)
  instead of reading the whole tree;
- claim an epoch before working on it (`clarity-ctl claim <id>`, `release <id>`);
- write a note the moment a decision changes.

`clarity-ctl install` puts the block back if it's lost; `install --remove` takes it out.

A claim is a **lease**: a marker saying who is working on an epoch (`epoch start` takes
one for you). It is a warning, not a lock; taking over someone else's needs `--steal`,
which records who held it.

Every read takes `--json` and answers `{ok, command, data, warnings, version}`. Exit
codes: `0` ok · `1` error · `2` validation failed · `3` not a clarity project ·
`4` refused.

Commands always take the epoch's id (`clarity-ctl note 7 "..."`). clarity never
guesses: a guess works until a second epoch starts.

## Getting the most out of it

- **Read `status` at the start of every session.** It's the whole briefing.
- **One epoch per attempt.** Two ideas in one branch can't be kept or thrown away
  separately.
- **Name things like a title.** A few words: "memory-map the input file". Put the why
  and the evidence in the first note; `show <id>` prints it.
- **Write a note the moment a decision changes,** not at the end. In a long session the
  end never comes, and the notes are what the next session has instead of this
  conversation.
- **Close with an honest outcome,** even when it's "didn't work, not merging".
- **Glance at `show <id>` before you close.** A fast agent can forget to write notes.

## Existing projects

Run `clarity-ctl adopt` in the folder.

- **A git repo**: adopt moves all of it, history and uncommitted work included, to
  `workspace/<folder name>/`. A virtualenv or anything else with absolute paths needs
  rebuilding.
- **Several checkouts and loose files**: adopt writes `.clarity/adopt.md`, a procedure
  for an agent. It proposes moving repos you change to `workspace/`, repos you only use
  to `3rd_party/`, and past results into a closed baseline epoch. Every move waits for
  your approval.

A workspace can hold several repos. List each one you change with `clarity-ctl repo add
<path>`, and every new epoch branches all of them. `epoch start <id> --repo <name>`
branches only some, and `--no-repos` branches none, for planning or analysis.

## Development

```sh
uv venv && uv pip install -e . pytest
.venv/bin/python -m pytest -q tests
```

## License

MIT — see [LICENSE](LICENSE).
