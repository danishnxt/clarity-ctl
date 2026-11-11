# clarity-ctl

**A simple memory system and project manager for you and your agents, set up in one command with minimal overhead.**

A coding agent can easily overtake you in a project and run away with its own reasoning
and execution. This gets especially bad if you are running multiple projects in parallel.

It leaves you with:

1. Gaps in your understanding.

   > When did we decide on this assumption...?

2. Messy project directories, with random files added ad hoc and no upfront plan.

   > Try to find the second-last analysis.md file you generated, I dare you.

3. Logs too long to read, that confuse more than they explain.

   > Logs are written for Claude to read, not for you. That's fine, but you have no way
   > to read your way back to where the project stands.

4. Experiment results, good and bad, that can't be tied back to a cause.

   > Again, there was no clear folder structure or target set up front.

5. Tokens burned on catching up, re-reading code, or having to remember to dump a
   handoff file at the end of every session.

   > Forgot to write a handoff file? Too bad: your agent burns tokens catching up again.

Letting agents run wild in graphs and loops is fine for well-structured tasks. In
analysis and experiments, where you make the decisions, you'd rather stay in the loop.

clarity-ctl is a small CLI and a few simple rules for your agent that keep you in the
loop. Good prompting can do this too; clarity-ctl makes it close to automatic. The automatic
project structuring means you can peruse your project yourself as well without needing an agent
to go back in.

## How it works

A project is a collection of ideas and epochs.

- **Ideas**: added when a thought occurs to you, to be worked on later.
- **Epochs**: begin when work on an idea begins. One epoch is a feature, a bug fix, an
  analysis or an experiment.

An epoch gets its own folder and its own **worktrees** of the repos you're working on,
so two epochs can touch the same repo without overlapping. **Notes** record when a
decision is made or a result arrives. All state lives in one lock-protected file,
`worklog.yaml`, written only by the CLI; your code lives in its own repo under
`workspace/`, so pushing it never pushes the notes.

## Install

Requires Python 3.10+ and git. clarity-ctl installs from GitHub; it is not on PyPI.

```sh
uv tool install git+https://github.com/danishnxt/clarity-ctl          # latest main
uv tool upgrade clarity-ctl                                           # pull the newest
```

After an upgrade, the next write in each project brings its agent rules and
`worklog.yaml` up to date (`init` in the project does it at once). An older clarity-ctl
reads a newer worklog but refuses to write it.

## Quick start

```sh
mkdir parser && cd parser
clarity-ctl init --objective "Make the parser fast enough for 1GB inputs"
git clone git@github.com:you/parser.git workspace/parser
clarity-ctl repo add workspace/parser

clarity-ctl start "memory-map the input file" --repo all --brief "cut load time"
                    # idea 1, folder, branch, worktree, claimed; prints where to work:
                    #   work in: EPOCHS/001_<date>__memory-map-the-input-file/wt/parser
clarity-ctl note 1 "load time halved, total unchanged: the tokenizer is the bottleneck"
clarity-ctl idea "flaky test on macOS"          # for later: idea 2
clarity-ctl status                              # where things stand
clarity-ctl search tokenizer                    # which item holds a fact
clarity-ctl close 1 "no gain, I/O is not the bottleneck"
```

