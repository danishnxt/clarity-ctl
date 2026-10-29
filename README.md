# clarity-ctl

**Your automatic project manager, set up in 2 commands.**

A coding agent can easily overtake your own thoughts and plans in a project and run away
with its own reasoning. This gets especially bad if you are running multiple projects in parallel.

It leaves you with:

1. Gaps in your understanding.
2. Project structures with random files all over the place (try to look for the 2nd last analysis.md file you generated, I dare you)
3. Logs too long to read, that confuse more than they explain.
4. Experiment results, good and bad, that can't be tied back to a cause.
5. Tokens burned on catching up, re-reading code or having to remember to dump
   a handoff file at the end of every session.

clarity-ctl is a small CLI and a few simple rules for your agent that keep you in the
loop. Good prompting can do this too; clarity-ctl makes it close to automatic. The automatic
project structuring means you can peruse your project yourself as well without needing an agent
to go back in.

## How it works

A project is a collection of ideas and epochs.

- **Ideas**: An idea is added when a thought occurs to you, to be worked on in the future.
- **Epochs**: An epoch begins when work on an idea begins. A single epoch would map to a
feature, or a bug fix, or an analysis, or an experiment, etc.

When an epoch starts, it gets its own folder, its own plan/analysis/logs/viz directories, and its own **worktrees** of relevant repos you're working on. This way two epochs can work on the same repos in different epochs without overlap.

Clarity-ctl rules guide your agent for when to add **notes** to your epoch, this is to document when a decision is made, or when an experiment result arrives.

All project state lives in one lock-protected file, `worklog.yaml`, written to only by the CLI. This is available to query in agent-friendly json format or human readable format. Every clarity-ctl command can be queried in both modes.

In the future and in the interest of performance and to avoid locking, we may move this single state file to a per-epoch file.

## Install

Requires Python 3.10+ and git.

clarity-ctl installs from GitHub; it is not on PyPI.

```sh
uv tool install git+https://github.com/danishnxt/clarity-ctl          # latest main
uv tool upgrade clarity-ctl                                           # pull the newest
```

After an upgrade, the next write in each project brings its agent rules and
`worklog.yaml` up to the new version. An older clarity-ctl that meets a newer worklog
reads it but refuses to write until it's upgraded.

## Quick start

clarity's files live in the project folder; your code lives in its own repo under
`workspace/`, so pushing your code never pushes the notes.

```sh
mkdir parser && cd parser
clarity-ctl init --objective "Make the parser fast enough for 1GB inputs"
git clone git@github.com:you/parser.git workspace/parser
clarity-ctl repo add workspace/parser

clarity-ctl epoch start "memory-map the input file" --repo all
                                           # idea 1, folder, branch, worktree, claimed
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

When the closed list gets long, `clarity-ctl archive` moves every closed epoch out of
`worklog.yaml` into `ARCHIVE/<month>.yaml`. Their folders stay, their ids are never
reused, and `show <id>` still reads them.

## Working with agents

`init` writes a short block of rules into `AGENTS.md`, and `CLAUDE.md` imports it. The
rules tell an agent to:

- start from the state at the end of the block: the objective, active epochs and
  their handoffs, what's queued, standing decisions and recent outcomes. clarity
  rewrites it on every write, so it is always current, and an agent gets it without
  running a command. For anything else it asks clarity (`clarity-ctl status`,
  `clarity-ctl show <id> --json`) instead of reading the whole tree;
- start work in one call: `clarity-ctl epoch start "<name>" --repo <repo> --brief "<goal>"`
  adds the idea, branches, makes the worktree and claims it. Closing
  releases it;
- write a note the moment a decision changes (see [When notes are written](#when-notes-are-written));
- stop with a **handoff**: a note starting `HANDOFF:` that says what's done, what's
  stuck, and what to do first. `show <id>` puts the latest one up front;
- record a **decision** that outlives the epoch (a rule, or something we won't
  build and why) as a note starting `DECISION:`. Every one is listed in the block;
- close an epoch only when the whole task is done and merged, with an outcome that
  says what changed and why, or drop it with the reason. If part is left for later,
  keep it active with a handoff rather than filing an idea.

Give an epoch a **brief** when you start it: `epoch start <id> --brief "<goal and
limits>"`, as text or a file. It's the first thing whoever picks the epoch up reads.

