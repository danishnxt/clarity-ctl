TLDR: Work how you want with your coding agent without having to worry about check points, project organization, handoff files, updating your claude.md manually, your agent creating random unfindable analysis files anywhere and none of your projects organized similarly.

Works best with: Research projects, multi-repo projects, projects where direction or tasks aren't clearly defined.

## clarity-ctl

**Thin, light, robust.** One simple CLI, one YAML file, < 20 commands. No server, no database, no
embeddings, no model calls. Simple.

## Four concepts, five minutes

| | What it is | You / your agent type |
|---|---|---|
| **Idea** | something to do later | `clarity-ctl idea "flaky test on macOS"` |
| **Epoch** | an idea being worked on: its own id, folder, branch and worktree | `clarity-ctl start 12` · `clarity-ctl close 12 "..."` |
| **Note** | a result, a finding, an approach rejected, written the moment it happens | `clarity-ctl note 12 "..."` |
| **Decision** | a rule that outlives the epoch, with an id (D7); a later one can replace it | `clarity-ctl note 12 "..." --decision --replaces D3` |

That's the whole model. An idea becomes an epoch with the same id; notes hang off either;
a decision comes from an epoch and stays listed until something replaces or retires it.
Everything else is a view of those four.

## Setup in one minute

Requires Python 3.10+ and git. Installs from GitHub:

```sh
uv tool install git+https://github.com/danishnxt/clarity-ctl          # latest main
uv tool upgrade clarity-ctl                                           # pull the newest
```

## New project workflow

```sh
# setup
mkdir parser && cd parser
clarity-ctl init --objective "Make the parser fast enough for 1GB inputs"
git clone git@github.com:you/parser.git workspace/parser
clarity-ctl repo add workspace/parser

# begin work
clarity-ctl start "memory-map the input file" --repo all --brief "cut load time"
# idea 1, folder, branch, worktree, claimed; prints where to work

clarity-ctl note 1 "load time halved, total unchanged: the tokenizer is the bottleneck"
clarity-ctl idea "flaky test on macOS"          # for later: idea 2
clarity-ctl status                              # where things stand
clarity-ctl close 1 "no gain, I/O is not the bottleneck"
```

## Already have a repo?

Run `clarity-ctl adopt` inside it instead. Your agent restructures it once, and nothing moves without your approval. It's a one-time setup and every subsequent work session can benefit from clarity's rules, structure and agent guidance.

## What your agent sees

clarity-ctl maintains one marked block in your `AGENTS.md`:

1. **Rules:** written by `init`, telling your agent how to use clarity.

2. **Where things stand:** a current-state summary that gives your agent a jumping-off point back into the project, like a very small CLAUDE.md. clarity regenerates it after every write, from the epochs and notes already recorded, with no model calls.

3. Everything outside the block is yours: put whatever you'd normally put in this file.

```
Objective
---------
Make the parser fast enough for 1GB inputs

Active
------
- #3 memory-map the input file (work in `EPOCHS/003_2026-11-11__memory-map-the-input-file/wt/parser`) — handoff: mmap works; next profile the tokenizer, start with the deque in tokenize.py

Up next
-------
#1 flaky test on macOS · #2 parallel chunk parsing


Standing decisions, newest first
--------------------------------
- parse in 64KB chunks, never the whole file; memory stays flat (D1, #3)

Closed, newest first — `clarity-ctl show <id>` for the outcome and notes
#4 ✓ ring buffer for the tokenizer

```

## Why not just keep updating CLAUDE.md?

- AGENTS.md is continuous prose and it contains everything. Think of clarity-ctl as being able to 
  dynamically create a claude.md file on the fly with only the still relevant portions of the work for a
  particular task so there is less token wastage. NOTES, DECISIONS, HANDOFFS all exist as explicit objects, each
  with backlinks, overrideablility, IDs, searchability, etc.

  Many tasks require no LLM at all, trying to reuse work as much as possible. Our always on AGENTS.md state block
  is auto generated with notes/decisions/handoffs without having to incur LLM cost. 

  How? 

  Well you've already done the work! Your latest notes and decisions on a certain task are already logged and retain the most 
  relevant recent information ready at hand. Simply use them to generate a block for next time!

- **CLAUDE.md is a file someone has to remember to update.** clarity's state changes as
  a side effect of commands the agent runs anyway, so you get more from your LLM.

- **The project folder stays organised.** One folder per epoch, plans and results
  inside it, worktrees out of the way, and code in its own repo so pushing code never
  pushes notes.

## Does it work?

**It works as well as a well maintained CLAUDE.md or better, for fewer tokens, and nobody has to keep it up
to date.** Against a carefully hand-kept CLAUDE.md, clarity-ctl passed 12/12 runs to its 11/12
and used 17% fewer tokens. An agent with no memory failed every run (0/3).

That is on a small project: about 24 sessions of history. Real projects run for hundreds, and
that's where the gap grows. A CLAUDE.md has to fit everything into one file the agent reads in
full every session; by the end of this eval it was already 170 lines of its 200-line budget.
clarity's block stays short, and the rest of the history is a `search` away.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/eval-dark.png">
  <img alt="Bar chart of mean tokens per run on six tasks, clarity-ctl vs a hand-kept CLAUDE.md, with each run as a dot. clarity-ctl is lower on four of six: H1 at epoch 16 108k vs 149k, X1 161k vs 185k, H2 93k vs 116k, H1 at epoch 24 120k vs 151k; higher on D1 155k vs 141k and P1 261k vs 244k. One CLAUDE.md run on H2 failed the hidden tests." src="docs/eval-light.png">
