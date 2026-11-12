# meterbill: does clarity-ctl help a fresh agent that has to rely on project history?

This directory holds the whole evaluation behind the "Does it work?" section of the top-level README: the
design, the frozen tasks and hidden tests, every transcript, the harness, and the scripts that rebuild the numbers.
It is written for someone who wants to check the claim, not accept it.

## What is claimed

> **When the answer lives only in the project's history, an agent with no memory got it wrong
> every time; with clarity-ctl it passed every run (12/12), and overall used 13–28% fewer tokens than
> with a carefully hand-kept CLAUDE.md (11/12)** — cheaper on 4 of the 6 tasks, dearer on 2. When the answer is in the code, memory doesn't matter:
> every arm passes, and keeping memory costs roughly 15–20k tokens a task.

What the data supports, precisely (details and tables below):

- History-only tasks: clarity-ctl passed 12/12 runs, CLAUDE.md 11/12. "No memory" was run on one history-only task
  (H1 at epoch 16): 0/3. It was not run on the epoch-24 tasks.
- Cost on those tasks: clarity-ctl was cheaper than CLAUDE.md on 4 of 6 tasks (by 13, 20, 21 and 28%) and dearer on 2
  (D1 by 10%, P1 by 7%). Pooled over runs (12 vs 12) clarity-ctl used 17% fewer tokens; averaged over the 6 tasks, 9% fewer.
  The "13-28%" range is the range over the four tasks where it was cheaper.
- Answer-in-code tasks and controls (T1-T3, C1, C2 at e16; 15 sessions per arm): every arm passed every run. Keeping
  memory cost about +17k (CLAUDE.md) and +12-14k (clarity-ctl) cost-weighted tokens per task over no memory.
- Samples are small: 1-3 runs per cell. Two epoch-24 cells have a single run.

## Design

- **A synthetic project.** `meterbill` is a Python 3.12, standard-library-only usage-billing library (events, plans,
  rating, invoices, tax, credit notes, ledger export, ...). It lives in one git repo. The history is scripted in
  `story.yaml`: 24 epochs, each one user request given to a fresh Claude Code (Sonnet) builder session, whose result
  the harness commits (`results/build/`; the repo at e24 is `results/build/meterbill-e24.bundle`, tags e1..e24,
  e24 = `9f41e74`).
- **Planted facts.** Each epoch can plant facts: decisions with their reasons, rejected approaches, reversals,
  constraints, handoffs ("half done, do this first"), and decoys no task needs. The reason is said in the request
  and the builder's rules forbid writing it into code comments. A leak check (`harness/leakcheck.py`) searches the
  tree and `git log -p` for each fact's key words; word hits that are plain vocabulary collisions were reviewed by
  hand. It checks words, not implications (see Limits).
- **Three arms**, identical code and git history (`arms.md`):
  - *no memory*: nothing but the code.
  - *CLAUDE.md*: a seed file that tells the agent to keep it current (decisions with reasons, rejected approaches,
    in-progress work, "keep it under 200 lines"), maintained after every epoch.
  - *clarity-ctl*: `clarity-ctl init` output (AGENTS.md block, worklog, EPOCHS/), maintained through clarity-ctl after
    every epoch. Run without `repo add`, so epochs carry no branch. The clarity-ctl used was the one installed on the
    author's machine (it reports 0.1.0); the exact commit is not recorded in the results.
- **Replay.** The two written arms never saw the builder sessions. After each epoch a fresh session got the user's
  request, the builder's final report and the diffstat, and updated that arm's memory the way the project's
  instructions say, without changing code (`results/replay/`, memory snapshot per epoch in `results/memory/`).
  The prompt is the same for both arms (`arms.md`). Replay cost is reported in `results/E24.md`.
- **Task sessions.** A fresh `claude -p --model sonnet` session in a box holding the code at the checkpoint and the arm's
  memory for that checkpoint; tools Bash, Read, Edit, Write, Grep, Glob; the task prompt verbatim; Claude Code's
  auto-memory disabled; `--setting-sources project,local` so the owner's global instructions are out. A `noop`
  check (`results/noop/`) confirmed each arm sees only its own instruction files.
- **Hidden tests with trap patches.** Each task has hidden target tests, hidden "keep" tests, and trap patches:
  the plausible fix an agent would write without knowing the history. `harness/validate.py` checks, against the
  checkpoint code, that the reference patch passes everything and every trap patch passes the target tests but
  fails at least one keep test. A run passes when the visible suite, the target tests and the keep tests all pass.
  Hidden tests are never in the box; they are copied in after the session.
