"""A handoff is a flag on a note: live until the next write on the item, then taken up.
Run: uv run -q --with pytest pytest -q tests/test_handoff.py"""

import json

import pytest
import yaml

from clarity import Project, agents, cli
from clarity.store import ARCHIVE


@pytest.fixture
def ctl(project, repo, capsys, monkeypatch):
    """ctl("note", "1", "text", "--handoff") -> (exit code, stdout, stderr), on `project`."""
    monkeypatch.chdir(repo)

    def run(*argv):
        code = cli.main([*argv])
        out, err = capsys.readouterr()
        return code, out, err
    return run


def _fresh(project) -> Project:
    return Project.find(project.root)


def _worklog(repo) -> dict:
    return yaml.safe_load((repo / "worklog.yaml").read_text())


def _digest(repo) -> str:
    text = (repo / "AGENTS.md").read_text()
    return text[text.index("### Where things stand"):text.index(agents.END)]


def _epoch(project, name="parser"):
    return project.start(project.add(name).id)[0]


def _notes(project, item):
    return _fresh(project).worklog.by_id(item.id).notes


# ---- writing ----------------------------------------------------------------------------


def test_a_handoff_is_a_note_with_a_live_flag(project, repo, ctl):
    epoch = _epoch(project)
    code, out, _ = ctl("note", str(epoch.id), "lexer done; start at parse_expr", "--handoff")
    assert code == 0 and out.startswith(f"handoff noted on {epoch.id} (1 so far)")
    [note] = _worklog(repo)["items"][0]["notes"]
    assert note["handoff"] == "live" and "taken_at" not in note
    assert note["text"] == "lexer done; start at parse_expr"      # no prefix stored
    assert _fresh(project).worklog.by_id(epoch.id).handoff == "lexer done; start at parse_expr"


def test_the_flag_goes_before_or_after_the_text(project, ctl):
    epoch = _epoch(project)
    assert ctl("note", str(epoch.id), "--handoff", "first")[0] == 0
    assert ctl("note", str(epoch.id), "second", "--handoff")[0] == 0
    texts = [(n.text, n.handoff) for n in _notes(project, epoch)]
    assert texts == [("first", "taken"), ("second", "live")]


def test_a_new_handoff_takes_up_the_previous_one(project, ctl):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "one", "--handoff")
    ctl("note", str(epoch.id), "two", "--handoff")
    first, second = _notes(project, epoch)
    assert first.handoff == "taken" and first.taken_at
    assert second.handoff == "live" and second.taken_at is None
    assert _fresh(project).worklog.by_id(epoch.id).live_handoff.text == "two"


# ---- taken up -----------------------------------------------------------------------------


def _live(project, ctl):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "half done", "--handoff")
    return epoch


def _taken(project, epoch) -> bool:
    [note] = [n for n in _notes(project, epoch) if n.text == "half done"]
    assert note.handoff in ("live", "taken")
    if note.handoff == "taken":
        assert note.taken_at
    return note.handoff == "taken"


def test_a_plain_note_takes_it_up(project, ctl):
    epoch = _live(project, ctl)
    ctl("note", str(epoch.id), "picked it up")
    assert _taken(project, epoch)


def test_a_note_with_on_takes_it_up(project, ctl):
    epoch = _epoch(project)
    project.decide(epoch.id, "stdlib only")
    ctl("note", str(epoch.id), "half done", "--handoff")
    assert ctl("note", str(epoch.id), "see the decision", "--on", "D1")[0] == 0
    assert _taken(project, epoch)


def test_a_decision_alone_takes_it_up(project, ctl):
    epoch = _live(project, ctl)
    assert ctl("note", str(epoch.id), "rule", "--decision")[0] == 0
    assert _taken(project, epoch)


def test_close_takes_it_up_done_or_dropped(project, ctl):
    done = _live(project, ctl)
    assert ctl("close", str(done.id), "all merged")[0] == 0
    assert _taken(project, done)
    dropped = _epoch(project, "other")
    ctl("note", str(dropped.id), "half done", "--handoff")
    assert ctl("close", str(dropped.id), "--drop", "no gain")[0] == 0
    [note] = _notes(project, dropped)
    assert note.handoff == "taken"


