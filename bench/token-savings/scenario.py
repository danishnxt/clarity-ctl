"""The scripted workload and the questions asked afterwards.

Every session is a fresh `claude -p` with no memory of the last one, which is
the situation clarity exists for. The prompts are what a user would type: they
carry decisions and the reasons for them, but never say "write this down" —
whether anything gets recorded is up to each arm's own instructions.

The facts the probes check are fixed by these prompts, not by what the agent
happened to find, so every arm is graded against the same answers.
"""

OBJECTIVE = "Make logstat a fast, correct summariser for nginx combined access logs"

SESSIONS = [
    # 1 — a plain feature that lands
    "Add a `--top N` flag to logstat that prints the N most requested paths with "
    "their counts. Default off. Add a test. Commit it to main when it works.",

    # 2 — an experiment
    "logstat is slow on big logs (`python gen_log.py 300000 > big.log` makes one; "
    "don't commit big.log). Try replacing the regex parser with plain str.split() "
    "parsing and measure both on the same file. Keep the experiment on its own "
    "branch, don't merge it yet. Tell me the numbers.",

    # 3 — the user's verdict on it, with the reason
    "Drop the str.split() parser, don't merge it: it mis-parses user agents that "
    "contain spaces, like the Firefox line in sample.log. Instead, keep the regex "
    "but compile it once at module level and measure that against the original. "
    "Commit the compiled version to main if it is not slower.",

    # 4 — a feature plus a product decision that rules something out
    "Add a status-class breakdown (2xx/3xx/4xx/5xx counts) to the default output, "
    "with a test, and commit it to main. Also: a customer asked for JSON-lines log "
    "support. We are not doing it — we support nginx combined format only, the "
    "customer agreed to convert on their side. Don't build anything for it.",

    # 5 — a bug fix
    "Bug: timestamps ignore the timezone offset, so the +0530 line in sample.log "
    "is treated as 15:30 UTC instead of 10:00 UTC. Fix parsing so every time is "
    "normalised to UTC, add a test for the +0530 line, commit to main.",

    # 6 — work stopped halfway: the next session must know what's left
    "Start on time-range filtering: `--since` and `--until`, both taking ISO "
    "timestamps in UTC. We're out of time today, so only do `--since` (with a "
    "test, committed to main). `--until` is for the next session — do not start "
    "it now. Stop after `--since`.",

    # 7 — backlog that isn't started
    "Two ideas for later, don't work on them now: gzip-compressed log input "
    "(.gz files read directly), and a `--format csv` output mode. That's all for "
    "this session.",
]

# Asked in a fresh session after the workload. `facts` is the grading rubric:
# each one is something a correct answer must contain or imply.
PROBES = [
    {
        "id": "ok",
        "q": "Reply with just the word ok. Don't use any tools.",
        "facts": [],  # measures the always-loaded context, nothing else
    },
    {
        "id": "resume",
        "q": "I'm picking this project back up after a few weeks away. Get up to "
             "speed, then tell me briefly where it stands and what I should do next.",
        "facts": [
            "--since is done and --until is the unfinished next step",
            "the timezone/UTC bug was fixed",
            "gzip input and --format csv are open ideas not started",
        ],
    },
    {
        "id": "parser",
        "q": "Did we ever try a faster parser for logstat? What happened, and why?",
        "facts": [
            "a str.split() based parser was tried",
            "it was dropped because it mis-parses user agents containing spaces",
            "the regex was kept but precompiled at module level instead",
        ],
    },
    {
        "id": "json",
        "q": "A customer wants JSON-lines log support in logstat. Has this come up "
             "before, and what did we decide?",
        "facts": [
            "it came up before and was decided against",
            "logstat supports nginx combined format only",
            "the customer agreed to convert on their side",
        ],
    },
    {
        "id": "handoff",
        "q": "What did the last working session leave unfinished? Be specific.",
        "facts": [
            "--until was not started and is the remaining part of time-range filtering",
            "--until should take ISO timestamps in UTC like --since",
        ],
    },
]

# What each arm's agent is told, beyond the default Claude Code behaviour.
CLAUDE_MD_RULE = f"""# logstat

Objective: {OBJECTIVE}.

The code is in `workspace/logstat`, its own git repo.

Keep this file current. Sessions don't remember each other, so this file is the
only thing the next session has: record where the project stands, decisions and
the reasons for them, what was tried and what came of it, and what is unfinished.
"""

VANILLA_MD = f"""# logstat

Objective: {OBJECTIVE}.

The code is in `workspace/logstat`, its own git repo.
"""

RIPOUT_PROMPT = (
    "We're removing clarity-ctl from this project after this session; its files "
    "and the AGENTS.md block will be deleted. Before that, write everything a "
    "future session needs into CLAUDE.md at the project root, outside the clarity "
    "markers: where the project stands, decisions and their reasons, what was "
    "tried and what came of it, what is unfinished, and the open ideas. Read it "
    "all from clarity first. Don't change any code."
)

GRADER = """You grade an answer against a rubric. Question asked:
{q}

Rubric — facts a correct answer must state or clearly imply:
{facts}

Answer to grade:
<answer>
{answer}
</answer>

For each fact, decide whether the answer contains it. Reply with JSON only, no
prose and no code fence: {{"hits": [true/false per fact, in order], "notes": "<one line>"}}"""
