"""Decisions are records of their own, linked from notes, retired by a later decision.
Run: uv run -q --with pytest pytest -q tests/test_decisions.py"""

import json

import pytest
import yaml

from clarity import ClarityError, Project, agents, cli, render
from clarity.store import ARCHIVE


@pytest.fixture
def ctl(project, repo, capsys, monkeypatch):
    """ctl("note", "1", "text", "--decision") -> (exit code, stdout, stderr), on `project`."""
    monkeypatch.chdir(repo)

    def run(*argv):
        code = cli.main([*argv])
        out, err = capsys.readouterr()
        return code, out, err
    return run


def _worklog(repo) -> dict:
    return yaml.safe_load((repo / "worklog.yaml").read_text())


def _fresh(project) -> Project:
    return Project.find(project.root)


def _digest(repo) -> str:
    text = (repo / "AGENTS.md").read_text()
    return text[text.index("### Where things stand"):text.index(agents.END)].rstrip()


# ---- recording --------------------------------------------------------------------------


def test_a_decision_is_a_record_not_a_note(project, repo, ctl):
    idea = project.add("parser")
    code, out, _ = ctl("note", str(idea.id), "stdlib only, no pip on the ops boxes", "--decision")
    assert (code, out.strip()) == (0, f"D1 recorded on #{idea.id}.")
    raw = _worklog(repo)
    assert raw["version"] == 3
    [d] = raw["decisions"]
    assert d["id"] == "D1" and d["epoch"] == idea.id and d["replaces"] == []
    assert d["replaced_by"] is None and d["retired"] is None and d["at"]
    assert "notes" not in raw["items"][0]            # no duplicate note


def test_the_flag_goes_before_or_after_the_text(project, ctl):
    idea = project.add("parser")
    assert ctl("note", str(idea.id), "--decision", "first")[0] == 0
    assert ctl("note", str(idea.id), "second", "--decision")[0] == 0
    assert [d.id for d in _fresh(project).worklog.decisions] == ["D1", "D2"]


def test_a_decision_can_be_made_in_a_closed_and_an_archived_epoch(project, ctl):
    idea = project.add("old work")
    project.close(idea.id, "done elsewhere")
    assert ctl("note", str(idea.id), "made after close", "--decision")[0] == 0
    project.archive()
    code, out, _ = ctl("note", str(idea.id), "made once archived", "--decision")
    assert code == 0 and out.startswith(f"D2 recorded on #{idea.id}")


def test_a_decision_in_an_epoch_that_does_not_exist_is_refused(ctl):
    code, _, err = ctl("note", "99", "x", "--decision")
    assert code == 4 and "no item with id 99" in err


def test_replacing_retires_the_old_one_and_links_both_ways(project, repo, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "stdlib only", "--decision")
    code, out, _ = ctl("note", str(idea.id), "pip is fine now", "--decision",
                       "--replaces", "D1")
    assert (code, out.strip()) == (0, f"D2 recorded on #{idea.id}; D1 retired.")
    d1, d2 = _fresh(project).worklog.decisions
    assert d1.replaced_by == "D2" and d1.retired["why"] == "replaced by D2"
    assert d2.replaces == ["D1"] and d2.standing and d2.replaced_by is None
    assert d1.retired["at"]


