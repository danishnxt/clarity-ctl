# Token savings benchmark

How many tokens does a fresh Claude Code session spend getting up to speed on a
project, with and without clarity, as the project's history grows? And are its
answers right?

## Design

**One dummy project, four arms.** `seed/logstat` is a small log summariser. Each
arm works on its own copy in its own sandbox folder, with a private
`CLAUDE_CONFIG_DIR`:

| arm | what the agent is told |
|---|---|
| `clarity` | `clarity-ctl init`; its AGENTS.md block is the only instruction |
| `claudemd` | no clarity; CLAUDE.md says to keep CLAUDE.md current (the strong baseline) |
| `vanilla` | no clarity; CLAUDE.md just names the objective (stock Claude Code) |
| `ripout` | the clarity arm at a checkpoint; Claude writes CLAUDE.md from clarity, then clarity is deleted |

**A generated workload.** `scenario.py` builds blocks of 8 sessions with the same
shape each time:

1. finish the previous block's half-done work
2. try a performance experiment on a branch
3. build a feature, plus a product decision that rules something out
4. fix a bug
5. the user's verdict on the experiment, with the reason
6. build a feature
7. a feature stopped halfway
8. two backlog ideas

Ideas get built two blocks later. Each session is a fresh `claude -p` with no
memory of the last. The prompts never say "write this down"; whether anything is
recorded depends on each arm's instructions. `python3 scenario.py 8` prints the
whole scenario.

**Checkpoints are project sizes.** The agent's work is snapshotted after blocks 1,
3 and 8 (8, 24 and 64 sessions). At each checkpoint, every arm is reset to that
snapshot before each question, and each question gets a fresh session. The
questions are:

- catch up and say what's next
- what the last session left unfinished
- everything tried for performance
- recall of experiments, decisions and bugs from the first, middle and last block
- whether a backlog idea was ever built
- something that never happened, to catch made-up answers
- a no-tools `ok`, which measures the context that is always loaded

A separate Claude call grades each answer against facts fixed by the prompts, so
every arm is graded against the same answers.

**Replicates.** One workload run varies a lot from the next, so run at least two
replicates (separate `--out` folders) and combine them in the report.

## Running it

Requires `claude` (logged in, or `ANTHROPIC_API_KEY`), `uv` and git.

```sh
# cheap smoke test: one block, Haiku, one rep
python3 bench/token-savings/run.py all --out /tmp/bench/smoke \
    --blocks 1 --checkpoints 1 --reps 1 --model claude-haiku-5-5 --grader claude-haiku-5-5

# the full run, one replicate
python3 bench/token-savings/run.py all --out /tmp/bench/r1

# combine replicates
python3 bench/token-savings/run.py report --out /tmp/bench/r1 --out /tmp/bench/r2
```

Phases can be run one at a time (`build`, `work`, `ripout`, `probe`, `grade`,
`report`). Reusing an `--out` folder picks up where it stopped.

**Isolation.**
- `--out` must be outside this repo, because the repo holds `scenario.py` and its
  answers.
- Locally, all arms sit side by side in one run folder. The report's **escapes**
  column counts any tool call that reached outside its own arm. CI runs each arm on
  its own runner.

**Permissions.**
- By default the agent gets a scoped tool allowlist (`ALLOWED` in `run.py`). Denied
  calls are counted in the report.
- On a throwaway machine, `--bypass` skips permission checks instead, so denials
  don't add noise. Two ways to get one:
  - **GitHub Actions** (preferred, reproducible): run the `token-bench` workflow by
    hand. It needs an `ANTHROPIC_API_KEY` secret, runs one replicate per runner,
    and puts the combined report in the job summary.
  - **Docker** (local): see the comments in `Dockerfile`.

**Cost.** A full run on Sonnet (8 blocks, 5 reps, 4 arms) is roughly $100–150 per
replicate. Try `--blocks 3 --checkpoints 1,3` first.

## Reading the report

- **ctx tokens** is everything the model read across all its turns: input, cache
  writes and cache reads. Cache reads cost about a tenth as much, so for money,
  look at **$**.
- The headline metric is **per correct answer**: total tokens or dollars across all
  graded probes, divided by total score, with a 90% bootstrap interval. A cheap
  session that gets the answer wrong did not catch up, so it is not a saving.
- **What keeping the record costs** compares the extra work-phase spend against
  what each catch-up saves, and gives the break-even point.
- **How the agents behaved**: whether agents query clarity first, and how often
  they write notes, close epochs or edit CLAUDE.md. A low rate of following
  clarity's rules shows up here before it shows up as wrong answers.