def test_a_read_does_not_take_it_up(project, ctl):
    epoch = _live(project, ctl)
    for argv in (("show", str(epoch.id)), ("show", str(epoch.id), "--json"), ("status",),
                 ("status", "--json"), ("show", "active"), ("search", "half")):
        assert ctl(*argv)[0] == 0
    assert not _taken(project, epoch)


def test_a_note_on_another_item_does_not_take_it_up(project, ctl):
    epoch = _live(project, ctl)
    other = _epoch(project, "other")
    ctl("note", str(other.id), "unrelated")
    ctl("note", str(other.id), "a rule", "--decision")
    assert not _taken(project, epoch)


def test_a_note_on_a_subepoch_does_not_touch_its_parent_and_the_reverse(project, ctl):
    parent = _epoch(project, "parent")
    child, _ = project.spawn(parent.id, "part")
    ctl("note", str(parent.id), "parent half done", "--handoff")
    ctl("note", child.id, "child half done", "--handoff")
    ctl("note", child.id, "child moves on")
    assert _fresh(project).worklog.by_id(parent.id).handoff == "parent half done"
    ctl("note", str(parent.id), "parent moves on")
    assert _fresh(project).worklog.by_id(parent.id).handoff is None


def test_generated_notes_do_not_take_it_up(project, ctl):
    epoch = _live(project, ctl)
    project.rename(epoch.id, "a better name")        # records a note of its own
    assert not _taken(project, epoch)


# ---- refusals -------------------------------------------------------------------------------


def test_refused_on_an_idea(project, ctl):
    idea = project.add("later")
    code, _, err = ctl("note", str(idea.id), "x", "--handoff")
    assert code == 4 and "idea" in err and "in flight" in err
    assert not _fresh(project).worklog.by_id(idea.id).notes


def test_refused_on_a_closed_epoch(project, ctl):
    epoch = _epoch(project)
    project.close(epoch.id, "done")
    code, _, err = ctl("note", str(epoch.id), "x", "--handoff")
    assert code == 4 and "done" in err


def test_refused_on_an_archived_epoch(project, ctl):
    epoch = _epoch(project)
    project.close(epoch.id, "done")
    project.archive()
    code, _, err = ctl("note", str(epoch.id), "x", "--handoff")
    assert code == 4 and "archived" in err


@pytest.mark.parametrize("extra", [["--decision"], ["--on", "D1"], ["--replaces", "D1"],
                                   ["--decision", "--replaces", "D1"]])
def test_refused_with_decision_on_or_replaces(project, ctl, extra):
    epoch = _epoch(project)
    project.decide(epoch.id, "a rule")
    code, _, err = ctl("note", str(epoch.id), "x", "--handoff", *extra)
    assert code == 2 and "--handoff" in err
    assert len(_notes(project, epoch)) == 0 and len(_fresh(project).worklog.decisions) == 1


@pytest.mark.parametrize("text", ["HANDOFF: left", "handoff: left", "  Handoff:left"])
def test_text_starting_handoff_is_refused_for_a_note_and_a_handoff(project, ctl, text):
    epoch = _epoch(project)
    for extra in ([], ["--handoff"]):
        code, _, err = ctl("note", str(epoch.id), text, *extra)
        assert code == 2 and "--handoff" in err
    assert _notes(project, epoch) == []


# ---- display ----------------------------------------------------------------------------------


def test_the_block_shows_a_handoff_only_while_it_is_live(project, repo, ctl):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "a plain note first")
    ctl("note", str(epoch.id), "parser half done", "--handoff")
    assert f"#{epoch.id} parser" in _digest(repo)
    assert "— handoff: parser half done" in _digest(repo)
    ctl("note", str(epoch.id), "took it up; lexer next")
    block = _digest(repo)
    assert "parser half done" not in block
    assert "last note: took it up; lexer next" in block


def test_a_taken_handoff_is_not_the_last_note_either(project, repo, ctl):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "a plain note first")
    ctl("note", str(epoch.id), "parser half done", "--handoff")
    ctl("note", str(epoch.id), "a rule", "--decision")        # takes it up, adds no note
    block = _digest(repo)
    assert "parser half done" not in block and "last note: a plain note first" in block


def test_the_block_budget_for_a_handoff_is_unchanged(project, repo, ctl):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "x" * 900, "--handoff")
    line = next(l for l in _digest(repo).splitlines() if "— handoff:" in l)
    assert len(line.split("— handoff: ")[1]) == 600


