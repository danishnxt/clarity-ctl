"""search: offline keyword search over the worklog, scored by match quality and rarity.
Run: uv run -q --with pytest pytest -q tests/test_search.py"""

import json

import pytest

from clarity import Item, cli
from clarity.model import Note
from clarity.search import search, terms


def _item(id_, name, *notes, outcome=None, brief=None, status="idea"):
    return Item(id=id_, name=name, status=status, outcome=outcome, brief=brief,
                notes=[Note(at="2026-01-01", text=t) for t in notes])


def _ids(hits):
    return [h.id for h in hits]


def test_exact_hit_ranks_above_no_hit():
    items = [_item(1, "unrelated"), _item(2, "lease host", "lease is the machine name"),
             _item(3, "other", "nothing here")]
    assert _ids(search(items, "lease")) == [2]


def test_rarer_term_outweighs_a_common_one():
    # "common" is in every item, "rare" in one: the item with rare wins
    items = [_item(1, "a1", "common words common"), _item(2, "a2", "common again"),
             _item(3, "a3", "common and rare"), _item(4, "a4", "common")]
    hits = search(items, "common rare")
    assert hits[0].id == 3
    only_common = search(items, "common")
    assert {h.id for h in only_common} == {1, 2, 3, 4}


def test_one_rare_term_beats_one_common_term():
    # item 9 matches only the common word and has the higher id, which would win a tie
    items = [_item(9, "c", "everyone"), _item(2, "d", "everyone"), _item(3, "e", "everyone"),
             _item(4, "w", "zebra"), _item(5, "v", "nothing")]
    assert _ids(search(items, "everyone zebra"))[0] == 4


def test_prefix_stem_match():
    items = [_item(1, "t", "the lease is held"), _item(2, "u", "unrelated")]
    assert _ids(search(items, "leases")) == [1]
    assert _ids(search([_item(1, "t", "branch merged")], "merge")) == [1]


def test_stem_needs_four_characters():
    # "re" is dropped as too short anyway; "pro" is a 3-char prefix of "process"
    assert search([_item(1, "t", "process")], "pro") == []


def test_typo_match():
    items = [_item(1, "t", "uses socket.gethostname for the host"), _item(2, "u", "else")]
    hits = search(items, "gethostnmae")
    assert _ids(hits) == [1]
    assert "gethostname" in hits[0].snippet


def test_typo_is_weaker_than_exact():
    items = [_item(1, "a", "gethostnmae"), _item(2, "b", "gethostname")]
    # both words appear once, so the weights are equal and only the match differs
    hits = search(items, "gethostname")
    assert _ids(hits) == [2, 1]
    assert hits[0].score > hits[1].score


def test_name_bonus():
    items = [_item(1, "plain", "lease"), _item(2, "lease", "other"), _item(3, "x", "nothing")]
    hits = search(items, "lease")
    # item 2 has the term in its name only; item 1 in a note only, and the higher id
    # would not win a tie, so the bonus is what puts 2 ahead of 1
    assert _ids(hits) == [2, 1]
    assert hits[0].score == pytest.approx(hits[1].score * 1.5)
    assert hits[0].field == "name" and hits[0].snippet == ""


def test_ties_go_to_the_newer_id_and_subepochs_sort_by_number():
    items = [_item(2, "a", "same"), _item(10, "b", "same"), _item("2.1", "c", "same")]
    assert _ids(search(items, "same")) == [10, "2.1", 2]


def test_snippet_names_the_field_with_the_best_match():
    item = _item(1, "thing", "first note says nothing", "the pgbouncer pool was too small",
                 outcome="shipped", brief="make it faster")
    hit = search([item], "pgbouncer")[0]
    assert hit.field == "note 2"
    assert "pgbouncer" in hit.snippet
    assert search([item], "faster")[0].field == "brief"
    assert search([item], "shipped")[0].field == "outcome"


def test_snippet_is_cut_around_the_match_with_ellipses():
    text = ("filler " * 40) + "the needle sits here " + ("padding " * 40)
    hit = search([_item(1, "t", text)], "needle")[0]
    assert "needle" in hit.snippet
    assert hit.snippet.startswith("…") and hit.snippet.endswith("…")
    assert len(hit.snippet) < 190


def test_short_text_is_shown_whole_and_whitespace_collapsed():
    hit = search([_item(1, "t", "a   short\nnote about leases")], "leases")[0]
    assert hit.snippet == "a short note about leases"