- **Task groups.** *Controls* (C1, C2): a plain feature, no history needed. *Answer in the code* (T1, T2, T3 at e16): the
  deciding facts are recoverable from the code, which the no-memory arm showed by passing 9/9. *History-only*
  (H1 at e16; D1, P1, X1, H2, H1 at e24): deciding facts absent from the tree, tests and git log, governed code not
  yet built. The grouping into "answer in code" and "history-only" was fixed in `story.yaml`'s e24 header after the
  e16 results were seen (T1-T3 were labelled `history`, H1 `handoff` when written). H1's prompt is sufficient: the
  oracle control (no memory, deciding facts appended to the prompt) passed 3/3 (`results/tasks/e16/H1-oracle/`).

## Metric

`cost_weighted = input + 1.25 * cache_creation + 0.1 * cache_read + 5 * output` (tokens, relative prices of the four
token classes), summed over all `result` events of the session. Tables below show it in thousands ("k"). Cost includes
the session's memory reading and writing (clarity-ctl calls, CLAUDE.md edits); `results/E16.md` and `E24.md` split each
session into solving and memory turns (`harness/split.py`, attribution by characters per turn, approximate).

## What was frozen when

All dates 2026-11-11, local time (UTC-5), from the commit history of the private repository that held the eval
(its commits are not published; times are from its log).

| time | commit in the private eval repo | event |
|---|---|---|
| 21:00 | 31a5996 | harness, epochs 1-8 built, `story.yaml` and `arms.md` first committed, three-arm context-leak (`noop`) check |
| 21:09 | 360325f | epochs 3-8 rebuilt on a revised story; auto-memory switched off in every session; noop rerun; T1/C1 hidden tests and patches. The first build and noop runs are kept in `results/build/discarded-v1/`, `results/noop/discarded-v*/` |
| 21:15 | 180673f | slice run: e1-e8 replay, T1 and C1 x 3 arms x 1 rep. T1's target test was relaxed to "one read per distinct country" and the `module_memo` trap added in this commit |
| 21:21 | a03844f | story batch 2 (epochs 9-16, tasks T2 T3 H1 C2) frozen before any e9-e16 build or replay (e1-e8 memory already existed) |
| 22:07 | 3cbc758 (interim 660e5a4, 21:45) | e16 checkpoint: 54 sessions (6 tasks x 3 arms x 3 reps). **Clarity location fix**: after interim results, `arms.md` was amended so the clarity box's objective names `workspace/meterbill`. Without it, clarity's .gitignore hid the code from root-level Glob/Grep and its memory never said where the code is (the CLAUDE.md seed does). The first 18 clarity sessions are kept in `results/tasks/e16/_discarded-no-location/` (passes: H1 3/3, T1 3/3, T2 3/3, T3 3/3, C1 3/3, C2 1/3) and excluded from every number; all 18 were rerun. From e17 on, the clarity replay box carries the same objective; the e1-e16 replays ran without it |
| 22:13 | fb09fac | H1 oracle control, 3 reps, no-memory arm with the facts in the prompt (3/3) |
| 22:16 | c0c43c3 | story batch 3 (epochs 17-24, tasks D1 P1 X1 H2, H1 re-run), after the e16 results. Frozen in advance: the owner's scope (CLAUDE.md vs clarity-ctl only; no no-memory arm, no controls, no oracle runs); the repair rule; predictions (see `story.yaml`). New builder rule "build only what this session asks for" for e17+ |
| 22:39 | 9766e4b | e17-e24 built and replayed. Reps cut from 6 to 3 per cell by the owner, before any e24 task session. `results/E24-covariates.md` records CLAUDE.md length per epoch and which facts each memory holds, before any e24 session |
| 22:56 | 2a17adb | the e24 task run was **stopped by the owner after 18 of the planned 30 sessions** |
| 23:11 | 7f39ab7 | usage-summing fix (below); `E16.md` regenerated, `E24.md` written from the reps that exist |

Only e8 (1 rep) was run as the slice; e16 and e24 are the reported checkpoints.

## Results

Per cell: passes/runs, mean cost-weighted tokens, each run in parentheses (k). Source: `results/figure-data.csv`
(built by `harness/figure.py` from the transcripts); fuller tables in `results/E16.md`, `results/E24.md`, `results/SLICE.md`.

**e8**

| task | group | no memory | CLAUDE.md | clarity-ctl |
|---|---|---|---|---|
| T1 | history (e8 slice) | 0/1, 35k (35) | 1/1, 59k (59) | 1/1, 41k (41) |
| C1 | control | 1/1, 48k (48) | 1/1, 56k (56) | 1/1, 55k (55) |

