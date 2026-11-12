# Arms — frozen 2026-11-11, before any session ran. Never tune these after seeing a result.

Every arm's sandbox has the same layout and the same code repo (identical commits):

    <box>/                      cwd of every session; NOT a git repo
    <box>/workspace/meterbill/  the code repo (git), committed by the harness only

Memory files sit in <box>/ and are never in git, so `git log` is identical in every arm.

| arm | what sits in <box>/ | written by |
|---|---|---|
| nothing  | nothing | — |
| claudemd | CLAUDE.md, seeded with the instructions below | replay agent after each epoch |
| clarity  | `clarity-ctl init` output (AGENTS.md, CLAUDE.md, worklog.yaml, EPOCHS/, .clarity/); no `repo add`, so epochs never branch the code repo | replay agent after each epoch, through clarity-ctl |

Limit: without `repo add`, clarity epochs carry no branch; real users would have one.
`clarity-ctl init` makes <box>/ a git repo with no commits that ignores everything but clarity's
files; the other arms' boxes are not git repos. Accepted asymmetry (amended 2026-11-11, before any
replay or task session).

Every session (builder, replay, task) runs with CLAUDE_CODE_DISABLE_AUTO_MEMORY=1, so Claude
Code's own auto-memory can't act as a hidden fourth memory (amended 2026-11-11, same timing).

2026-11-11, after e16 interim results: clarity box objective now names the code location
(workspace/meterbill), matching the claudemd seed; clarity's .gitignore hid workspace/ from root-level
Glob/Grep and two C2 sessions never found the code. All e16 clarity task sessions rerun; the discarded
ones are kept.

2026-11-11, before the e17-e24 replays: from epoch 17 on, the clarity replay box also has the objective naming
the code location (workspace/meterbill), applied once on top of the e16 memory; the e1-e16 replays ran without it.

## claudemd seed (the whole file before epoch 1)

    # meterbill

    Usage-billing library (Python 3.12, stdlib only). Code: workspace/meterbill.

    ## Keeping this file current
    This file is the project's memory between sessions. At the end of every session, update it:
    - Overview and architecture: what each module does, kept short.
    - Decisions: rules we follow, each with its reason. Say when a decision replaced an older one.
    - Rejected approaches: what was tried and removed, and why, so nobody tries it again.
    - In progress: anything left half done, what is left and what to do first.
    - Next: work the user has said is coming.
    Keep it under 200 lines; prune what no longer matters, but never drop a decision or a
    rejected approach that still applies.

## replay prompt (identical in both written arms)

    A work session on this project just ended. Its record is below: the user's request, the
    agent's final report, and the files it changed. The code is already committed; do not change
    any code under workspace/. Bring the project's memory up to date the way this project's
    instructions say to — as the agent that did the work would have before ending the session.

    <session>
    ## User's request
    {prompt}
    ## Agent's final report
    {report}
    ## Files changed
    {diffstat}
    </session>

## task sessions (all arms)

- `claude -p --model sonnet --setting-sources project,local --strict-mcp-config --no-session-persistence --output-format stream-json --verbose`
  (project,local keeps the owner's ~/.claude/CLAUDE.md out; checked 2026-11-11: answers NONE)
- tools allowed: Bash, Read, Edit, Write, Grep, Glob; disallowed: Agent/Task, WebFetch, WebSearch
- prompt: the task's prompt verbatim, nothing else
- `clarity-ctl` on PATH in the clarity arm only; removed from PATH in the others