def test_show_piped_has_a_live_line_and_marks_the_note(project, ctl):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "parser half done", "--handoff")
    out = ctl("show", str(epoch.id))[1]
    [line] = [l for l in out.splitlines() if l.startswith("handoff (live, ")]
    assert line.endswith("): parser half done")
    assert "1. [" in out and "(handoff, live) parser half done" in out


def test_show_piped_marks_a_taken_handoff_in_the_notes_only(project, ctl):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "parser half done", "--handoff")
    ctl("note", str(epoch.id), "took it up")
    out = ctl("show", str(epoch.id))[1]
    assert not any(l.startswith("handoff (live") for l in out.splitlines())
    [note] = [l for l in out.splitlines() if l.startswith("1. [")]
    assert "(handoff, taken up " in note and note.endswith(") parser half done")


def test_show_on_a_terminal_has_a_handoff_section_and_marks(project, ctl, tty):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "parser half done", "--handoff")
    out = ctl("show", str(epoch.id))[1]
    assert "Handoff (live, " in out and out.index("Handoff (live") < out.index("Notes (1)")
    assert "handoff, live" in out
    ctl("note", str(epoch.id), "took it up")
    out = ctl("show", str(epoch.id))[1]
    assert "Handoff (live" not in out and "handoff, taken up " in out


def test_the_live_hint_follows_the_live_handoff_only(project, repo, git, commit, ctl):
    item = _epoch(project, "half done")
    commit(repo / item.folder / "wt" / repo.name, "p.txt")
    git(["merge", "-q", "--squash", item.branch], repo)
    git(["commit", "-qm", "land"], repo)
    nag = f"clarity-ctl close {item.id}"
    ctl("note", str(item.id), "the parser is left", "--handoff")
    assert nag not in _fresh(project).agent_status_text()
    ctl("note", str(item.id), "parser finished after all")
    assert nag in _fresh(project).agent_status_text()


def test_epoch_md_shows_the_live_handoff_and_marks_the_notes(project, repo, ctl):
    epoch = _epoch(project)
    page = repo / epoch.folder / "EPOCH.md"
    ctl("note", str(epoch.id), "parser half done", "--handoff")
    text = page.read_text()
    assert "## Handoff (live, " in text and "(handoff, live) parser half done" in text
    ctl("note", str(epoch.id), "took it up")
    text = page.read_text()
    assert "## Handoff" not in text and "(handoff, taken up " in text
    assert "took it up" in text                      # EPOCH.md keeps every note


def test_json_carries_the_live_handoff_and_the_note_fields(project, ctl):
    epoch = _epoch(project)
    ctl("note", str(epoch.id), "plain")
    ctl("note", str(epoch.id), "parser half done", "--handoff")
    data = json.loads(ctl("show", str(epoch.id), "--json")[1])["data"]
    assert data["handoff"]["text"] == "parser half done" and data["handoff"]["at"]
    assert [n.get("handoff") for n in data["notes"]] == [None, "live"]
    ctl("note", str(epoch.id), "took it up")
    data = json.loads(ctl("show", str(epoch.id), "--json")[1])["data"]
    assert data["handoff"] is None
    assert data["notes"][1]["handoff"] == "taken" and data["notes"][1]["taken_at"]
    listed = json.loads(ctl("status", "--json")[1])["data"]["items"]
    assert [i["handoff"] for i in listed if i["id"] == epoch.id] == [None]


# ---- migration --------------------------------------------------------------------------------


