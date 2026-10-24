# Token savings benchmark

Measures how many tokens a fresh Claude Code session spends getting up to speed on a
project, with and without clarity, and whether what it learned is right.

## How it works

1. **The same dummy project, several arms.** `seed/logstat` is a small log summariser.
   Each arm gets its own copy in its own sandbox folder, with a private
   `CLAUDE_CONFIG_DIR`:

   | arm | what the agent is told |
   |---|---|
   | `clarity` | `clarity-ctl init`; its AGENTS.md block is the only instruction |
   | `claudemd` | no clarity; CLAUDE.md says to keep CLAUDE.md current |
   | `vanilla` | no clarity; CLAUDE.md just names the objective (stock Claude Code) |
   | `ripout` | the clarity arm's final state; Claude writes CLAUDE.md from clarity, then clarity is deleted |

2. **The same scripted workload.** `scenario.SESSIONS` holds 7 user prompts: a
   feature, a failed experiment and the reason it was dropped, a product decision
   not to build something, a bug fix, work stopped halfway, and two backlog ideas.
   Each prompt runs as a fresh `claude -p` with no memory of the last one. The
   prompts never say "write this down". Whether it gets recorded depends on each
   arm's instructions.

3. **Probes.** After the workload, every arm is reset to its final state before each
   question in `scenario.PROBES`. Each question gets a fresh session: "where do
   things stand", "did we try a faster parser", "did JSON support come up", "what
   was left unfinished". The `ok` probe uses no tools, so it measures only the
   context that is always loaded.

4. **Grading.** A separate Claude call checks each answer against the rubric facts.
   The facts come from the prompts, so all arms are graded against the same
   answers.

`report.md` gives tokens, cost, turns and score for each arm and probe, the cost per
correct answer, and what keeping the record cost during the work itself.

## Run it

Requires `claude` (logged in), `uv` and git.

```sh
python3 bench/token-savings/run.py all --out /tmp/bench            # full run, Sonnet, 3 reps
python3 bench/token-savings/run.py all --out /tmp/smoke \
    --sessions 2 --reps 1 --model claude-haiku-5-5 --grader claude-haiku-5-5   # cheap smoke test
```

Phases can be run one at a time (`build`, `work`, `ripout`, `probe`, `grade`,
`report`). Reusing an `--out` folder picks up where it stopped.

The agent gets a scoped tool allowlist (`ALLOWED` in `run.py`), not
`--dangerously-skip-permissions`. Denied calls are counted in the report, so a
skewed allowlist shows up.

## Reading the result

- **ctx tokens** is everything the model read across all its turns: input, cache
  writes and cache reads. Cache reads cost about a tenth as much, so for money,
  look at **cost**.
- A low token count with a low score means the session didn't catch up. It is not
  a saving. Compare on **$ per correct answer**.
- One workload run per arm means the arms' histories differ a little: different
  commits, different numbers. The probes only check facts the prompts fixed, so
  that doesn't change the grading. It does add noise to the work-phase costs.