def test_one_decision_can_replace_several(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("note", str(idea.id), "no network", "--decision")
    code, out, _ = ctl("note", str(idea.id), "no pip and no network, both",
                       "--decision", "--replaces", "D1,D2")
    assert code == 0 and out.strip() == f"D3 recorded on #{idea.id}; D1, D2 retired."
    d1, d2, d3 = _fresh(project).worklog.decisions
    assert d1.replaced_by == d2.replaced_by == "D3" and d3.replaces == ["D1", "D2"]


def test_a_retired_target_is_refused_naming_its_successor(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("note", str(idea.id), "pip ok", "--decision", "--replaces", "D1")
    code, _, err = ctl("note", str(idea.id), "pip ok, pinned", "--decision", "--replaces", "D1")
    assert code == 2 and "D1 was replaced by D2; replace D2" in err
    assert len(_fresh(project).worklog.decisions) == 2     # nothing recorded


def test_a_decision_retired_without_a_successor_cannot_be_replaced(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("close", "D1", "no longer true")
    code, _, err = ctl("note", str(idea.id), "x", "--decision", "--replaces", "D1")
    assert code == 2 and "D1 is already retired" in err


def test_replacing_a_decision_that_does_not_exist_is_refused(project, ctl):
    idea = project.add("parser")
    code, _, err = ctl("note", str(idea.id), "x", "--decision", "--replaces", "D5")
    assert code == 2 and "no decision D5" in err
    code, _, err = ctl("note", str(idea.id), "x", "--decision", "--replaces", "seven")
    assert code == 2 and "decision ids" in err


def test_replaces_needs_decision_and_on_cannot_be_decision(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    code, _, err = ctl("note", str(idea.id), "x", "--replaces", "D1")
    assert code == 2 and "--decision" in err
    code, _, err = ctl("note", str(idea.id), "x", "--decision", "--on", "D1")
    assert code == 2 and "--on" in err


def test_without_replaces_the_closest_standing_decisions_are_offered(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "the ops boxes have no pip so the parser is stdlib only",
        "--decision")
    ctl("note", str(idea.id), "benchmarks run on the nightly queue only", "--decision")
    ctl("note", str(idea.id), "colour output is off unless stdout is a terminal", "--decision")
    code, out, _ = ctl("note", str(idea.id),
                       "the ops boxes now have pip, so the parser may use packages", "--decision")
    lines = out.splitlines()
    assert lines[0] == f"D4 recorded on #{idea.id}."
    assert lines[1] == "Does D4 replace any of these? close D<n> --by D4"
    assert lines[2].startswith("  D1 ") and len(lines) == 3   # the others read as unrelated


def test_nothing_is_offered_when_no_decision_reads_close(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "benchmarks run on the nightly queue only", "--decision")
    code, out, _ = ctl("note", str(idea.id), "colour output is off unless stdout is a terminal",
                       "--decision")
    assert out.strip() == f"D2 recorded on #{idea.id}."


def test_a_retired_decision_is_never_offered(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "the ops boxes have no pip so the parser is stdlib only",
        "--decision")
    ctl("close", "D1", "obsolete")
    _, out, _ = ctl("note", str(idea.id), "the ops boxes have pip so the parser may use packages",
                    "--decision")
    assert "Does" not in out


def test_the_old_prefix_is_refused_with_the_new_way(project, ctl):
    idea = project.add("parser")
    for text in ("DECISION: stdlib only", "  decision: stdlib only"):
        code, _, err = ctl("note", str(idea.id), text)
        assert code == 2 and "--decision" in err
        code, _, err = ctl("note", str(idea.id), text, "--decision")
        assert code == 2
    assert not _fresh(project).worklog.decisions
    assert not _fresh(project).worklog.by_id(idea.id).notes


# ---- linking notes ------------------------------------------------------------------------


def test_a_note_links_to_decisions_and_the_link_is_stored_as_given(project, repo, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("note", str(idea.id), "no network", "--decision")
    code, out, _ = ctl("note", str(idea.id), "ops confirmed both", "--on", "D1",
                       "--on", "d2")
    assert code == 0 and "linked to D1, D2" in out
    [note] = _worklog(repo)["items"][0]["notes"]
    assert note["decision"] == ["D1", "D2"] and note["text"] == "ops confirmed both"


def test_linking_to_a_decision_that_does_not_exist_writes_nothing(project, ctl):
    idea = project.add("parser")
    code, _, err = ctl("note", str(idea.id), "x", "--on", "D9")
    assert code == 2 and "no decision D9" in err
    assert not _fresh(project).worklog.by_id(idea.id).notes


def test_linking_to_a_retired_decision_is_fine(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("close", "D1", "obsolete")
    assert ctl("note", str(idea.id), "why it went", "--on", "D1")[0] == 0


def test_a_linked_note_reads_through_the_chain_to_where_the_decision_stands(project, repo, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "v1", "--decision")
    ctl("note", str(idea.id), "ops confirmed it", "--on", "D1")
    ctl("note", str(idea.id), "v2", "--decision", "--replaces", "D1")
    ctl("note", str(idea.id), "v3", "--decision", "--replaces", "D2")
    ctl("note", str(idea.id), "about the live one", "--on", "D3")
    _, out, _ = ctl("show", str(idea.id))
    assert "ops confirmed it (D1 → D3)" in out
    assert "about the live one (D3)" in out
    # the stored link never changes
    assert _worklog(repo)["items"][0]["notes"][0]["decision"] == ["D1"]
    # and when the end of the chain is closed with no successor, it says so
    ctl("close", "D3", "gone")
    assert "ops confirmed it (D1 → D3 retired)" in ctl("show", str(idea.id))[1]


def test_a_note_links_show_in_the_terminal_page_too(project, ctl, tty):
    idea = project.add("parser")
    ctl("note", str(idea.id), "v1", "--decision")
    ctl("note", str(idea.id), "ops confirmed it", "--on", "D1")
    ctl("note", str(idea.id), "v2", "--decision", "--replaces", "D1")
    out = ctl("show", str(idea.id))[1]
    assert "ops confirmed it (D1 → D2)" in out and "Decisions (2)" in out


# ---- retiring ---------------------------------------------------------------------------


def test_close_retires_a_decision_with_a_reason(project, repo, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    code, out, _ = ctl("close", "D1", "the ops boxes have pip now")
    assert (code, out.strip()) == (0, "D1 retired: the ops boxes have pip now")
    [d] = _worklog(repo)["decisions"]
    assert d["retired"]["why"] == "the ops boxes have pip now" and d["replaced_by"] is None
    assert _fresh(project).worklog.by_id(idea.id).status == "idea"   # the epoch is untouched


def test_close_a_decision_needs_a_reason_and_never_asks(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    code, _, err = ctl("close", "D1")
    assert code == 2 and 'close D1 "<why>"' in err
    assert _fresh(project).worklog.decision("D1").standing


def test_close_a_decision_refuses_drop_and_a_second_retirement(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    code, _, err = ctl("close", "D1", "--drop", "why")
    assert code == 2 and "--drop" in err
    assert ctl("close", "D1", "obsolete")[0] == 0
    code, _, err = ctl("close", "D1", "again")
    assert code == 4 and "already retired" in err


def test_close_by_links_after_the_fact(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("note", str(idea.id), "pip is fine", "--decision")
    code, out, _ = ctl("close", "D1", "--by", "D2")
    assert (code, out.strip()) == (0, "D1 retired: replaced by D2")
    d1, d2 = _fresh(project).worklog.decisions
    assert d1.replaced_by == "D2" and d2.replaces == ["D1"]
    assert d1.retired["why"] == "replaced by D2"


def test_close_by_takes_a_reason_too(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("note", str(idea.id), "pip is fine", "--decision")
    assert ctl("close", "D1", "--by", "D2", "ops has pip")[0] == 0
    assert _fresh(project).worklog.decision("D1").retired["why"] == "ops has pip"


def test_close_by_refusals(project, ctl):
    idea = project.add("parser")
    for text in ("a", "b", "c"):
        ctl("note", str(idea.id), text, "--decision")
    ctl("close", "D3", "gone")
    code, _, err = ctl("close", "D1", "--by", "D1")
    assert code == 2 and "itself" in err
    code, _, err = ctl("close", "D1", "--by", "D3")
    assert code == 2 and "D3 is retired" in err
    code, _, err = ctl("close", "D1", "--by", "D9")
    assert code == 2 and "no decision D9" in err
    code, _, err = ctl("close", "D1", "--by", "nine")
    assert code == 2
    assert _fresh(project).worklog.decision("D1").standing


def test_by_is_only_for_a_decision(project, ctl):
    idea = project.add("parser")
    code, _, err = ctl("close", str(idea.id), "done", "--by", "D1")
    assert code == 2 and "--by" in err


def test_retiring_a_decision_needs_no_lease_branch_or_merge(project, ctl):
    epoch, _ = project.start(project.add("work").id)          # active, leased, branched
    ctl("note", str(epoch.id), "no pip", "--decision")
    assert ctl("close", "D1", "obsolete")[0] == 0
    assert _fresh(project).worklog.by_id(epoch.id).status == "active"


# ---- reading ----------------------------------------------------------------------------


def _lineage(project, ctl):
    """D1 <- D2 <- D3, with notes on each: one from an epoch that is then archived."""
    a = project.add("first thinking")
    b = project.add("second thinking")
    ctl("note", str(a.id), "v1: no pip", "--decision")
    ctl("note", str(a.id), "ops said so", "--on", "D1")
    ctl("note", str(b.id), "v2: pip pinned", "--decision", "--replaces", "D1")
    ctl("note", str(b.id), "pins live in lock.txt", "--on", "D2")
    ctl("note", str(b.id), "v3: uv only", "--decision", "--replaces", "D2")
    ctl("note", str(b.id), "uv is on every box", "--on", "D3")
    project.close(a.id, "done")
    project.archive()                                          # a's note is archived now
    return a, b


def test_show_a_decision_walks_back_through_what_it_replaced(project, ctl):
    a, b = _lineage(project, ctl)
    code, out, _ = ctl("show", "D3")
    lines = out.splitlines()
    assert code == 0 and lines[0].startswith(f"D3 standing · #{b.id} · ")
    assert lines[1] == "v3: uv only"
    assert "Notes (1)" in lines and any(l.endswith("] uv is on every box") for l in lines)
    assert "Replaced (2)" in lines
    # D2 then D1, one line each, each followed by the notes linked to it from any item
    [d2] = [i for i, l in enumerate(lines) if l.strip().startswith("D2 retired · ")]
    assert lines[d2].endswith(": v2: pip pinned")
    assert lines[d2 + 1].strip().startswith(f"#{b.id} [") and "pins live in lock.txt" in lines[d2 + 1]
    [d1] = [i for i, l in enumerate(lines) if l.strip().startswith("D1 retired · ")]
    assert d1 > d2 and lines[d1].endswith(": v1: no pip")
    assert lines[d1 + 1].strip().startswith(f"#{a.id} [") and "ops said so" in lines[d1 + 1]


def test_show_a_retired_decision_says_where_it_stands_now(project, ctl):
    _lineage(project, ctl)
    first = ctl("show", "d1")[1].splitlines()[0]
    assert first.startswith("D1 retired → D3 · ")
    assert "retired " in ctl("show", "D1")[1]                  # when, and why: replaced by D2
    assert "replaced by D2" in ctl("show", "D1")[1]


def test_show_a_decision_closed_with_no_replacement(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("close", "D1", "obsolete")
    out = ctl("show", "D1")[1]
    assert out.splitlines()[0].startswith("D1 retired, no replacement · ")
    assert "retired " in out and "obsolete" in out


def test_show_a_merge_lists_both_ancestors_once(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("note", str(idea.id), "no network", "--decision")
    ctl("note", str(idea.id), "both", "--decision", "--replaces", "D1,D2")
    out = ctl("show", "D3")[1]
    assert "Replaced (2)" in out and out.count("D1 retired") == 1 and "D2 retired" in out


def test_show_decision_that_does_not_exist(project, ctl):
    code, _, err = ctl("show", "D4")
    assert code == 4 and "no decision D4" in err


def test_show_decisions_lists_standing_first_then_the_retired(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("note", str(idea.id), "pip is fine", "--decision", "--replaces", "D1")
    ctl("note", str(idea.id), "colour only on a terminal", "--decision")
    ctl("note", str(idea.id), "ship on fridays", "--decision")
    ctl("close", "D4", "we ship any day")
    out = ctl("show", "decisions")[1]
    assert out.splitlines() == [
        "Standing (2)",
        f"- D3 (#{idea.id}) colour only on a terminal",
        f"- D2 (#{idea.id}) pip is fine",
        "Retired (2)",
        "- D4 ✗ ship on fridays (closed: we ship any day)",
        "- D1 → D2 no pip",
    ]


def test_show_decisions_with_none(project, ctl):
    assert ctl("show", "decisions")[1].strip() == "no decisions yet"


def test_show_an_epoch_lists_the_decisions_it_made(project, ctl):
    a, b = _lineage(project, ctl)
    out = ctl("show", str(b.id))[1]
    assert "Decisions (2)" in out
    assert "- D2 retired → D3: v2: pip pinned" in out
    assert "- D3 standing: v3: uv only" in out
    # an epoch that made none has no section
    assert "Decisions" not in ctl("show", str(project.add("quiet").id))[1]
    # an archived epoch still lists its own
    assert "- D1 retired → D3: v1: no pip" in ctl("show", str(a.id))[1]


def test_search_finds_a_decision_by_its_text_beside_the_items(project, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "the tokenizer stays single threaded", "--decision")
    ctl("note", str(idea.id), "multithreading tried first", "--decision", "--replaces", "D1")
    project.add("tokenizer cleanup")
    out = ctl("search", "tokenizer", "threaded")[1]
    lines = out.splitlines()
    assert any(l.startswith("D1 retired the tokenizer") for l in lines)
    assert not any(l.startswith("#D1") for l in lines)
    assert any(l.startswith("#2 idea tokenizer cleanup") for l in lines)
    data = json.loads(ctl("search", "tokenizer", "threaded", "--json")[1])["data"]
    hit = next(h for h in data["hits"] if h["id"] == "D1")
    assert hit["status"] == "retired" and "single threaded" in hit["snippet"]


def test_a_search_with_no_decisions_is_what_it_was(project, ctl):
    project.add("tokenizer cleanup")
    assert ctl("search", "tokenizer")[1].startswith("#1 idea tokenizer cleanup")


# ---- every other verb ------------------------------------------------------------------


@pytest.mark.parametrize("argv", [
    ["start", "D7", "--repo", "none"], ["rename", "D7", "new"], ["claim", "D7"],
    ["spawn", "D7", "part"], ["refresh", "D7"], ["add-repo", "D7", "x"],
    ["drop-repo", "D7", "x"], ["note", "D7", "text"], ["note", "d7", "text"],
])
def test_other_verbs_refuse_a_decision_id(project, ctl, argv):
    code, out, err = ctl(*argv)
    assert code == 2 and out == ""
    assert "D7 is a decision" in err
    if argv[0] != "note":
        assert f"{argv[0]} takes an epoch id" in err
    else:
        assert "--on D7" in err


# ---- JSON ----------------------------------------------------------------------------------


def test_json_shapes(project, ctl):
    a, b = _lineage(project, ctl)
    one = json.loads(ctl("show", "D2", "--json")[1])
    assert one["command"] == "show.decision"
    d = one["data"]
    assert {"id", "epoch", "text", "at", "status", "replaces", "replaced_by", "retired",
            "notes", "history"} <= set(d)
    assert (d["id"], d["status"], d["replaces"], d["replaced_by"], d["epoch"]) == (
        "D2", "retired", ["D1"], "D3", b.id)
    assert d["retired"]["why"] == "replaced by D3" and d["now"] == "D3"
    assert [n["item"] for n in d["notes"]] == [b.id]
    assert [h["id"] for h in d["history"]] == ["D1"]
    assert d["history"][0]["notes"][0]["text"] == "ops said so"      # the archived epoch's

    many = json.loads(ctl("show", "decisions", "--json")[1])
    assert many["command"] == "show.decisions"
    assert [x["id"] for x in many["data"]["standing"]] == ["D3"]
    assert [x["id"] for x in many["data"]["retired"]] == ["D2", "D1"]

    item = json.loads(ctl("show", str(b.id), "--json")[1])["data"]
    assert item["decisions"] == ["D2", "D3"]
    assert item["notes"][0]["decision"] == ["D2"]
    assert "decisions" not in json.loads(ctl("show", str(project.add("q").id), "--json")[1])["data"]


# ---- the agent block ---------------------------------------------------------------------


def test_the_block_lists_standing_decisions_newest_first_and_never_a_retired_one(
        project, repo, ctl):
    idea = project.add("parser")
    ctl("note", str(idea.id), "no pip", "--decision")
    ctl("note", str(idea.id), "colour only on a terminal", "--decision")
    ctl("note", str(idea.id), "pip is fine", "--decision", "--replaces", "D1")
    digest = _digest(repo)
    section = digest.split("**Standing decisions**, newest first")[1].split("\n\n")[0]
    assert section.strip().splitlines() == [
        f"- pip is fine (D3, #{idea.id})", f"- colour only on a terminal (D2, #{idea.id})"]
    assert "no pip" not in digest
    ctl("close", "D2", "obsolete")
    assert "colour only" not in _digest(repo)


def test_the_block_points_at_show_decisions_for_the_rest(project, repo):
    idea = project.add("parser")
    for n in range(render.DIGEST_DECISIONS + 3):
        project.decide(idea.id, f"rule number {n}")
    digest = _digest(repo)
    assert f"- 3 older: `clarity-ctl show decisions`" in digest
    assert "rule number 22 (D23" in digest and "rule number 2 (D3" not in digest
    assert "search DECISION" not in digest


def test_the_block_has_no_decision_heading_when_none_stand(project, repo):
    idea = project.add("parser")
    project.decide(idea.id, "no pip")
    project.retire_decision("D1", "obsolete")
    assert "Standing decisions" not in _digest(repo)


def test_the_instructions_teach_the_new_commands(project, repo):
    text = (repo / "AGENTS.md").read_text()
    assert '--decision' in text and "--replaces D<n>" in text and "--on D<n>" in text
    assert 'close D<n> "<why>"' in text and "DECISION:" not in text


# ---- EPOCH.md ------------------------------------------------------------------------------


def test_epoch_md_follows_a_decision_that_is_retired_from_another_epoch(project, repo):
    first, _ = project.start(project.add("first").id)
    second, _ = project.start(project.add("second").id)
    project.decide(first.id, "no pip")
    project.note(first.id, "ops said so", on=["D1"])
    page = (repo / first.folder / "EPOCH.md")
    assert "- **D1** standing: no pip" in page.read_text()
    assert "ops said so (D1)" in page.read_text()
    project.decide(second.id, "pip is fine", replaces=["D1"])      # a write in the other epoch
    text = page.read_text()
    assert "- **D1** retired → D2: no pip" in text and "ops said so (D1 → D2)" in text


# ---- migration -----------------------------------------------------------------------------


def _v2(repo, edit):
    path = repo / "worklog.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["version"] = 2
    raw.pop("decisions", None)
    edit(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def test_a_version_2_worklog_turns_decision_notes_into_records(project, repo):
    one = project.add("one")
    two = project.add("two")
    three = project.add("three")
    project.close(three.id, "done elsewhere")

    def edit(raw):
        by = {i["id"]: i for i in raw["items"]}
        by[one.id]["notes"] = [
            {"at": "2026-03-02 09:00", "text": "DECISION: later one"},
            {"at": "2026-03-02 09:05", "text": "a plain note"}]
        by[two.id]["notes"] = [{"at": "2026-03-01 08:00", "text": "DECISION: earlier one"}]
        by[three.id]["notes"] = [{"at": "2026-03-01 12:00", "text": "DECISION: middle one"}]
    _v2(repo, edit)

    worklog = Project.find(repo).worklog
    assert [(d.id, d.epoch, d.text, d.at) for d in worklog.decisions] == [
        ("D1", two.id, "earlier one", "2026-03-01 08:00"),
        ("D2", three.id, "middle one", "2026-03-01 12:00"),
        ("D3", one.id, "later one", "2026-03-02 09:00")]
    assert all(d.standing and d.replaces == [] and d.replaced_by is None
               for d in worklog.decisions)
    assert [n.text for n in worklog.by_id(one.id).notes] == ["a plain note"]   # no duplicate
    assert worklog.by_id(two.id).notes == []
    assert yaml.safe_load((repo / "worklog.yaml").read_text())["version"] == 2  # a read writes nothing

    project.add("next write")
    raw = _worklog(repo)
    assert raw["version"] == 3 and [d["id"] for d in raw["decisions"]] == ["D1", "D2", "D3"]
    assert "DECISION" not in (repo / "worklog.yaml").read_text()
    assert project.add("again").id and _fresh(project).worklog.next_decision_id() == "D4"


def test_migration_reaches_decision_notes_in_the_archive(project, repo):
    kept = project.add("kept")
    old = project.add("old")
    project.close(old.id, "done")
    [(name, _)] = project.archive()
    archive = repo / ARCHIVE / name
    raw = yaml.safe_load(archive.read_text())
    raw["items"][0]["notes"] = [{"at": "2026-03-01 08:00", "text": "DECISION: from the archive"},
                                {"at": "2026-03-01 08:01", "text": "kept note"}]
    raw["version"] = 2
    archive.write_text(yaml.safe_dump(raw, sort_keys=False))
    _v2(repo, lambda r: r["items"][0].update(
        notes=[{"at": "2026-03-02 08:00", "text": "DECISION: live"}]))

    worklog = Project.find(repo).worklog
    assert [(d.id, d.epoch, d.text) for d in worklog.decisions] == [
        ("D1", old.id, "from the archive"), ("D2", kept.id, "live")]
    assert [n.text for n in worklog.lookup(old.id)[0].notes] == ["kept note"]
    assert "DECISION" in archive.read_text()               # reading alone changed nothing

    project.add("write")                                   # the next write saves both
    stored = yaml.safe_load(archive.read_text())
    assert stored["version"] == 3
    assert [n["text"] for n in stored["items"][0]["notes"]] == ["kept note"]
    assert [d["text"] for d in _worklog(repo)["decisions"]] == ["from the archive", "live"]


def test_archiving_right_after_the_migration_keeps_both_files_whole(project, repo):
    keep = project.add("keep")
    old = project.add("old")
    project.close(old.id, "done")
    [(name, _)] = project.archive()
    archive = repo / ARCHIVE / name
    raw = yaml.safe_load(archive.read_text())
    raw["items"][0]["notes"] = [{"at": "2026-03-01 08:00", "text": "DECISION: archived one"}]
    archive.write_text(yaml.safe_dump(raw, sort_keys=False))
    _v2(repo, lambda r: None)
    newer = _fresh(project).add("closes next")
    _fresh(project).close(newer.id, "done")
    [(again, _)] = _fresh(project).archive()                # same month, same file
    assert again == name
    stored = yaml.safe_load(archive.read_text())
    assert {i["id"] for i in stored["items"]} == {old.id, newer.id}
    assert "DECISION" not in archive.read_text()
    assert [d["text"] for d in _worklog(repo)["decisions"]] == ["archived one"]
    assert keep.id


def test_a_worklog_with_no_decision_notes_migrates_to_no_decisions(project, repo):
    project.add("one")
    _v2(repo, lambda r: None)
    Project.find(repo).add("two")
    assert "decisions" not in _worklog(repo) and _worklog(repo)["version"] == 3


def test_an_older_clarity_ctl_cannot_write_a_version_3_worklog(project, repo):
    idea = project.add("one")
    project.decide(idea.id, "x")
    from clarity import store
    monkey = store.WORKLOG_VERSION
    try:
        store.WORKLOG_VERSION = 2                                # what the previous release was
        old = Project.find(repo)
        assert old.worklog.newer == 3
        with pytest.raises(ClarityError):
            old.add("nope")
    finally:
        store.WORKLOG_VERSION = monkey
