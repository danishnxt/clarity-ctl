# Token savings

> Clarity arm only, at commit 5c8f89c: start by name, claim on start, `--repo` defaults to the only repo, a rules block half the length. Sonnet, 2 repeats. The baselines are in 2026-10-25-pilot-24-sessions.md, first 8 sessions: same scenario, same questions.

Model `claude-sonnet-5-5`, grader `claude-sonnet-5-5`, Claude Code 2.1.310 (Claude Code), clarity 5c8f89c, 1 replicate(s), 1 blocks of 8 sessions, tool allowlist.

- **ctx tokens**: everything the model read across all its turns (input + cache write + cache read).
- **per correct answer**: total over every graded probe ÷ total score. Lower is better. Brackets are a 90% bootstrap interval.

## Tokens to get up to speed, by project size

| sessions of history | arm | score | ctx tokens per correct answer | $ per correct answer |
|---|---|---|---|---|
| 8 | clarity | 0.96 | 46k (35k–60k) | 0.029 (0.020–0.038) |

## Clarity against each baseline

Negative means clarity is cheaper. Score is clarity's minus the baseline's.

| sessions | vs | ctx per correct answer | $ per correct answer | score |
|---|---|---|---|---|

## What keeping the record costs

**Always loaded**: context read by a session that does nothing (the `ok` probe). **Work $**: the scripted sessions up to that point, mean per replicate (ripout shows the clarity arm's). **Break-even**: how many fresh-session catch-ups (the `resume` probe) clarity's extra work cost pays for.

| sessions | arm | always loaded | work $ | resume ctx | resume $ | clarity breaks even after |
|---|---|---|---|---|---|---|
| 8 | clarity | 3,625 | 1.03 | 36,996 | 0.027 |  |

## How the agents behaved

Probes: median tool calls, reads and searches per question, and how often the first tool call was clarity. Work: per session, clarity notes, epoch closes and CLAUDE.md edits.

| arm | probe tool calls | reads | searches | first call is clarity | notes/session | closes/session | CLAUDE.md edits/session | denied calls | escapes |
|---|---|---|---|---|---|---|---|---|---|
| clarity | 1 | 0 | 0 | 57% | 0.50 | 1.38 | 0.00 | 28 | 0 |

**escapes** counts tool calls that reached outside the arm's own project, into other arms, the results or this repo. Anything above zero needs a look at the traces before the numbers are trusted.

## Each probe after 8 sessions

Each cell: mean score · median ctx tokens.

| probe | clarity |
|---|---|
| `resume` | 1.00 · 37k |
| `handoff` | 1.00 · 49k |
| `perf` | 1.00 · 37k |
| `never` | 1.00 · 49k |
| `exp-b0` | 1.00 · 25k |
| `dec-b0` | 1.00 · 25k |
| `bug-b0` | 0.75 · 89k |

## Grader notes on answers that missed something

- **clarity @8 `bug-b0`** 1#2 (0.50): The answer says the original failure isn't described and only infers the offset wasn't handled, so fact 1 is not stated; the fix is described as parsing with %z and normalising to UTC, which covers fact 2.
