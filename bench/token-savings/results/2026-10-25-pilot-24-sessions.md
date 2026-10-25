# Token savings

> **Notes on this run.**
> - Sonnet, 1 replicate, 2 repeats per question; clarity at commit 61ee848, with the state digest.
> - The run paused once at a subscription limit and resumed.
> - The **92 errored calls** are leftover third repeats from an attempt that was aborted when repeats went
>   from 3 to 2. They are excluded and change nothing.
> - The **escapes** counts come from an over-eager `../..` check, removed since. Reading every trace
>   found no call that reached another arm, the results or the repo.

Model `claude-sonnet-5-5`, grader `claude-sonnet-5-5`, Claude Code 2.1.310 (Claude Code), clarity 7ce7f46, 1 replicate(s), 3 blocks of 8 sessions, tool allowlist.

- **ctx tokens**: everything the model read across all its turns (input + cache write + cache read).
- **per correct answer**: total over every graded probe ÷ total score. Lower is better. Brackets are a 90% bootstrap interval.

**92 call(s) errored and are left out**; resume the run to retry them: probe clarity ok, probe ripout ok, probe ripout ok, probe vanilla ok, probe claudemd ok, probe clarity resume, probe ripout resume, probe vanilla resume, probe ripout resume, probe claudemd resume

## Tokens to get up to speed, by project size

| sessions of history | arm | score | ctx tokens per correct answer | $ per correct answer |
|---|---|---|---|---|
| 8 | clarity | 0.96 | 55k (45k–66k) | 0.032 (0.024–0.042) |
| 8 | claudemd | 0.94 | 49k (33k–68k) | 0.030 (0.021–0.041) |
| 8 | vanilla | 0.55 | 245k (176k–404k) | 0.110 (0.075–0.188) |
| 8 | ripout | 0.85 | 46k (26k–79k) | 0.032 (0.022–0.047) |
| 24 | clarity | 0.94 | 53k (42k–65k) | 0.040 (0.029–0.051) |
| 24 | claudemd | 0.93 | 36k (29k–46k) | 0.035 (0.026–0.045) |
| 24 | vanilla | 0.54 | 269k (208k–360k) | 0.130 (0.097–0.179) |
| 24 | ripout | 0.87 | 50k (36k–67k) | 0.034 (0.026–0.043) |

## Clarity against each baseline

Negative means clarity is cheaper. Score is clarity's minus the baseline's.

| sessions | vs | ctx per correct answer | $ per correct answer | score |
|---|---|---|---|---|
| 8 | claudemd | +12% | +7% | +0.02 |
| 8 | vanilla | -78% | -71% | +0.42 |
| 8 | ripout | +18% | +1% | +0.12 |
| 24 | claudemd | +47% | +13% | +0.01 |
| 24 | vanilla | -80% | -70% | +0.40 |
| 24 | ripout | +7% | +15% | +0.07 |

## What keeping the record costs