`clarity-ctl install` puts the block back if it's lost; `install --remove` takes it out.

A claim is a **lease**: a marker saying who is working on an epoch (`epoch start` takes
one for you). It is a warning, not a lock; taking over someone else's needs `--steal`,
which records who held it.

Every read takes `--json` and answers `{ok, command, data, warnings, version}`. Exit
codes: `0` ok · `1` error · `2` validation failed · `3` not a clarity project ·
`4` refused.

`clarity-ctl --help` opens with how the work goes, as commands to copy, then the
contract above. `clarity-ctl help reference` prints every command's help on one page,
so an agent can read the whole tool in one call instead of one `--help` per command.

Commands always take the epoch's id (`clarity-ctl note 7 "..."`). clarity never
guesses: a guess works until a second epoch starts.

### When notes are written

clarity never writes a note on its own and never calls a model. The agent (or you)
decides, following the rules in the block. A note is for something the next session
couldn't get from the code or git:

- **a decision changes**: a reversal, an approach rejected and why, a result that
  surprised you. Written at that moment, not at the end; in a long session the end
  never comes, and an unwritten note is lost with the conversation;
- **a rule that outlives the epoch**: a note starting `DECISION:`, listed in the
  block for every later session;
- **stopping before the work is done**: a note starting `HANDOFF:`, what's done, what's
  left, what to do first;
- **the first note on a new idea**: the why and the evidence behind its name.

Routine progress ("ran the tests", "edited parser.py") is not a note; git has it. The
outcome is not a note either: it goes on `epoch close`. Notes are kept in order and
never edited; a later note that corrects an earlier one should say so.

## Splitting an epoch across agents

When one epoch is too big for one agent, its owner spawns a **subepoch** for each part
that needs a branch of its own:

    clarity-ctl epoch spawn 7 "port expressions" --brief "Expressions only. Don't touch the lexer."

Subepochs are numbered under their parent (7.1, 7.2) and sit together under
`EPOCHS/subepochs/`. Each branches from 7's branch and merges back into it; only 7
merges to main. Quick work that needs no branch, like a search or a review, is a note
on 7 instead.

1. The part's agent claims it (`claim 7.1 --as expr-agent`), works in `path 7.1`, and
   stops with a `HANDOFF:` note. It doesn't close the subepoch.
2. 7's owner reviews. Feedback goes in a note on 7.1, so it's still there when the
   agent's session isn't.
3. 7's owner merges 7.1's branch into 7's and closes 7.1. `close` prints the merge
   command if it's missing, and `epoch refresh 7.2` brings the merged work into a
   sibling.

While 7 is active, `status` lists its subepochs under it, one line each:

    │ ▸ │  7 │ migrate the parser
    │   │    │ ↳ #7.1 ✓ port expressions
    │   │    │ ↳ #7.2 ▸ port statements

`show 7` gathers each one's outcome, or its latest handoff while it's still going.
7 can't close while a subepoch is active, and warns if a done one never got merged in.

## Getting the most out of it

- **Start from the state at the end of the block.** It's the briefing; `status` adds
  branches and leases.
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
<path>`. Then `epoch start` asks which to branch: `--repo <name>` (repeat for more),
`--repo all`, or `--repo none` for planning or analysis.

## Development

```sh
uv venv && uv pip install -e . pytest
.venv/bin/python -m pytest -q tests
```

### Releasing

1. Bump the version in `pyproject.toml`, `src/clarity/__init__.py` and
   `src/clarity/cli.py`, and commit.
2. Tag it `v<version>`, push the tag, and publish a GitHub release from it.

Users install a release with `uv tool install git+https://github.com/danishnxt/clarity-ctl@v<version>`.
Publishing to PyPI is off for now: `.github/workflows/publish.yml` runs only when
started by hand from the Actions tab, never on a release.

## License

MIT — see [LICENSE](LICENSE).
