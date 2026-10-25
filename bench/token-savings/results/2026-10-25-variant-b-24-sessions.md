# Token savings

> Clarity arm only, at commit d482fb0 (variant B), 24 sessions, Sonnet, 2 repeats. The baselines are in 2026-10-25-pilot-24-sessions.md. At 24 sessions this lost on catching up; fd4f63b (variant C) addresses why.

Model `claude-sonnet-5-5`, grader `claude-sonnet-5-5`, Claude Code 2.1.310 (Claude Code), clarity d482fb0, 1 replicate(s), 3 blocks of 8 sessions, tool allowlist.

- **ctx tokens**: everything the model read across all its turns (input + cache write + cache read).
- **per correct answer**: total over every graded probe ÷ total score. Lower is better. Brackets are a 90% bootstrap interval.

## Tokens to get up to speed, by project size

| sessions of history | arm | score | ctx tokens per correct answer | $ per correct answer |
|---|---|---|---|---|
| 8 | clarity | 0.93 | 42k (34k–52k) | 0.028 (0.020–0.036) |
| 24 | clarity | 0.89 | 84k (62k–106k) | 0.044 (0.033–0.055) |

## Clarity against each baseline

Negative means clarity is cheaper. Score is clarity's minus the baseline's.

| sessions | vs | ctx per correct answer | $ per correct answer | score |
|---|---|---|---|---|

## What keeping the record costs

**Always loaded**: context read by a session that does nothing (the `ok` probe). **Work $**: the scripted sessions up to that point, mean per replicate (ripout shows the clarity arm's). **Break-even**: how many fresh-session catch-ups (the `resume` probe) clarity's extra work cost pays for.

| sessions | arm | always loaded | work $ | resume ctx | resume $ | clarity breaks even after |
|---|---|---|---|---|---|---|
| 8 | clarity | 3,692 | 1.02 | 49,451 | 0.031 |  |
| 24 | clarity | 4,314 | 3.06 | 38,068 | 0.030 |  |

## How the agents behaved

Probes: median tool calls, reads and searches per question, and how often the first tool call was clarity. Work: per session, clarity notes, epoch closes and CLAUDE.md edits.

| arm | probe tool calls | reads | searches | first call is clarity | notes/session | closes/session | CLAUDE.md edits/session | denied calls | escapes |
|---|---|---|---|---|---|---|---|---|---|
| clarity | 1 | 0 | 0 | 55% | 0.33 | 0.83 | 0.00 | 70 | 0 |

**escapes** counts tool calls that reached outside the arm's own project, into other arms, the results or this repo. Anything above zero needs a look at the traces before the numbers are trusted.

## Each probe after 8 sessions

Each cell: mean score · median ctx tokens.

| probe | clarity |
|---|---|
| `resume` | 1.00 · 49k |
| `handoff` | 0.50 · 50k |
| `perf` | 1.00 · 25k |
| `never` | 1.00 · 49k |
| `exp-b0` | 1.00 · 25k |
| `dec-b0` | 1.00 · 25k |
| `bug-b0` | 1.00 · 49k |

## Each probe after 24 sessions

Each cell: mean score · median ctx tokens.

| probe | clarity |
|---|---|
| `resume` | 0.50 · 38k |
| `handoff` | 1.00 · 51k |
| `perf` | 1.00 · 78k |
| `never` | 1.00 · 92k |
| `exp-b0` | 0.67 · 65k |
| `exp-b1` | 1.00 · 51k |
| `exp-b2` | 1.00 · 38k |
| `dec-b0` | 1.00 · 25k |
| `dec-b1` | 1.00 · 25k |
| `dec-b2` | 1.00 · 25k |
| `bug-b0` | 0.50 · 175k |
| `bug-b1` | 1.00 · 187k |
| `bug-b2` | 0.75 · 160k |
| `idea-b2` | 1.00 · 25k |

## Grader notes on answers that missed something

- **clarity @8 `handoff`** 1#2 (0.00): The answer names #8 `--until TIMESTAMP` as the second half of time-range filtering, but says it is only an idea in the queue and that nothing was left unfinished. It never says ISO in UTC for `--until` or that later requests are skipped, so not every part of the fact is present.
- **clarity @24 `resume`** 1#1 (0.50): Fact 1 is covered: --hourly (UTC counts) is done and --bars (# scaled to 40 columns) is the next step. Fact 2 is only partly covered: the answer mentions #16 (5xx percentage) and #17 (--status filter) but never names referrer domains or daily visitors, and doesn't call the ideas not yet started.
- **clarity @24 `resume`** 1#2 (0.50): Fact 1 is met: --hourly is done, and --bars is the next step with the 40-column '#' rows. Fact 2 is only partly met: the answer names referrer domains (#22) and daily visitors (#23) as waiting, and lists #16 (5xx percentage) and #17 (--status filter) as next, but it never calls them unstarted open ideas, and it frames the 5xx percentage as a percentage rather than an error rate.
- **clarity @24 `exp-b0`** 1#1 (0.67): Answer says split was tried and dropped, and mentions user agents with spaces mis-parsing, but never states that the regex was kept and precompiled at module level (it only mentions a later strptime/parse_ts change).
- **clarity @24 `exp-b0`** 1#2 (0.67): Answer says split was tried and not merged, and that it mis-parses user agents with spaces. It never says the regex was kept and precompiled at module level, so fact 3 is missing.
- **clarity @24 `bug-b0`** 1#1 (0.00): Answer denies a recorded bug; it mentions #4 normalising to UTC via the %z offset (+0530 test) but frames it as a feature and only speculates that earlier timestamps weren't normalised, so it doesn't state that timestamps ignored the offset or that the fix was a bug fix.
- **clarity @24 `bug-b2`** 1#1 (0.50): Answer states ties are sorted alphabetically by path, but explicitly says it can't tell what prompted the change and does not state that tie order was previously nondeterministic.