**e16**

| task | group | no memory | CLAUDE.md | clarity-ctl |
|---|---|---|---|---|
| H1 | history-only | 0/3, 57k (51, 62, 58) | 3/3, 149k (126, 174, 146) | 3/3, 108k (125, 97, 102) |
| T1 | answer in code | 3/3, 34k (32, 39, 32) | 3/3, 68k (66, 82, 55) | 3/3, 60k (71, 48, 60) |
| T2 | answer in code | 3/3, 67k (60, 77, 64) | 3/3, 77k (73, 88, 71) | 3/3, 68k (75, 73, 57) |
| T3 | answer in code | 3/3, 46k (47, 46, 45) | 3/3, 55k (54, 60, 51) | 3/3, 56k (63, 53, 53) |
| C1 | control | 3/3, 47k (50, 50, 43) | 3/3, 64k (71, 55, 65) | 3/3, 58k (56, 64, 54) |
| C2 | control | 3/3, 44k (40, 47, 44) | 3/3, 61k (61, 63, 60) | 3/3, 61k (57, 69, 55) |

**e24**

| task | group | no memory | CLAUDE.md | clarity-ctl |
|---|---|---|---|---|
| D1 | history-only | not run | 2/2, 141k (143, 138) | 2/2, 155k (166, 144) |
| P1 | history-only | not run | 2/2, 244k (286, 202) | 1/1, 261k (261) |
| X1 | history-only | not run | 2/2, 185k (188, 183) | 2/2, 161k (157, 165) |
| H2 | history-only | not run | 1/2, 116k (99, 133) | 2/2, 93k (103, 82) |
| H1 | history-only | not run | 1/1, 151k (151) | 2/2, 120k (139, 101) |

Notes:

- e16 H1, no memory 0/3: the target tests passed but the keep test "credit note revenue goes to the accounts the
  invoice posted to" failed each time (the agent used the current account mapping).
- e24 H2, CLAUDE.md run 1 failed: the target test `each_entity_numbers_its_own_credit_notes` and two keep tests failed
  (credit-note numbering after a tenant moved entity, per-entity/tenant/year sequence).
- e8 T1, no memory 0/1: the keep test "override edited between invoices is used (same resolver object)" failed.
- e24 cells by n: D1 2/2, P1 CLAUDE.md 2 and clarity 1, X1 2/2, H2 2/2, H1 CLAUDE.md 1 and clarity 2.
- Pass rates, history-only: clarity-ctl 12/12 (H1e16 3, D1 2, P1 1, X1 2, H2 2, H1e24 2); CLAUDE.md 11/12.
- Clarity vs CLAUDE.md mean tokens, history-only: H1e16 -28%, D1 +10%, P1 +7%, X1 -13%, H2 -20%, H1e24 -21%.
- Answer-in-code (T1-T3) mean over tasks: no memory 49k, CLAUDE.md 66k, clarity-ctl 61k. Controls: 46k, 62k, 59k.
- Replay (memory-writing) cost, cost-weighted, e1-e8 / e9-e16 / e17-e24: CLAUDE.md 188k / 247k / 280k; clarity-ctl
  194k / 227k / 266k. Memory size at e24: CLAUDE.md 1 file, 170 lines, 33,547 chars; clarity 15 files, 80,021 chars
  (the AGENTS.md block a session always loads is 9,070 chars).

## Known limits

- **Small n.** 1-3 runs per cell, one model (Sonnet; `claude_code_version` 2.1.322 in the transcripts), one
  checkpoint per claim. Token differences are directions, not estimates; the e24 token gaps are within run-to-run spread
  in several cells (for instance P1 CLAUDE.md 286k vs 202k).
- **No-memory evidence is thin.** The 0-pass result is one task, three runs. At e8, T1 failed without memory (0/1);
  at e16 T1 passed 3/3 without memory.
- **One synthetic repo.** meterbill is small, built by one model in 24 sessions; real histories are messier.
- **clarity-ctl ran without `repo add`**, so its epochs carry no branches; real users would have them. The clarity
  box is also a git repo, and its objective names the code location (task boxes from e16, replays from e17; a fix made
  after seeing e16 interim results).
- **A best-case CLAUDE.md.** The seed tells the agent to maintain the file in a fixed structure. It grew to 170 lines
  at e24 and never reached its own 200-line cap, so pruning, the usual failure of hand-kept files, was never exercised.
- **clarity's block lists superseded decisions.** At e24 the AGENTS.md block still shows the old 90-day reject
  retention next to the 30-day change, and older reversed entries. This was predicted in advance (`story.yaml`) as a risk
  for D1 and X1; clarity passed both, but D1 was dearer than CLAUDE.md.
