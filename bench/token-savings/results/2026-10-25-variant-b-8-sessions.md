# Token savings

> Clarity arm only, at commit 70920dd: variant A plus `epoch start --in-place` for small changes, which makes no branch and no worktree. Sonnet, 2 repeats. The baselines are in 2026-10-25-pilot-24-sessions.md, first 8 sessions: same scenario, same questions.

Model `claude-sonnet-5-5`, grader `claude-sonnet-5-5`, Claude Code 2.1.310 (Claude Code), clarity 70920dd, 1 replicate(s), 1 blocks of 8 sessions, tool allowlist.

- **ctx tokens**: everything the model read across all its turns (input + cache write + cache read).
- **per correct answer**: total over every graded probe ÷ total score. Lower is better. Brackets are a 90% bootstrap interval.

## Tokens to get up to speed, by project size

| sessions of history | arm | score | ctx tokens per correct answer | $ per correct answer |
|---|---|---|---|---|
| 8 | clarity | 0.96 | 36k (30k–44k) | 0.026 (0.018–0.035) |

## Clarity against each baseline

Negative means clarity is cheaper. Score is clarity's minus the baseline's.

| sessions | vs | ctx per correct answer | $ per correct answer | score |
|---|---|---|---|---|

## What keeping the record costs

**Always loaded**: context read by a session that does nothing (the `ok` probe). **Work $**: the scripted sessions up to that point, mean per replicate (ripout shows the clarity arm's). **Break-even**: how many fresh-session catch-ups (the `resume` probe) clarity's extra work cost pays for.

| sessions | arm | always loaded | work $ | resume ctx | resume $ | clarity breaks even after |
|---|---|---|---|---|---|---|
| 8 | clarity | 3,643 | 0.95 | 49,575 | 0.031 |  |

## How the agents behaved

Probes: median tool calls, reads and searches per question, and how often the first tool call was clarity. Work: per session, clarity notes, epoch closes and CLAUDE.md edits.

| arm | probe tool calls | reads | searches | first call is clarity | notes/session | closes/session | CLAUDE.md edits/session | denied calls | escapes |
|---|---|---|---|---|---|---|---|---|---|
| clarity | 0 | 0 | 0 | 43% | 0.62 | 0.75 | 0.00 | 24 | 0 |

**escapes** counts tool calls that reached outside the arm's own project, into other arms, the results or this repo. Anything above zero needs a look at the traces before the numbers are trusted.

## Each probe after 8 sessions

Each cell: mean score · median ctx tokens.

| probe | clarity |
|---|---|
| `resume` | 0.75 · 50k |
| `handoff` | 1.00 · 25k |
| `perf` | 1.00 · 25k |
| `never` | 1.00 · 49k |
| `exp-b0` | 1.00 · 25k |
| `dec-b0` | 1.00 · 25k |
| `bug-b0` | 1.00 · 49k |

## Grader notes on answers that missed something

- **clarity @8 `resume`** 1#1 (0.50): Fact 1 present: --since done, --until is next (UTC handling mentioned for naive timestamps). Fact 2 incomplete: mentions .gz input and CSV as queued items #8/#9 but does not say they are open ideas not yet started; arguably present, but framed as a queue rather than unstarted ideas.