Already have a repo? Run `clarity-ctl adopt` inside it instead
([Existing projects](#existing-projects)).

## Commands

`<command> --help` has one command's flags and an example; `help reference` prints
them all on one page.

| | |
|---|---|
| **Read** | |
| `status` | objective, active, next; `--all` adds closed |
| `show <id\|view>` | one item with every note, or a list: `active`, `next`, `closed`, `all`, `objective`, `repos` |
| `search <words>` | the items holding a fact: names, outcomes, briefs, notes |
| **Work on an epoch** (always by id) | |
| `start <name\|id>` | add and start an idea in one go; also picks a closed epoch back up |
| `note <id> "..."` | record a decision, a result, a `DECISION:` or a `HANDOFF:` |
| `close <id> "<outcome>"` | finish it; `--drop "<why>"` when it didn't work |
| `spawn <id> "<name>"` | a subepoch, for one part of a big epoch |
| `refresh <id>` | merge each repo's base branch into the epoch's branch |
| `claim <id>` | say who is working it; `--steal` takes over |
| `rename <id> "<name>"` | new title; the old one is kept as a note |
| `add-repo <id> <repo>` · `drop-repo <id> <repo>` | change which repos an epoch branches |
| **Capture** | |
| `idea "<name>"` | work for later |
| **Tidy** | |
| `archive` | move closed epochs out of `worklog.yaml` into `ARCHIVE/<month>.yaml` |
| **Set up** | |
| `init` · `adopt` | start a project; adopt an existing one. `init` in an existing project refreshes the agent files |
| `objective "<text>"` | what the project is for |
| `repo add <path>` · `repo remove <repo>` | the repos epochs branch |

Commands take the epoch's id (`clarity-ctl note 7 "..."`). clarity never guesses
which one you mean: a guess works until a second epoch starts.

## Reading the state

`clarity-ctl status` is the one-screen view. `--all` adds the 15 most recent closed
and dropped epochs (`--limit N` for more, `--order oldest` to read them as a story).

```
$ clarity-ctl status --all
OBJECTIVE  Make the parser fast enough for 1GB inputs

Active (1)  ·  ▸ 3 parallel chunk parsing  (EPOCHS/003_2026-10-20__parallel-chunk-parsing)
Up next (1)  ·  4 flaky test on macOS

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

The **landed** column is read live from git, squash merges included, so the history
shows what stuck and what didn't, each with its reason: a good fit for performance and
research work, where you try five things and keep two.

`show <id>` prints one item as a page: outcome, folder, branch, repos and every note,
latest handoff first. Closing never merges and never deletes a branch: merge first if
the work should land. When the closed list gets long, `archive` moves it out of
`worklog.yaml`; folders stay, ids are never reused, and `show <id>` still reads them.

**Terminal or pipe.** At a terminal the reads print tables. Anywhere else, which is how
an agent's shell runs them, they print plain text with no boxes or colour, so lists are
about a seventh of the size:

```
$ clarity-ctl show closed | cat
Closed (2), newest first
#2 ✓ ring buffer for the tokenizer · #1 ✓ memory-map the input file
```

**For scripts**, `status`, `show` and `search` take `--json` and answer
`{ok, command, data, warnings, version}`; a failure has `ok: false` with `error` and
`code` in place of `data`. Every other command prints text, with errors on stderr.
`status --json` lists each item with a `note_count`; `show <id> --json` has the notes.
Exit codes: `0` ok · `1` error · `2` validation failed · `3` not a clarity project · `4` refused.

## Working with agents

`init` writes a short block of rules into `AGENTS.md`, and `CLAUDE.md` imports it. Every
later write keeps the block current. It tells an agent to:

- **start from the state at the end of the block**: objective, active epochs and their
  handoffs, the queue, standing decisions and the ten newest closed epochs. For
  anything else it asks clarity instead of reading the tree: `show closed`,
  `search <words>` to find the item holding a fact, `show <id>` to read it;
- **start work in one call**: `start "<name>" --repo <repo> --brief "<goal and limits>"`.
  The brief is the first thing whoever picks the epoch up reads;
- **write a note the moment a decision changes**: a reversal, a rejected approach, a
  surprising result. Not at the end: in a long session the end never comes;
- **stop with a handoff**: a note starting `HANDOFF:` that says what's done, what's
  left, and what to do first;
- **record a decision that outlives the epoch** (a rule, or something we won't build
  and why) as a note starting `DECISION:`. Every one is listed in the block;
- **close only when the whole task is done and merged**, with an outcome saying what
  changed and why, or `--drop` it with the reason. Part left for later: keep it
  active with a handoff.

clarity never writes a note itself and never calls a model; the agent (or you)
decides. Routine progress is not a note, git has it, and the outcome goes on `close`.
Notes are never edited; a later note that corrects an earlier one should say so. Glance
at `show <id>` before you close: a fast agent can forget to write notes. A claim is a
**lease**, a warning of who is working on an epoch, not a lock.

## Splitting an epoch across agents

When one epoch is too big for one agent, its owner spawns a **subepoch** for each part
that needs a branch of its own:

    clarity-ctl spawn 7 "port expressions" --brief "Expressions only. Don't touch the lexer."

Subepochs are numbered under their parent (7.1, 7.2), branch from 7's branch and merge
back into it; only 7 merges to main. The part's agent claims it (`claim 7.1 --as
expr-agent`), works in the folder `spawn` printed and stops with a `HANDOFF:` note.
7's owner reviews (feedback goes in a note on 7.1), merges 7.1 into 7 and closes it;
`refresh 7.2` brings the merged work into a sibling. `show 7` gathers each subepoch's
outcome or latest handoff, and 7 can't close while one is active.

## Existing projects

Run `clarity-ctl adopt` in the folder.

- **A git repo**: adopt moves all of it, history and uncommitted work included, to
  `workspace/<folder name>/`. A virtualenv or anything with absolute paths needs
  rebuilding.
- **Several checkouts and loose files**: adopt writes `.clarity/adopt.md`, a procedure
  for an agent: repos you change go to `workspace/`, repos you only use to `3rd_party/`,
  past results into a closed baseline epoch. Every move waits for your approval.

A workspace can hold several repos. List each one you change with `clarity-ctl repo add
<path>`. Then `start` asks which to branch: `--repo <name>` (repeat for more),
`--repo all`, or `--repo none` for planning or analysis. `show repos` lists them, and
`add-repo` / `drop-repo` change an epoch's set later.

## Development

```sh
uv venv && uv pip install -e . pytest
.venv/bin/python -m pytest -q tests
```

### Releasing

Bump the version in `pyproject.toml`, `src/clarity/__init__.py` and
`src/clarity/cli.py`, commit, tag `v<version>`, push the tag and publish a GitHub
release. Users pin it with `uv tool install git+https://github.com/danishnxt/clarity-ctl@v<version>`.
PyPI publishing is off: `.github/workflows/publish.yml` runs only when started by hand.

## License

MIT — see [LICENSE](LICENSE).