- **Leak check is by words.** T1-T3 passed without memory 9/9, so for them the facts were recoverable from the code even
  though no leak word appeared. Only the history-only group is claimed to need history, and the grouping was made after
  the e16 results.
- **Tasks were frozen at different times** (table above); the e16 tasks were written after the e1-e8 memory existed, the e24
  tasks after the e16 results.
- **e24 was cut at 18/30**; rep 3 never ran, no no-memory arm and no controls at e24.
- **e8 slice: 1 rep.**
- **Harness bug, fixed.** A session's stream can hold two `result` events (a backgrounded command wakes a finished session
  for another turn). The first `report.py` and `tasks.py` read only the last event, undercounting usage. Two sessions
  are affected: `e16/T1/claudemd/r1` (cost-weighted 16.8k before the fix, 66.2k after) and `e24/P1/clarity/r1`. The fix sums
  `usage`, `num_turns` and `duration` over all events; `total_cost_usd` is cumulative in the stream, so the last value is
  the total (verified: the second event's `model_usage_since_last_result` accounts for the difference). `meta.json` of
  those two sessions still holds the pre-fix, last-event usage; all reports and the figure read the transcripts.
  `results/figure-data.csv` and the figure were produced after the fix. No other number in this directory was
  produced by the old code except `SLICE.md` (e8, no affected session).
- **Scrubbed transcripts.** Transcripts were edited for publication (below). The solving/memory split tables in
  `E16.md` and `E24.md` were regenerated from the scrubbed files and differ from the unscrubbed run by under 1
  percentage point, because the split weights turns by characters and paths became shorter. `SLICE.md` was not
  regenerated (the current script would add replay rows for all 24 epochs to it).

## Privacy scrub

Applied to every file here, including the transcripts before they were compressed: the home directory became `~`, macOS
temp directories `$TMPDIR/`, the agent scratch directory `$TMPDIR/claude/`, the account's user name `user`, and any
email address other than reserved example domains (`*.example`, `*.invalid`, `example.com`) and `noreply@anthropic.com`
`user@example.com` (none needed replacing). `session_id`, `uuid`, `req_`, `msg_` and `toolu_` identifiers in the
transcripts are replaced by sha256-derived pseudonyms, consistent across files. The bundle is a binary git repository
with a single author `eval <eval@example.invalid>` and was copied unchanged. The only remaining mention of the
author's GitHub name is the public repository URL in clarity-ctl's own `--version` output. Transcripts still contain
Claude Code's rate-limit status events and thinking-block signatures, unmodified.

## Layout

    story.yaml, arms.md     the frozen design
    tasks/<ckpt>/<ID>/      reference.patch, hidden/ (tests), traps/ (trap patches)
    harness/                scripts and README (how to run each)
    results/build/          builder sessions e01..e24 (+ discarded-v1), the code bundle
    results/replay/<arm>/   memory-writing sessions;  results/memory/<arm>/eNN/ snapshots
    results/tasks/<ckpt>/<ID>/<arm>/r<N>.{jsonl.gz,meta.json,diff}   task sessions
    results/noop/           context-leak check;  results/E16.md E24.md SLICE.md E24-covariates.md figure-data.csv
    eval-light.png, eval-dark.png   the figure in the top-level README

## Reproduce

Needs Python 3.12, `uv`, and for new sessions `claude` and `clarity-ctl` on PATH. From the repository root:

    # numbers and figure from the published transcripts (no sessions are run)
    mkdir -p /tmp/fig/results
    uv run --with matplotlib python eval/meterbill/harness/figure.py eval/meterbill /tmp/fig   # eval-*.png, results/figure-data.csv
    diff /tmp/fig/results/figure-data.csv eval/meterbill/results/figure-data.csv                 # no output = identical
    cd eval/meterbill/harness
    uv run --with pyyaml python report.py --at e16     # rewrites results/E16.md
    uv run --with pyyaml python report.py --at e24     # rewrites results/E24.md
    uv run --with pyyaml python validate.py --help     # hidden tests vs patches (needs the code repo, see harness/README.md)

    # rerun task sessions (starts real Claude Code sessions; see harness/README.md for the code-repo restore step)
    uv run --with pyyaml python tasks.py --at e24 --task D1 P1 X1 H2 H1 --arm claudemd clarity --reps 3 --list

Rerunning sessions will not give the same numbers: model output varies run to run. Without the second argument
`figure.py` overwrites `eval-*.png` and `results/figure-data.csv` in place.
