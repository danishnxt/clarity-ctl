"""The scripted workload, and the questions asked at each checkpoint.

The workload is built from blocks of eight sessions. Each block has the same
shape, so any checkpoint taken at a block boundary contains every kind of
history: features, an experiment and its verdict, a product decision, a bug, a
piece of work stopped halfway, and backlog ideas.

    1  finish the work the previous block's session 7 stopped on (block 0: a feature)
    2  try an experiment on its own branch
    3  a feature, plus a product decision that rules something out
    4  a bug report, with the fix the user wants
    5  the user's verdict on the experiment, with the reason
    6  a feature
    7  a feature, stopped halfway: part B is for a later session
    8  two ideas for later

Ideas from block k are built as features in block k+2, so older ideas go stale
and the probes can ask whether one was ever built.

Every session is a fresh `claude -p` with no memory of the last. The prompts
carry decisions and reasons the way a user would say them, and never say "write
this down": whether anything is recorded is up to each arm's instructions. The
probes check only facts these prompts fix, so every arm is graded against the
same answers whatever the agent happened to find.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

OBJECTIVE = "Make logstat a fast, correct summariser for nginx combined access logs"
SESSIONS_PER_BLOCK = 8

# ------------------------------------------------------------------- pools

# Features that are never an idea first, for the slots before promoted ideas exist.
PLAIN = [
    "Add a `--top N` flag that prints the N most requested paths with their counts. Off by default.",
    "Add a status-class breakdown (2xx/3xx/4xx/5xx counts) to the default output.",
    "Add `--ip-top N`, printing the N busiest client IPs with their request counts.",
    "Accept `-` as the log file to read from stdin.",
    "Add `--method M` to count only requests with that HTTP method, e.g. `--method POST`.",
]

# Work stopped halfway: (name, part A, part B). Session 7 asks for A only and
# says B is for next time; session 1 of the next block asks to finish it.
SPLIT = [
    ("time-range filtering",
     "`--since TIMESTAMP`, an ISO timestamp in UTC; earlier requests are skipped",
     "`--until TIMESTAMP`, also ISO in UTC; later requests are skipped"),
    ("JSON output",
     "`--format json` printing the summary totals (requests, bytes, unique IPs) as one JSON object",
     "every other section the text output has (status classes, --top, --ip-top) included in the JSON object"),
    ("hourly histogram",
     "`--hourly`, printing the request count for each hour of the day (UTC)",
     "`--bars`, which draws each `--hourly` count as a row of `#` scaled to 40 columns"),
    ("path exclusion",
     "`--exclude GLOB`, dropping requests whose path matches the glob",
     "`--exclude` repeatable, plus `--exclude-file FILE` reading one glob per line"),
    ("response size stats",
     "p50 and p95 of response size in bytes in the default output",
     "`--size-by-path`, printing the p95 response size for each path"),
    ("multiple log files",
     "several log files on the command line, merged into one summary",
     "`--per-file`, adding a request count for each file under the merged summary"),
    ("user-agent families",
     "a breakdown of requests by user-agent family: curl, browser, bot, other",
     "`--no-bots`, excluding bot requests from every statistic"),
    ("not-found report",
     "`--not-found`, listing the 10 most requested paths that returned 404",
     "each `--not-found` path followed by its top 3 referrers"),
]

# (short name, what the user says, the flag it ends up as). The first twelve get
# built two blocks after they come up; the last four never do.
IDEAS = [
    ("gzip input", "reading .gz log files directly, without unzipping first", "`.gz` files read transparently"),
    ("CSV output", "a `--format csv` output mode", "`--format csv`"),
    ("error rate", "printing the percentage of 5xx responses", "an error-rate line in the default output"),
    ("status filter", "a `--status` filter, like `--status 5xx` or `--status 404`", "`--status`"),
    ("referrer domains", "top referrer domains", "`--referrers N`"),
    ("daily visitors", "unique visitors (IPs) per day", "`--daily`"),
    ("head limit", "only reading the first N lines of a log", "`--head N`"),
    ("quiet mode", "a mode that prints bare numbers without labels, for scripts", "`--quiet`"),
    ("minimum count", "hiding paths below a count in `--top`", "`--min-count N`"),
    ("bytes by path", "total bytes served per path", "`--bytes-by-path`"),
    ("path prefix", "only counting paths under a prefix, like `/api/`", "`--path-prefix P`"),
    ("peak minute", "showing the busiest minute and its request count", "`--peak`"),
    ("HTML report", "an HTML report with charts", None),
    ("Prometheus export", "exporting the stats as Prometheus metrics", None),
    ("GeoIP breakdown", "a per-country breakdown using GeoIP", None),
    ("Slack alerts", "a Slack alert when the 5xx rate passes a threshold", None),
]

# Experiments: what to try, the verdict prompt, and the facts the verdict fixes.
EXPERIMENTS = [
    dict(kept=False, topic="parsing lines with str.split() instead of the regex",
         ask="replace the regex parser with plain `str.split()` parsing",
         verdict="Drop the str.split() parser, don't merge it: it mis-parses user agents that contain "
                 "spaces, like the Firefox line in sample.log. Instead, keep the regex but compile it once "
                 "at module level, measure that against the original, and commit it to main if it is not slower.",
         facts=["a str.split() parser was tried and dropped",
                "the reason: it mis-parses user agents containing spaces",
                "the regex was kept, precompiled at module level instead"]),
    dict(kept=True, topic="parsing timestamps by slicing instead of strptime",
         ask="replace `datetime.strptime` with slicing the fixed-format timestamp and building the datetime by hand",
         verdict="The timestamp slicing experiment: merge it into main. It's correct on sample.log and the "
                 "speedup is worth it.",
         facts=["timestamps are parsed by slicing instead of strptime",
                "it was merged (kept) because it was correct and faster"]),
    dict(kept=False, topic="parsing in parallel with multiprocessing",
         ask="split the file into chunks and parse them in parallel with `multiprocessing`",
         verdict="Drop the multiprocessing experiment, don't merge it: process start-up and pickling make it "
                 "slower below about 500k lines, and that's most of our logs.",
         facts=["parallel parsing with multiprocessing was tried and dropped",
                "the reason: start-up and pickling overhead make it slower below about 500k lines, most of our logs"]),
    dict(kept=False, topic="caching parsed results in a sidecar file",
         ask="cache the parsed records in a pickle file next to the log, reused when the log hasn't changed",
         verdict="Drop the cache experiment, don't merge it: logs get rotated in place, and a stale cache "
                 "would silently give wrong numbers. Correctness beats speed here.",
         facts=["a pickle sidecar cache of parsed results was tried and dropped",
                "the reason: logs rotate in place, so a stale cache could silently give wrong numbers"]),
    dict(kept=False, topic="aggregating with pandas",
         ask="load the parsed records into a pandas DataFrame and do the aggregation there",
         verdict="Drop the pandas experiment, don't merge it: it breaks the stdlib-only rule, and the "
                 "speedup doesn't justify a heavy dependency.",
         facts=["pandas aggregation was tried and dropped",
                "the reason: it breaks the stdlib-only (no third-party dependencies) rule"]),
    dict(kept=True, topic="streaming the summary without building a list of records",
         ask="make `summarise` stream over the lines and keep running totals instead of building a list of records",
         verdict="The streaming summarise experiment: merge it into main. Memory stays flat on big logs.",
         facts=["summarise was changed to stream with running totals instead of a list of records",
                "it was merged (kept) because memory stays flat on big logs"]),
    dict(kept=False, topic="reading the log with mmap",
         ask="read the log through `mmap` instead of normal file iteration",
         verdict="Drop the mmap experiment, don't merge it: there's no measurable gain, I/O isn't the bottleneck.",
         facts=["reading through mmap was tried and dropped",
                "the reason: no measurable gain, I/O is not the bottleneck"]),
    dict(kept=True, topic="parsing timestamps lazily",
         ask="only parse the timestamp when something needs it (a time filter or --hourly), "
             "and skip it otherwise",
         verdict="The lazy timestamp experiment: merge it into main. Most runs don't need times at all.",
         facts=["timestamps are parsed lazily, only when a time filter or --hourly needs them",
                "it was merged (kept) because most runs don't need times"]),
]

# Decisions, said in passing at the end of a feature session.
DECISIONS = [
    dict(say="a customer asked for JSON-lines log input. We are not doing it: we support nginx combined "
             "format only, and the customer agreed to convert on their side.",
         q="A customer wants logstat to read JSON-lines logs. Has this come up before, and what did we decide?",
         facts=["it came up before and was decided against",
                "logstat supports nginx combined format only",
                "the customer agreed to convert on their side"]),
    dict(say="from now on logstat stays stdlib-only, no third-party runtime dependencies. It has to install "
             "on locked-down ops boxes that have no pip access.",
         q="Can logstat take on a third-party dependency, like `rich` for nicer tables? Is there a rule about that?",
         facts=["no: logstat is stdlib-only, no third-party runtime dependencies",
                "the reason: it must install on locked-down ops boxes without pip access"]),
    dict(say="the minimum Python stays 3.10, so no 3.11+ features like tomllib or ExceptionGroup. The ops "
             "servers run 3.10.",
         q="Can I use `tomllib` in logstat? Is there a Python version constraint?",
         facts=["no: Python 3.10 is the minimum, so no 3.11+ features like tomllib",
                "the reason: the ops servers run Python 3.10"]),
    dict(say="no config file, ever. Flags only: ops wants every cron line to say exactly what it runs.",
         q="Should logstat read defaults from a config file like ~/.logstatrc? Has that been decided?",
         facts=["decided against: no config file, flags only",
                "the reason: ops wants every cron line to say exactly what it runs"]),
    dict(say="the default text output is a contract now. Existing scripts parse it, so any change to it goes "
             "behind a flag.",
         q="I'd like to reword the labels in logstat's default output. Is anything stopping me?",
         facts=["the default text output must not change: scripts parse it",
                "changes to it have to go behind a flag"]),
    dict(say="someone asked for Apache common log format. Not this year: it's out of scope until next year's "
             "planning.",
         q="Does logstat support Apache common log format, or was it ever planned?",
         facts=["it was asked for and deferred",
                "out of scope until next year's planning"]),
    dict(say="times are always reported in UTC, never local time. Our servers are in several regions and "
             "mixing local times caused a bad incident report once.",
         q="Should logstat show times in the server's local timezone? Has this been settled?",
         facts=["settled: always UTC, never local time",
                "the reason: servers in several regions; mixed local times once caused a bad incident report"]),
    dict(say="no --watch or tail mode. Use `tail -f access.log | logstat -` instead.",
         q="Can we add a --watch mode that follows a growing log? Was that ever discussed?",
         facts=["decided against a --watch/tail mode",
                "use `tail -f access.log | logstat -` instead"]),
]

BUGS = [
    dict(say="timestamps ignore the timezone offset, so the +0530 line in sample.log is treated as 15:30 UTC "
             "instead of 10:00 UTC. Normalise every time to UTC and add a test for the +0530 line.",
         q="Has logstat ever had a timezone bug? What was it and how was it fixed?",
         facts=["timestamps ignored the timezone offset (the +0530 line)",
                "fixed by normalising every time to UTC"]),
    dict(say="malformed lines are silently dropped. Count them and print `malformed: N` on stderr when N > 0.",
         q="What does logstat do with lines it can't parse, and was that always the case?",
         facts=["malformed lines used to be silently dropped",
                "now they are counted and `malformed: N` is printed on stderr"]),
    dict(say="`--top` lists paths with equal counts in a different order from run to run. Break ties "
             "alphabetically by path.",
         q="Was there a problem with the ordering of --top? What's the rule now?",
         facts=["--top tie order was not deterministic",
                "ties are now broken alphabetically by path"]),
    dict(say="paths with query strings are counted separately, so `/api/items?id=1` and `/api/items` are two "
             "paths. Strip the query string for all path statistics.",
         q="How does logstat treat query strings in paths, and why?",
         facts=["query strings used to split one path into many",
                "the query string is now stripped for path statistics"]),
    dict(say="`/login` and `/login/` are counted as different paths. Strip a trailing slash, except on `/` "
             "itself.",
         q="Are `/login` and `/login/` the same path in logstat's stats?",
         facts=["yes: a trailing slash is stripped (except on `/`), after a bug where they counted separately"]),
    dict(say="a log with non-UTF-8 bytes crashes logstat with a UnicodeDecodeError. Read with "
             "errors=\"replace\" instead, and add a test with a bad byte.",
         q="What happens if a log contains invalid UTF-8? Was that ever a problem?",
         facts=["it used to crash with a UnicodeDecodeError",
                "logs are now read with errors=\"replace\""]),
    dict(say="a missing log file gives a Python traceback. Print `logstat: no such file: PATH` and exit 2.",
         q="What does logstat do when the log file doesn't exist?",
         facts=["prints `logstat: no such file: PATH` and exits with status 2",
                "it used to show a traceback"]),
    dict(say="HEAD requests are counted in the byte totals, but they have no body. Exclude HEAD requests "
             "from byte totals.",
         q="Do HEAD requests count towards logstat's byte totals?",
         facts=["no: HEAD requests are excluded from byte totals",
                "this was a bug fix: they have no body but used to be counted"]),
]

NEVER = [
    "rewriting the parser as a Rust extension",
    "storing parsed logs in SQLite",
    "an asyncio-based reader",
    "exporting to Elasticsearch",
]


# --------------------------------------------------------------- building

@dataclass
class Probe:
    id: str
    q: str
    facts: list[str] = field(default_factory=list)


@dataclass
class Scenario:
    sessions: list[str]
    checkpoints: dict[int, list[Probe]]  # session count -> probes asked after it


def _commit(text):
    return f"{text} Add a test, and commit it to main when it works."


def build(blocks: int, checkpoints: list[int], seed: int = 7) -> Scenario:
    """Sessions for `blocks` blocks, and probes for each checkpoint (in blocks)."""
    if blocks > len(SPLIT):
        raise ValueError(f"at most {len(SPLIT)} blocks")
    sessions: list[str] = []
    plain = iter(PLAIN)
    history = []  # (block, kind, item) for everything that has happened

    for b in range(blocks):
        exp, dec, bug = EXPERIMENTS[b], DECISIONS[b], BUGS[b]
        name, part_a, part_b = SPLIT[b]
        built = [IDEAS[2 * (b - 2)], IDEAS[2 * (b - 2) + 1]] if b >= 2 else []
        feats = [f"Let's build the {i[0]} idea from the backlog: {i[1]}, as {i[2]}." for i in built]
        feats += [next(plain) for _ in range(2 - len(feats))]

        if b == 0:
            s1 = _commit(next(plain))
        else:
            s1 = f"Finish the {SPLIT[b - 1][0]} work the last session started. Commit to main when it works."
        sessions += [
            s1,
            f"logstat is slow on big logs (`python gen_log.py 300000 > big.log` makes one; don't commit "
            f"big.log). Try this: {exp['ask']}. Measure it against main on the same file. Keep the experiment "
            f"on its own branch, don't merge it yet, and tell me the numbers.",
            _commit(feats[0]) + f" Also: {dec['say']} Don't build anything for it.",
            f"Bug: {bug['say']} Commit the fix to main.",
            exp["verdict"],
            _commit(feats[1]),
            f"Start on {name}. Today only do part A: {part_a}, with a test, committed to main. Part B, for "
            f"the next session, is {part_b} — do not start it now. Stop after part A.",
            f"Two ideas for later, don't work on them now: {IDEAS[2 * b][1]}, and {IDEAS[2 * b + 1][1]}. "
            f"That's all for this session.",
        ]
        history += [(b, "exp", exp), (b, "dec", dec), (b, "bug", bug)]
        history += [(b, "built", i) for i in built]

    rng = random.Random(seed)
    cps = {}
    for c in checkpoints:
        if not 1 <= c <= blocks:
            raise ValueError(f"checkpoint {c} is outside 1..{blocks}")
        last = c - 1
        name, part_a, part_b = SPLIT[last]
        open_ideas = [IDEAS[2 * k] for k in range(max(0, last - 1), c)] + \
                     [IDEAS[2 * k + 1] for k in range(max(0, last - 1), c)]
        probes = [
            Probe("ok", "Reply with just the word ok. Don't use any tools."),
            Probe("resume", "I'm picking this project back up after a few weeks away. Get up to speed, then "
                            "tell me briefly where it stands and what I should do next.",
                  [f"{name}: part A ({part_a}) is done and part B ({part_b}) is the unfinished next step",
                   "open ideas not yet started include " + ", ".join(i[0] for i in open_ideas)]),
            Probe("handoff", "What did the last working session leave unfinished? Be specific.",
                  [f"part B of {name} is not started: {part_b}"]),
            Probe("perf", "List everything we've tried to make logstat faster, and what came of each.",
                  [f"{e['topic']}: {'merged (kept)' if e['kept'] else 'dropped'}"
                   for e in EXPERIMENTS[:c]]),
            Probe("never", f"Did we ever try {NEVER[rng.randrange(len(NEVER))]}? What came of it?",
                  ["there is no record of it ever being tried or discussed"]),
        ]
        # Recall from the first, middle and last block, so old facts are asked about too.
        seen = [h for h in history if h[0] <= last]
        for kind, ask in [("exp", lambda e: f"Did we ever try {e['topic']}? What happened, and why?"),
                          ("dec", lambda d: d["q"]), ("bug", lambda g: g["q"])]:
            pool = [h for h in seen if h[1] == kind]
            picks = {pool[0][0], pool[len(pool) // 2][0], pool[-1][0]}
            for b, _, item in [h for h in pool if h[0] in picks]:
                probes.append(Probe(f"{kind}-b{b}", ask(item), item["facts"]))
        built = [h for h in seen if h[1] == "built"]
        if built:
            b, _, idea = built[0]
            probes.append(Probe(f"idea-b{b}", f"Did the {idea[0]} idea from the backlog ever get built?",
                                [f"yes, it was built: {idea[2]}"]))
        cps[c * SESSIONS_PER_BLOCK] = probes
    return Scenario(sessions, cps)


# ----------------------------------------------------------- arm settings

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

For each fact, decide whether the answer contains it. A fact with several parts
counts only if every part is there. Reply with JSON only, no prose and no code
fence: {{"hits": [true/false per fact, in order], "notes": "<one line>"}}"""


if __name__ == "__main__":  # print the scenario, to read it without running anything
    import sys
    blocks = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    s = build(blocks, sorted({1, (blocks + 1) // 2, blocks}))
    for i, p in enumerate(s.sessions, 1):
        print(f"--- session {i}\n{p}")
    for c, ps in s.checkpoints.items():
        print(f"\n=== checkpoint after {c} sessions")
        for p in ps:
            print(f"[{p.id}] {p.q}")
            for f in p.facts:
                print(f"    - {f}")