**Always loaded**: context read by a session that does nothing (the `ok` probe). **Work $**: the scripted sessions up to that point, mean per replicate (ripout shows the clarity arm's). **Break-even**: how many fresh-session catch-ups (the `resume` probe) clarity's extra work cost pays for.

| sessions | arm | always loaded | work $ | resume ctx | resume $ | clarity breaks even after |
|---|---|---|---|---|---|---|
| 8 | clarity | 4,222 | 1.39 | 50,690 | 0.030 |  |
| 8 | claudemd | 3,510 | 0.90 | 100,136 | 0.044 | 32 catch-ups |
| 8 | vanilla | 2,202 | 0.98 | 155,045 | 0.073 | 9 catch-ups |
| 8 | ripout | 3,765 | 1.39 | 126,734 | 0.044 |  |
| 24 | clarity | 5,033 | 4.21 | 53,364 | 0.037 |  |
| 24 | claudemd | 5,774 | 2.64 | 95,231 | 0.047 | 155 catch-ups |
| 24 | vanilla | 2,202 | 2.94 | 189,312 | 0.126 | 14 catch-ups |
| 24 | ripout | 4,351 | 4.21 | 130,006 | 0.050 |  |

## How the agents behaved

Probes: median tool calls, reads and searches per question, and how often the first tool call was clarity. Work: per session, clarity notes, epoch closes and CLAUDE.md edits.

| arm | probe tool calls | reads | searches | first call is clarity | notes/session | closes/session | CLAUDE.md edits/session | denied calls | escapes |
|---|---|---|---|---|---|---|---|---|---|
| clarity | 1 | 0 | 0 | 60% | 1.25 | 0.79 | 0.00 | 92 | 15 |
| claudemd | 0 | 0 | 0 | 0% | 0.00 | 0.00 | 0.54 | 59 | 17 |
| vanilla | 6 | 1 | 2 | 0% | 0.00 | 0.00 | 0.00 | 162 | 4 |
| ripout | 0 | 0 | 0 | 0% | 0.00 | 0.00 | 0.00 | 8 | 0 |

**escapes** counts tool calls that reached outside the arm's own project, into other arms, the results or this repo. Anything above zero needs a look at the traces before the numbers are trusted.

## Each probe after 8 sessions

Each cell: mean score · median ctx tokens.

| probe | clarity | claudemd | vanilla | ripout |
|---|---|---|---|---|
| `resume` | 0.75 · 51k | 0.75 · 100k | 0.00 · 155k | 0.25 · 127k |
| `handoff` | 1.00 · 51k | 1.00 · 24k | 0.00 · 128k | 1.00 · 25k |
| `perf` | 1.00 · 39k | 1.00 · 24k | 1.00 · 148k | 1.00 · 25k |
| `never` | 1.00 · 102k | 1.00 · 24k | 1.00 · 153k | 1.00 · 25k |
| `exp-b0` | 1.00 · 51k | 0.83 · 24k | 0.67 · 111k | 0.67 · 25k |
| `dec-b0` | 1.00 · 25k | 1.00 · 24k | 0.17 · 148k | 1.00 · 25k |
| `bug-b0` | 1.00 · 51k | 1.00 · 100k | 1.00 · 96k | 1.00 · 25k |

## Each probe after 24 sessions

Each cell: mean score · median ctx tokens.

| probe | clarity | claudemd | vanilla | ripout |
|---|---|---|---|---|
| `resume` | 1.00 · 53k | 0.25 · 95k | 0.00 · 189k | 0.25 · 130k |
| `handoff` | 1.00 · 26k | 1.00 · 27k | 0.00 · 212k | 1.00 · 25k |
| `perf` | 1.00 · 54k | 1.00 · 27k | 0.83 · 167k | 1.00 · 25k |
| `never` | 1.00 · 81k | 1.00 · 40k | 1.00 · 173k | 1.00 · 25k |
| `exp-b0` | 0.67 · 26k | 1.00 · 27k | 0.67 · 137k | 0.67 · 25k |
| `exp-b1` | 1.00 · 53k | 1.00 · 27k | 0.75 · 220k | 1.00 · 25k |
| `exp-b2` | 1.00 · 26k | 1.00 · 27k | 0.25 · 232k | 1.00 · 25k |
| `dec-b0` | 1.00 · 26k | 1.00 · 27k | 0.33 · 139k | 1.00 · 25k |
| `dec-b1` | 1.00 · 26k | 1.00 · 27k | 0.00 · 83k | 1.00 · 25k |
| `dec-b2` | 1.00 · 26k | 1.00 · 27k | 0.00 · 47k | 1.00 · 25k |
| `bug-b0` | 1.00 · 98k | 1.00 · 40k | 1.00 · 95k | 1.00 · 104k |
| `bug-b1` | 1.00 · 53k | 0.75 · 27k | 1.00 · 147k | 0.75 · 65k |
| `bug-b2` | 0.50 · 121k | 1.00 · 27k | 0.75 · 86k | 0.50 · 51k |
| `idea-b2` | 1.00 · 26k | 1.00 · 27k | 1.00 · 115k | 1.00 · 25k |

## Grader notes on answers that missed something

- **ripout @24 `resume`** 1#1 (0.50): Fact 1: answer says --hourly shipped and Part B (--bars, # scaled to 40 columns) is next. Fact 2: only 5xx percentage (#17) and --status filter (#18) are named as open and not started; referrer domains and daily visitors are missing, and error rate is only implied by the 5xx item.
- **vanilla @8 `resume`** 1#1 (0.00): The answer says --since is done but never names --until as the unfinished next step, and it doesn't mention gzip input or CSV output as open ideas.
- **claudemd @8 `resume`** 1#1 (0.50): Fact 1 is stated: --since is done and --until is the unstarted next step; the UTC/ISO detail is only implied via 'normalised to UTC'. Fact 2 is missing: the answer never mentions gzip input or CSV output as open ideas.
- **ripout @24 `resume`** 1#2 (0.00): Fact 1: the answer says --hourly was merged and --bars is next, but it never says --hourly prints the count for each hour of the day (UTC), so the part A description is incomplete. Fact 2: it mentions open ideas #17 and #18 and parked #21 and #22 only by number, without naming error rate, referrer domains, status filter or daily visitors.
- **vanilla @8 `resume`** 1#2 (0.00): The answer says --since is implemented but never mentions --until as the unfinished next step, and it doesn't list gzip input or CSV output as open ideas.
- **ripout @8 `resume`** 1#1 (0.50): Answer says --since shipped (inclusive, UTC) and --until is next, which covers fact 1. It never mentions open ideas like gzip input or CSV output, so fact 2 is missed.
- **clarity @8 `resume`** 1#1 (0.50): Fact 1: --since is done and #8 --until is the next step, with ISO/UTC handling mentioned for the filter, so it counts. Fact 2: the answer lists #9 read .gz logs and #10 csv output as 'Up next' but doesn't say they are open ideas not yet started, though that is arguably implied; marked as a miss because they are framed as queued items, not unstarted ideas.
- **ripout @8 `resume`** 1#2 (0.00): Answer says --since is done and --until is next, but omits that bounds are ISO timestamps in UTC (only 'UTC timestamp normalisation' and 'inclusive bound' mentioned), so part 1 is incomplete. Open ideas (gzip input, CSV output) are not mentioned at all.
- **clarity @8 `resume`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `resume`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @8 `resume`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @8 `resume`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @8 `resume`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @8 `handoff`** 1#1 (0.00): The answer never mentions part B of time-range filtering or the `--until TIMESTAMP` flag; it says only that the repo records no unfinished work and lists general gaps.
- **vanilla @8 `handoff`** 1#2 (0.00): The answer never mentions part B of time-range filtering or an unstarted `--until TIMESTAMP` option; it says nothing is unfinished beyond other loose ends.
- **vanilla @8 `handoff`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @8 `handoff`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `handoff`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @8 `handoff`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @8 `handoff`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @8 `perf`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @8 `perf`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @8 `perf`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @8 `perf`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `perf`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @8 `never`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @8 `never`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @8 `never`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @8 `never`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `never`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @8 `exp-b0`** 1#1 (0.67): Answer says a split() parser was tried and abandoned, and that main kept the regex and compiled it once at module level. But it gives the reason as no speedup (strptime dominates), not mis-parsing of user agents with spaces, so fact 2 is missing.
- **ripout @8 `exp-b0`** 1#1 (0.67): Answer states split parser was tried and dropped because it mis-parses user agents with spaces; it says the regex parser was kept but never mentions it being precompiled at module level.
- **claudemd @8 `exp-b0`** 1#1 (0.67): Split parser tried and abandoned, and the user-agent-with-spaces reason is stated. Module-level precompiled regex is mentioned only as a committed speedup to main, not as the regex being kept instead of split, so fact 3 is only partly implied.
- **vanilla @8 `exp-b0`** 1#2 (0.67): Split parser was tried and not merged, and the regex was precompiled at module level in 654f613. But the stated reason is that strptime dominates and there was no speedup, not mis-parsing of user agents with spaces.
- **ripout @24 `exp-b0`** 1#1 (0.67): Answer says split parser was tried and not merged, and that it mis-parses user agents with spaces. It says the regex parser is kept but never says it was precompiled at module level, so fact 3 is incomplete.
- **ripout @8 `exp-b0`** 1#2 (0.67): Answer states split parser was tried and dropped, and that it mis-parses user agents with spaces; it says the regex parser was kept but never mentions precompiling at module level.
- **ripout @24 `exp-b0`** 1#2 (0.67): Split parser was tried and dropped, and the user-agent-with-spaces mis-parse is given as the reason. The answer says to keep the regex parser but never says it was precompiled at module level.
- **vanilla @8 `exp-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @8 `exp-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @8 `exp-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `exp-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @8 `exp-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @8 `dec-b0`** 1#1 (0.00): Answer says no record of a prior decision exists, contradicting fact 1. It mentions the README covers nginx combined logs but does not state logstat supports only that format as a constraint (borderline, marked false). It says nothing about the customer agreeing to convert.
- **vanilla @8 `dec-b0`** 1#2 (0.33): Answer says no earlier request or decision was found, contradicting fact 1; it does note the code is built around nginx combined format (fact 2), but never mentions the customer agreeing to convert (fact 3).
- **vanilla @8 `dec-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @8 `dec-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @8 `dec-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `exp-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @8 `dec-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @8 `bug-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @8 `bug-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `exp-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @8 `bug-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @8 `bug-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `dec-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `resume`** 1#1 (0.00): The answer says --hourly is the last commit but never mentions --bars as the unfinished part B, and it lists no open ideas (error rate, referrer domains, status filter, daily visitors).
- **claudemd @24 `resume`** 1#1 (0.00): unparseable: {"hits": [false, false], "notes": "Fact 1: the answer says the hourly histogram (--hourly) is done and --bars is part B not started, but it omits the 40-column scaling and the per-hour UTC count detai
- **vanilla @24 `resume`** 1#2 (0.00): The answer says --hourly is done but never mentions the --bars part B as the unfinished next step, and it lists no open ideas (error rate, referrer domains, status filter, daily visitors).
- **claudemd @24 `resume`** 1#2 (0.50): Fact 1 is incomplete: the answer says the last commit is --hourly and --bars is part B and not started, but never says what part A prints (per-hour request counts, UTC) or that --bars draws '#' rows scaled to 40 columns. Fact 2 holds: 5xx percentage (error rate), a --status filter, top referrer domains and unique IPs per day (daily visitors) are listed as unscheduled ideas.
- **vanilla @24 `resume`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `resume`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `dec-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `resume`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `handoff`** 1#1 (0.00): The answer never mentions the unstarted `--bars` option (part B of the hourly histogram, `#` rows scaled to 40 columns); it lists other loose ends instead.
- **vanilla @24 `handoff`** 1#2 (0.00): The answer never mentions part B of the hourly histogram or the `--bars` flag (rows of `#` scaled to 40 columns). It says no half-finished code exists and lists unrelated items.
- **vanilla @24 `handoff`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `handoff`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `dec-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `handoff`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `perf`** 1#2 (0.67): Fact 1: split parser 'Not merged' with no speedup, which implies dropped. Fact 2: slicing timestamps merged. Fact 3: the answer says the multiprocessing attempt is 'Not on main, and no result recorded' and is uncertain why, so it does not state it was dropped.
- **vanilla @24 `perf`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `perf`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `bug-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `perf`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `bug-b1`** 1#2 (0.50): Answer states malformed lines are counted and 'malformed: N' goes to stderr, but explicitly says it can't tell whether they were previously silently dropped, so fact 1 is missing.
- **vanilla @24 `never`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `never`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `bug-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `never`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `exp-b0`** 1#1 (0.67): Answer says split parser was tried and not merged, and regex was kept and precompiled at module level (654f613). But the reason given is no speedup because strptime dominated, not mis-parsing of user agents containing spaces.
- **clarity @24 `exp-b0`** 1#1 (0.67): Answer says split() was tried and rejected, and that it mis-parses user agents with spaces. It says to keep the regex but never says it was precompiled at module level, so fact 3 is only partly covered.
- **ripout @24 `bug-b2`** 1#1 (0.50): Answer states ties are broken alphabetically by path but denies any ordering problem, so it misses that tie order was previously non-deterministic.
- **vanilla @24 `exp-b0`** 1#2 (0.67): Answer says split parser was tried and dropped, and regex was kept and precompiled at module level (654f613). But the reason given is no speedup because strptime dominates, not mis-parsing of user agents with spaces, so fact 2 is missed.
- **ripout @24 `bug-b2`** 1#2 (0.50): The answer says alphabetical-by-path tie-breaking applies now, but denies any ordering problem existed, so it misses the non-deterministic tie order fact.
- **clarity @24 `exp-b0`** 1#2 (0.67): Answer states split() was tried and rejected for mis-parsing user agents with spaces, and that the regex parser stayed. It never says the regex was precompiled at module level, so fact 3 is only partly covered.
- **ripout @24 `bug-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `exp-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `exp-b1`** 1#1 (0.50): Fact 1 is present: slicing replaced strptime. Fact 2 is only half there: the answer says it was merged and kept, but says the history doesn't record why, and speed is only inferred with no evidence it was correct and faster.
- **claudemd @24 `exp-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `exp-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `exp-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `exp-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **ripout @24 `idea-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `exp-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `exp-b2`** 1#1 (0.50): Answer says it was tried and abandoned (branch not merged), but explicitly says the reason isn't recorded; its overhead guesses lack the ~500k-line threshold and are presented as unconfirmed, so fact 2 is not stated.
- **vanilla @24 `exp-b2`** 1#2 (0.00): The answer says multiprocessing was never tried and found no record of it. It does not state that it was tried and dropped, and it gives no overhead or 500k-line reason.
- **vanilla @24 `exp-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `exp-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `exp-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `dec-b0`** 1#1 (0.33): Answer says no prior record of the request or a decision; it does state logstat parses only nginx combined format, but never mentions the customer agreeing to convert.
- **vanilla @24 `dec-b0`** 1#2 (0.33): Answer says no prior record of JSON-lines input or a decision; it does note logstat parses only nginx combined format, but never mentions a prior decision against it or the customer agreeing to convert.
- **vanilla @24 `dec-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `dec-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `dec-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `dec-b1`** 1#1 (0.00): Answer says there is no rule and rich would be allowed; it notes stdlib-only only 'in practice' and never gives the locked-down ops boxes without pip reason.
- **vanilla @24 `dec-b1`** 1#2 (0.00): Answer says there is no rule and treats stdlib-only as a mere habit, contradicting fact 1; it never mentions the locked-down ops boxes / no pip access reason.
- **vanilla @24 `dec-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `dec-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `dec-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `dec-b2`** 1#2 (0.00): Answer says yes tomllib is usable and says no Python minimum is declared; it never states 3.10 is the minimum or that ops servers run 3.10.
- **vanilla @24 `dec-b2`** 1#1 (0.00): The answer says tomllib can be used and states no Python constraint exists; it never mentions the 3.10 minimum or that the ops servers run Python 3.10.
- **vanilla @24 `dec-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `dec-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `dec-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `bug-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `bug-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `bug-b0`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `bug-b1`** 1#2 (0.50): Answer says malformed lines are counted and 'malformed: N' goes to stderr, but explicitly says it cannot say they were previously silently dropped, so fact 1 is missing.
- **vanilla @24 `bug-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `bug-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `bug-b1`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `bug-b2`** 1#2 (0.50): Answer states the alphabetical-by-path tie rule, but only speculates that tie order depended on log order and explicitly says it can't confirm the original problem, so non-determinism isn't stated as fact.
- **clarity @24 `bug-b2`** 1#1 (0.50): Answer states ties are sorted alphabetically by path, but says no problem was recorded and never states that tie order was previously non-deterministic.
- **vanilla @24 `bug-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `bug-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `bug-b2`** 1#2 (0.50): Answer states ties are broken alphabetically by path, but explicitly says it found no record of a problem and does not state that tie order was previously non-deterministic (only hints at 'stable between runs').
- **clarity @24 `bug-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **vanilla @24 `idea-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **claudemd @24 `idea-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
- **clarity @24 `idea-b2`** 1#3 (0.00): unparseable: You've hit your session limit · resets 6:50am (UTC)