def _v3(repo, edit):
    path = repo / "worklog.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["version"] = 3
    edit(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def _by(raw, item_id):
    return next(i for i in raw["items"] if i["id"] == item_id)


def test_an_in_flight_epoch_whose_last_note_is_a_handoff_gets_a_live_one(project, repo):
    epoch = _epoch(project)
    _v3(repo, lambda r: _by(r, epoch.id).update(notes=[
        {"at": "2026-03-01 08:00", "text": "a plain note"},
        {"at": "2026-03-01 09:00", "text": "HANDOFF: stopped at the parser"}]))
    item = _fresh(project).worklog.by_id(epoch.id)
    assert item.handoff == "stopped at the parser"
    assert [n.text for n in item.notes] == ["a plain note", "stopped at the parser"]
    assert _worklog(repo)["version"] == 3                  # a read writes nothing
    project.add("next write")
    note = _by(_worklog(repo), epoch.id)["notes"][1]
    assert _worklog(repo)["version"] == 4
    assert note["handoff"] == "live" and note["text"] == "stopped at the parser"


def test_a_note_after_the_handoff_makes_it_taken_at_that_notes_time(project, repo):
    epoch = _epoch(project)
    _v3(repo, lambda r: _by(r, epoch.id).update(notes=[
        {"at": "2026-03-01 09:00", "text": "HANDOFF: stopped at the parser"},
        {"at": "2026-03-02 10:30", "text": "picked it up"}]))
    item = _fresh(project).worklog.by_id(epoch.id)
    assert item.handoff is None
    [first, _] = item.notes
    assert (first.handoff, first.taken_at) == ("taken", "2026-03-02 10:30")


def test_only_the_latest_of_several_handoffs_can_be_live(project, repo):
    epoch = _epoch(project)
    _v3(repo, lambda r: _by(r, epoch.id).update(notes=[
        {"at": "2026-03-01 09:00", "text": "HANDOFF: one"},
        {"at": "2026-03-02 09:00", "text": "HANDOFF: two"}]))
    one, two = _fresh(project).worklog.by_id(epoch.id).notes
    assert (one.handoff, one.taken_at) == ("taken", "2026-03-02 09:00")
    assert (two.handoff, two.taken_at) == ("live", None)


def test_a_closed_epochs_handoff_is_taken_at_its_end_date(project, repo):
    epoch = _epoch(project)
    project.close(epoch.id, "done")
    _v3(repo, lambda r: _by(r, epoch.id).update(ended="2026-03-05", notes=[
        {"at": "2026-03-01 09:00", "text": "HANDOFF: stopped"}]))
    [note] = _fresh(project).worklog.by_id(epoch.id).notes
    assert (note.text, note.handoff, note.taken_at) == ("stopped", "taken", "2026-03-05")


def test_a_handoff_on_an_idea_is_taken(project, repo):
    idea = project.add("odd")
    _v3(repo, lambda r: _by(r, idea.id).update(notes=[
        {"at": "2026-03-01 09:00", "text": "HANDOFF: stopped"}]))
    [note] = _fresh(project).worklog.by_id(idea.id).notes
    assert (note.handoff, note.taken_at) == ("taken", "2026-03-01 09:00")


def test_migration_reaches_handoff_notes_in_the_archive(project, repo):
    _epoch(project, "kept")
    old = _epoch(project, "old")
    project.close(old.id, "done")
    [(name, _)] = project.archive()
    archive = repo / ARCHIVE / name
    raw = yaml.safe_load(archive.read_text())
    raw["items"][0]["notes"] = [{"at": "2026-03-01 08:00", "text": "HANDOFF: from the archive"}]
    raw["version"] = 3
    archive.write_text(yaml.safe_dump(raw, sort_keys=False))
    _v3(repo, lambda r: None)

    [note] = _fresh(project).worklog.lookup(old.id)[0].notes
    assert (note.text, note.handoff) == ("from the archive", "taken")
    assert "HANDOFF:" in archive.read_text()               # reading alone changed nothing

    project.add("write")                                   # the next write saves both
    stored = yaml.safe_load(archive.read_text())
    assert stored["version"] == 4
    assert stored["items"][0]["notes"][0]["handoff"] == "taken"
    assert "HANDOFF:" not in archive.read_text()


def test_archiving_right_after_the_migration_keeps_the_file_whole(project, repo):
    _epoch(project, "kept")
    old = _epoch(project, "old")
    project.close(old.id, "done")
    [(name, _)] = project.archive()
    archive = repo / ARCHIVE / name
    raw = yaml.safe_load(archive.read_text())
    raw["items"][0]["notes"] = [{"at": "2026-03-01 08:00", "text": "HANDOFF: archived one"}]
    archive.write_text(yaml.safe_dump(raw, sort_keys=False))
    _v3(repo, lambda r: None)
    newer = _epoch(_fresh(project), "closes next")
    _fresh(project).close(newer.id, "done")
    [(again, _)] = _fresh(project).archive()
    assert again == name
    stored = yaml.safe_load(archive.read_text())
    assert {i["id"] for i in stored["items"]} == {old.id, newer.id}
    assert "HANDOFF:" not in archive.read_text()


def test_migrating_twice_changes_nothing():
    from clarity import store
    items = [{"id": 1, "status": "active", "notes": [
        {"at": "2026-03-01 09:00", "text": "HANDOFF: stopped"}]}]
    assert store._migrate_handoffs(items) is True
    once = yaml.safe_dump(items)
    assert store._migrate_handoffs(items) is False and yaml.safe_dump(items) == once


# ---- long note lists ---------------------------------------------------------------------------


def _many(project, count):
    epoch = _epoch(project)
    for n in range(1, count + 1):
        project.note(epoch.id, f"note number {n}")
    return epoch


def test_show_prints_the_ten_newest_notes_with_a_pointer(project, ctl):
    epoch = _many(project, 14)
    out = ctl("show", str(epoch.id))[1]
    lines = out.splitlines()
    assert "Notes (14)" in lines
    assert lines[lines.index("Notes (14)") + 1] == (
        f"… 4 older notes: clarity-ctl show {epoch.id} --all")
    numbered = [l for l in lines if l[:2].rstrip(". ").isdigit() and "[" in l]
    assert [l.split(".")[0] for l in numbered] == [str(n) for n in range(5, 15)]
    assert numbered[0].endswith("note number 5") and numbered[-1].endswith("note number 14")
    assert "note number 4" not in out


def test_all_prints_every_note_and_no_pointer(project, ctl):
    epoch = _many(project, 14)
    out = ctl("show", str(epoch.id), "--all")[1]
    assert "older note" not in out
    assert [l.split(".")[0] for l in out.splitlines() if l[:2].rstrip(". ").isdigit()
            and "[" in l] == [str(n) for n in range(1, 15)]
    assert ctl("show", "--all", str(epoch.id))[1] == out


def test_eleven_notes_read_in_the_singular(project, ctl):
    epoch = _many(project, 11)
    assert f"… 1 older note: clarity-ctl show {epoch.id} --all" in ctl("show", str(epoch.id))[1]


def test_ten_notes_have_no_pointer(project, ctl):
    epoch = _many(project, 10)
    out = ctl("show", str(epoch.id))[1]
    assert "older note" not in out and "1. [" in out


def test_the_terminal_page_keeps_real_numbers_too(project, ctl, tty):
    epoch = _many(project, 12)
    out = ctl("show", str(epoch.id))[1]
    assert "Notes (12)" in out and f"… 2 older notes: clarity-ctl show {epoch.id} --all" in out
    assert "  3. " in out and "  12. " in out and "  2. " not in out
    assert "  2. " in ctl("show", str(epoch.id), "--all")[1]


def test_json_caps_the_notes_and_says_how_many_are_left_out(project, ctl):
    epoch = _many(project, 14)
    data = json.loads(ctl("show", str(epoch.id), "--json")[1])["data"]
    assert data["notes_omitted"] == 4 and len(data["notes"]) == 10
    assert data["notes"][0]["text"] == "note number 5"
    data = json.loads(ctl("show", str(epoch.id), "--all", "--json")[1])["data"]
    assert data["notes_omitted"] == 0 and len(data["notes"]) == 14


def test_an_archived_item_is_capped_too(project, ctl):
    epoch = _many(project, 12)
    project.close(epoch.id, "done")
    project.archive()
    out = ctl("show", str(epoch.id))[1]
    assert f"… 2 older notes: clarity-ctl show {epoch.id} --all" in out
    lines = out.splitlines()
    assert any(l.startswith("3. [") for l in lines) and not any(l.startswith("2. [") for l in lines)
    assert any(l.startswith("2. [") for l in ctl("show", str(epoch.id), "--all")[1].splitlines())


def test_epoch_md_keeps_every_note(project):
    epoch = _many(project, 14)
    text = (project.root / epoch.folder / "EPOCH.md").read_text()
    assert all(f"note number {n}" in text for n in range(1, 15))


# ---- the instructions ----------------------------------------------------------------------------


def test_the_agent_text_names_the_flag_and_the_moment(project, repo):
    text = (repo / "AGENTS.md").read_text()
    assert "--handoff" in text and "HANDOFF:" not in text
    assert "last thing before you stop" in text and "taken up" in text