</picture>

How it was measured: a synthetic billing library built over 24 scripted sessions by fresh
Claude Code (Sonnet) sessions. Decisions, reversals and handoffs were said in those sessions and
never written into the code. Each memory arm was kept up to date by the same agent after every
session, without seeing the tasks. Each batch's task prompts and test specs were committed before
that batch's history was built or remembered; tasks are graded by hidden tests, including tests that fail the fix you'd
write without knowing the history. The no-memory arm was run on the first of these tasks only; each cell
has 1–3 runs.
Everything is in [clarity-eval](https://github.com/danishnxt/clarity-eval#readme), with
transcripts, hidden tests and the commands to rerun it. It is also a submodule here at `eval/meterbill`,
pinned to the eval commit these numbers come from (`git submodule update --init` to fetch it).

## Commands

    read      status · show · search · help
    on an id  start · close · note · spawn · refresh · claim · rename · add-repo · drop-repo
    capture   idea
    tidy      archive
    set up    init · adopt · objective · repo add|remove

`clarity-ctl <command> --help` has each one's flags and an example; `clarity-ctl help reference`
prints them all on one page. Commands take the epoch's id: clarity never guesses which one you mean.

## Reference

### Reading the state

`status` is the one-screen view; `--all` adds the 15 most recent closed and dropped
epochs (`--limit N` for more, `--order oldest` to read them as a story). Closed rows
show a **landed** mark read live from git, squash merges included, so the history shows
what stuck and what didn't, each with its reason. `show <id>` prints one item as a page:
outcome, folder, branch, repos, its decisions, a live handoff on top, and the latest 10
notes (`--all` for every one). `show decisions` lists the standing and retired decisions;
`show D<n>` gives one with the decisions it replaced (3 back, `--all` for the rest) and
the notes linked to each.

At a terminal the reads print tables. Anywhere else, which is how an agent's shell runs
them, they print plain text with no boxes or colour, about a seventh the size for lists:

```
$ clarity-ctl show closed | cat
Closed (2), newest first
#2 ✓ ring buffer for the tokenizer · #1 ✓ memory-map the input file
```

Closing never merges and never deletes a branch: merge first if the work should land.
When the closed list gets long, `archive` moves it out of `worklog.yaml`; folders stay,
ids are never reused, and `show <id>` still reads archived epochs.

Notes are never edited; a later note that corrects an earlier one should say so. A note
about a decision links to it with `--on D<n>`. A decision that stops being true is
retired: a new one with `--replaces D<n>`, or `close D<n> "why"`, or `close D<n> --by D<m>`
when the replacement already exists. Stopping before the work is done, the agent's last
write is `note <id> "..." --handoff`: it shows in the state block until the next session's
first note on that epoch takes it up. Glance
at `show <id>` before you close, since a fast agent can forget to write notes. A claim is
a **lease**, a warning of who is working on an epoch, not a lock.

### `--json` for scripts

`status`, `show` and `search` take `--json` and answer
`{ok, command, data, warnings, version}`; a failure has `ok: false` with `error` and
`code` in place of `data`. Every other command prints text, with errors on stderr.
`status --json` lists each item with a `note_count`; `show <id> --json` has the latest 10
notes and `notes_omitted` (`--all` for every one); `show D<n> --json` and
`show decisions --json` have the decisions.
Exit codes: `0` ok · `1` error · `2` validation failed · `3` not a clarity project · `4` refused.

### Multi-repo projects

Your code lives under `workspace/`, one repo or several. List each one you change with
`repo add <path>`. `start` then asks which to branch: `--repo <name>` (repeat for more),
`--repo all`, or `--repo none` for planning or analysis. `show repos` lists them;
`add-repo` and `drop-repo` change an epoch's set later.

### Splitting work across agents

When one epoch is too big for one agent, its owner spawns a **subepoch** per part:

    clarity-ctl spawn 7 "port expressions" --brief "Expressions only. Don't touch the lexer."

Subepochs are numbered under their parent (7.1, 7.2), branch from 7's branch and merge
back into it; only 7 merges to main. The part's agent claims it (`claim 7.1 --as
expr-agent`), works in the folder `spawn` printed and stops with a `--handoff` note. 7's
owner reviews (feedback goes in a note on 7.1), merges 7.1 into 7 and closes it;
`refresh 7.2` brings the merged work into a sibling. `show 7` gathers each subepoch's
outcome or live handoff, and 7 can't close while one is active.

### Existing projects

Run `clarity-ctl adopt` in the folder.

- **A git repo**: adopt moves all of it, history and uncommitted work included, to
  `workspace/<folder name>/`. A virtualenv or anything with absolute paths needs
  rebuilding.
- **Several checkouts and loose files**: adopt writes `.clarity/adopt.md`, a procedure
  for an agent: repos you change go to `workspace/`, repos you only use to `3rd_party/`,
  past results into a closed baseline epoch. Every move waits for your approval.

After an upgrade, the next write in each project brings its agent rules and
`worklog.yaml` up to date (`init` in the project does it at once). An older clarity-ctl
reads a newer worklog but refuses to write it.

### License

MIT — see [LICENSE](LICENSE).
