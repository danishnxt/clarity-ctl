# clarity-ctl

**You're still telling Claude what to put in handoff files and AGENTS.md?**

Then every session ends the same way: "write a handoff", "add that to CLAUDE.md", "no, the
other decision". Forget once and the next session burns tokens rediscovering what you
already decided: things you already paid tokens for, sitting in the last session's context.

clarity-ctl makes that project bookkeeping automatic. Your agent records decisions as it
works, and every new session starts already knowing where things stand. Nothing to
remember, nothing to dump at the end.

**Thin, light, robust.** One CLI, one YAML file, 20 commands. No server, no database, no
embeddings, no model calls. It started as a tool to keep projects manageable for people,
and has grown into an agent-first, low-bloat memory system.

## Three concepts, five minutes

| | What it is | You / your agent type |
|---|---|---|
| **Idea** | something to do later | `clarity-ctl idea "flaky test on macOS"` |
| **Epoch** | an idea being worked on: its own id, folder, branch and worktree | `clarity-ctl start 12` · `clarity-ctl close 12 "..."` |
| **Note** | a decision or a result, written the moment it happens | `clarity-ctl note 12 "DECISION: ..."` |

That's the whole model. An idea becomes an epoch with the same id; notes hang off either.
Everything else is a view of those three. A note starting `HANDOFF:` is how an agent
stops mid-way: what's done, what's left, what to do first.

## Setup in one minute

Requires Python 3.10+ and git. Installs from GitHub:

```sh
uv tool install git+https://github.com/danishnxt/clarity-ctl          # latest main
uv tool upgrade clarity-ctl                                           # pull the newest
```

A first session, typed by you or your agent:

```sh
mkdir parser && cd parser
clarity-ctl init --objective "Make the parser fast enough for 1GB inputs"
git clone git@github.com:you/parser.git workspace/parser
clarity-ctl repo add workspace/parser

clarity-ctl start "memory-map the input file" --repo all --brief "cut load time"
                    # idea 1, folder, branch, worktree, claimed; prints where to work
clarity-ctl note 1 "load time halved, total unchanged: the tokenizer is the bottleneck"
clarity-ctl idea "flaky test on macOS"          # for later: idea 2
clarity-ctl status                              # where things stand
clarity-ctl close 1 "no gain, I/O is not the bottleneck"
```

`init` also writes the rules your agent follows into `AGENTS.md` (`CLAUDE.md` imports
it). Already have a repo? Run `clarity-ctl adopt` inside it instead.

## What your agent sees

The end of `AGENTS.md` is a block that clarity regenerates on every write. This is a
small project partway through:

```
**Objective:** Make the parser fast enough for 1GB inputs

**Active**
- #3 memory-map the input file (work in `EPOCHS/003_2026-11-11__memory-map-the-input-file/wt/parser`) — handoff: mmap works; next profile the tokenizer, start with the deque in tokenize.py

**Up next:** #1 flaky test on macOS · #2 parallel chunk parsing

**Standing decisions**, newest first
- parse in 64KB chunks, never the whole file; memory stays flat (#3)

**Closed**, newest first — `clarity-ctl show <id>` for the outcome and notes
#4 ✓ ring buffer for the tokenizer
```

A fresh session reads this, not your chat history. `status`, `show <id>` and `search`
fetch the rest, as plain text when an agent runs them.

## Why not just CLAUDE.md?

- **CLAUDE.md is a file someone has to remember to update.** clarity's state changes as
  a side effect of commands the agent runs anyway.
- **Decisions are tied to the work they came from**, with an id and a date.
- **Standing decisions are listed for every session**, so a rule made in March is still
  in front of the agent in November.
- **The project folder stays organised.** One folder per epoch, plans and results
  inside it, worktrees out of the way, and code in its own repo so pushing code never
  pushes notes.

An agent can easily overtake you in a project and run away with its own reasoning. That
leaves you with:

1. Gaps in your understanding. *"When did we decide on this assumption...?"*
2. Messy directories, files added ad hoc with no plan. *"Try to find the second-last
   analysis.md you generated, I dare you."*
3. Logs too long to read. *"Logs are written for Claude to read, not for you."*
4. Results, good and bad, that can't be tied back to a cause. *"Again, there was no
   clear folder structure or target set up front."*
5. Tokens burned on catching up. *"Forgot to write a handoff file? Too bad: your agent
   burns tokens catching up again."*

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
outcome, folder, branch, repos and every note, latest handoff first.

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

Notes are never edited; a later note that corrects an earlier one should say so. Glance
at `show <id>` before you close, since a fast agent can forget to write notes. A claim is
a **lease**, a warning of who is working on an epoch, not a lock.

### `--json` for scripts

`status`, `show` and `search` take `--json` and answer
`{ok, command, data, warnings, version}`; a failure has `ok: false` with `error` and
`code` in place of `data`. Every other command prints text, with errors on stderr.
`status --json` lists each item with a `note_count`; `show <id> --json` has the notes.
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
expr-agent`), works in the folder `spawn` printed and stops with a `HANDOFF:` note. 7's
owner reviews (feedback goes in a note on 7.1), merges 7.1 into 7 and closes it;
`refresh 7.2` brings the merged work into a sibling. `show 7` gathers each subepoch's
outcome or latest handoff, and 7 can't close while one is active.

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

### Development

```sh
uv venv && uv pip install -e . pytest
.venv/bin/python -m pytest -q tests
```

### Releasing

Bump the version in `pyproject.toml`, `src/clarity/__init__.py` and
`src/clarity/cli.py`, commit, tag `v<version>`, push the tag and publish a GitHub
release. Users pin it with `uv tool install git+https://github.com/danishnxt/clarity-ctl@v<version>`.
PyPI publishing is off: `.github/workflows/publish.yml` runs only when started by hand.

### License

MIT — see [LICENSE](LICENSE).