def test_limit():
    items = [_item(i, f"n{i}", "keyword") for i in range(1, 9)]
    assert len(search(items, "keyword")) == 5  # the default via the CLI; the function's too
    assert _ids(search(items, "keyword", limit=2)) == [8, 7]
    assert len(search(items, "keyword", limit=0)) == 8


def test_stopwords_and_one_character_tokens_alone_match_nothing():
    items = [_item(1, "t", "the thing is a what")]
    assert search(items, "the of is a what how") == []
    assert terms("what is the x") == []


def test_tokenising():
    assert terms("socket.gethostname --repo 4ba41a9 Socket") == [
        "socket", "gethostname", "repo", "4ba41a9"]
    assert search([_item(1, "t", "fixed in 4ba41a9")], "4ba41a9")[0].id == 1


# ---- the command ----

def _run(project, capsys, monkeypatch, *argv):
    monkeypatch.chdir(project.root)
    code = cli.main(["search", *argv])
    return code, capsys.readouterr().out


def test_cli_text_output(project, capsys, monkeypatch):
    item = project.add("lease host is a MAC address")
    project.note(item.id, "socket.gethostname returns the machine name")
    project.add("something else")
    code, out = _run(project, capsys, monkeypatch, "gethostname")
    lines = out.rstrip("\n").splitlines()
    assert code == 0
    assert lines[0] == f"#{item.id} idea lease host is a MAC address"
    assert lines[1].startswith("  note 1: ") and "gethostname" in lines[1]
    assert len(lines) == 2


def test_cli_searches_archived_items(project, capsys, monkeypatch):
    item = project.add("old thing")
    project.note(item.id, "the zanzibar cache was the culprit")
    project.close(item.id, outcome="not doing it", dropped=True)
    project.archive()
    code, out = _run(project, capsys, monkeypatch, "zanzibar")
    assert code == 0
    assert out.startswith(f"#{item.id} dropped old thing")
    code, out = _run(project, capsys, monkeypatch, "culprit", "--json")
    assert json.loads(out)["data"]["hits"][0]["id"] == item.id


def test_cli_json_envelope(project, capsys, monkeypatch):
    item = project.add("alpha")
    project.note(item.id, "the quokka matters")
    code, out = _run(project, capsys, monkeypatch, "the", "quokka", "--json")
    env = json.loads(out)
    assert code == 0 and env["ok"] is True and env["command"] == "search"
    assert env["data"]["query"] == ["quokka"]
    (hit,) = env["data"]["hits"]
    assert set(hit) == {"id", "name", "status", "score", "field", "snippet"}
    assert hit["id"] == item.id and hit["field"] == "note 1" and "quokka" in hit["snippet"]
    assert hit["score"] == round(hit["score"], 2) and hit["score"] > 0


def test_cli_limit(project, capsys, monkeypatch):
    for n in range(4):
        project.add(f"idea number {n} about widgets")
    _, out = _run(project, capsys, monkeypatch, "widgets", "--limit", "2", "--json")
    assert len(json.loads(out)["data"]["hits"]) == 2
    _, out = _run(project, capsys, monkeypatch, "widgets", "--json")
    assert len(json.loads(out)["data"]["hits"]) == 4


def test_cli_no_matches_is_not_an_error(project, capsys, monkeypatch):
    project.add("alpha")
    code, out = _run(project, capsys, monkeypatch, "nonexistentword")
    assert code == 0 and out.strip() == "no matches"
    code, out = _run(project, capsys, monkeypatch, "nonexistentword", "--json")
    assert code == 0
    assert json.loads(out)["data"] == {"query": ["nonexistentword"], "hits": []}


def test_cli_stopwords_alone_match_nothing(project, capsys, monkeypatch):
    project.add("the what is")
    code, out = _run(project, capsys, monkeypatch, "the", "what", "is")
    assert code == 0 and out.strip() == "no matches"


def test_cli_search_outside_a_project_is_refused(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["search", "x"]) == 3


def test_search_is_in_the_help(tmp_path, monkeypatch, capsys):
    top = cli.build_parser().format_help()
    assert "clarity-ctl search" in top
    reference = cli.reference_text()
    assert "## clarity-ctl search" in reference
    assert "$ clarity-ctl search lease host" in reference
