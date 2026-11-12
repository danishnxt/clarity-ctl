# meterbill eval harness

Python 3.12, standard library plus PyYAML (`figure.py` also needs matplotlib). Run every script from this
directory with `uv run --with pyyaml python <script>.py`, or with any interpreter that has PyYAML.

Requirements on the machine: `claude` (Claude Code; override the binary with `CLAUDE_BIN`), `clarity-ctl` on `PATH`
(only the clarity arm sees it), `git`, and `uv` (used once to make a venv with pytest).
Scratch space is `$MB_SCRATCH` (default `$TMPDIR/meterbill-eval`, or `/tmp/meterbill-eval` if `TMPDIR` is unset); the
venv, the build repo and every session box live there. Results are written under `../results/`.

The published results hold every transcript as `.jsonl.gz`. `report.py`, `split.py` and `figure.py` read `.jsonl.gz`
and `.jsonl`; `tasks.py` and `replay.py` treat a `.jsonl.gz` as a finished session when resuming. New runs write plain
`.jsonl`.

## What exists

- `../story.yaml`, `../arms.md`: the frozen design (24 epochs, task prompts, hidden-test descriptions, arms).
- The built code repo: `$MB_SCRATCH/build/box/workspace/meterbill`, tags `e1`..`e24`. If it is missing, restore it
  with the same commit hashes from the bundle:

      mkdir -p "${MB_SCRATCH:-${TMPDIR:-/tmp}/meterbill-eval}/build/box/workspace"
      git clone ../results/build/meterbill-e24.bundle "${MB_SCRATCH:-${TMPDIR:-/tmp}/meterbill-eval}/build/box/workspace/meterbill"

  The clone carries tags e1..e24; `git rev-parse e24` starts with `9f41e74`.
- Memory snapshots written by the replay: `../results/memory/<arm>/e<NN>/` (claudemd, clarity), through e24.
- Hidden tests, reference patch and trap patches: `../tasks/<checkpoint>/<ID>/`. Hidden tests are never put in a
  task box; `tasks.py` copies them into a copy of the code after the session to grade it.

## Scripts

| script | what it does |
|---|---|
| `build.py --upto N` | builds epochs, one builder session each (done to e24) |
| `leakcheck.py` | searches the built repo's tree and `git log -p` for each fact's leak words (word hits such as `quote`, `ledger`, `Tokyo`, `legal`, `allocated` are vocabulary collisions, reviewed by hand) |
| `replay.py [--arm A] --upto N` | writes each arm's memory after each epoch (done to e24) |
| `validate.py --at e24 [IDs]` | checks hidden tests and patches against the checkpoint's code: unchanged tree, target fails and keep passes; `reference.patch`, everything passes; each trap patch, target passes and at least one keep test fails |
| `tasks.py --at e24 --task ... --arm ... --reps N [--list]` | runs task sessions (resumable per task, arm, rep) and grades them |
| `report.py [--at e16\|e24]` | checkpoint report: pass n/N, cost-weighted mean and per rep, paired differences, solving-vs-memory split |
| `split.py FILE.jsonl[.gz]` | solving-vs-memory split of one session |
| `figure.py [root [outdir]]` | the headline figure and `figure-data.csv` |
| `noop.py` | context-leak check: what instructions a session sees per arm |

## Running a task checkpoint (the e24 run, as designed)

Scope as frozen: claudemd and clarity only; D1 P1 X1 H2 H1; 3 reps (30 sessions). `tasks.py --at e24` refuses
`--arm nothing`.

    uv run --with pyyaml python tasks.py --at e24 --task D1 P1 X1 H2 H1 --arm claudemd clarity --reps 3 --list   # lists, starts nothing
    uv run --with pyyaml python tasks.py --at e24 --task D1 P1 X1 H2 H1 --arm claudemd clarity --reps 3
    uv run --with pyyaml python report.py --at e24

Per session it makes a fresh box (the checkpoint's code, that arm's memory for the checkpoint; the clarity box also gets
the objective that names `workspace/meterbill`), runs `claude -p` with the task prompt verbatim, then grades a copy of
the code: visible suite, hidden target tests, hidden keep tests. Output per session is
`../results/tasks/<checkpoint>/<ID>/<arm>/r<rep>.{jsonl,meta.json,diff}`. After a usage limit the run stops starting
sessions, prints `REMAINING (usage limit): [...]` and exits with code 3; rerun the same command later.

The published e24 run stopped at 18 of the 30 sessions, by the owner's decision (see `../README.md`).

## Usage is summed over every `result` event

A session's stream can contain more than one `result` event: a backgrounded command that finishes after the model
has ended its turn wakes the session for another turn. Per event, `usage`, `num_turns` and `duration_ms` cover only
that stretch, so they are summed (`common.session_result`); `total_cost_usd` and `modelUsage` are cumulative in the
stream, so the last value is the session total. Two published sessions have two events (`e16/T1/claudemd/r1`,
`e24/P1/clarity/r1`). Their `meta.json` was written before the fix and keeps the last event's usage only; every
report and the figure read the transcript, not `meta.json`.

## Repair rule (fixed in advance, `story.yaml` e24 header)

If both arms fail the same hidden test for a reason not tied to a planted fact (an interface the prompt left open), the
task is repaired and rerun for both arms, and the discarded runs are kept and reported. No repair was needed at the
runs that exist. (Known open interface in P1: the prompt says `<payment id>` but payments have no id; the hidden tests
ignore the id token.)
